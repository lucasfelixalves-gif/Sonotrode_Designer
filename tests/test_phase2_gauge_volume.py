from __future__ import annotations

import math
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyvista as pv
import pytest

from scripts.app.controllers.setup_controller import (
    GAUGE_LIST_ITEM_TAG,
    GAUGE_OVERLAY_ACTOR_NAME,
    GAUGE_ROLE_NAME,
    compute_initial_gauge_bounds,
)
from scripts.app.state.project_session import ProjectSession
from scripts.app.workers.mesh_worker import MeshGenerationWorker
from scripts.app.workers.solver_worker import SolverWorker
from scripts.ccx_results_parser import (
    parse_dat_modal_results,
    parse_mesh_node_sets,
    select_longitudinal_mode,
)
from scripts.ccx_solver import (
    _normalize_mesh_for_ccx,
    build_frequency_deck,
    solve_frequency_case,
)
from scripts.meshing import (
    format_abaqus_set_block,
    mesh_step_to_inp,
    select_elements_in_bounds,
)
from scripts.modal_inspection_service import (
    get_available_modes_and_frequencies,
    load_base_result_mesh,
)
from ui_harness import _export_cylinder_step


def _parse_inp_blocks(inp_path: Path) -> dict[str, object]:
    """Parse *NODE, *ELEMENT, *ELSET, and *NSET directly from a CalculiX .inp file."""
    nodes: dict[int, tuple[float, float, float]] = {}
    elements: dict[int, list[int]] = {}
    elsets: dict[str, list[int]] = {}
    nsets: dict[str, list[int]] = {}

    section = None
    active_set_dict = None
    active_set_name = None

    for raw in inp_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith("*"):
            upper = line.upper()
            section = None
            active_set_dict = None
            active_set_name = None
            if upper.startswith("*NODE") and not upper.startswith("*NODE "):
                section = "NODE"
            elif upper.startswith("*ELEMENT"):
                section = "ELEMENT"
            elif upper.startswith("*ELSET"):
                m = re.search(r"\bELSET\s*=\s*([^,\s]+)", upper)
                if m:
                    active_set_dict = elsets
                    active_set_name = m.group(1).strip().upper()
                    elsets.setdefault(active_set_name, [])
            elif upper.startswith("*NSET"):
                m = re.search(r"\bNSET\s*=\s*([^,\s]+)", upper)
                if m:
                    active_set_dict = nsets
                    active_set_name = m.group(1).strip().upper()
                    nsets.setdefault(active_set_name, [])
            continue

        tokens = [t.strip() for t in line.split(",") if t.strip()]
        if section == "NODE" and len(tokens) >= 4:
            nodes[int(tokens[0])] = (float(tokens[1]), float(tokens[2]), float(tokens[3]))
        elif section == "ELEMENT" and len(tokens) >= 2:
            elements[int(tokens[0])] = [int(t) for t in tokens[1:]]
        elif active_set_dict is not None and active_set_name is not None:
            active_set_dict[active_set_name].extend(int(t) for t in tokens)

    return {"nodes": nodes, "elements": elements, "elsets": elsets, "nsets": nsets}


def _assert_ccx_set_block_syntax(inp_text: str, keyword: str, set_name: str) -> list[int]:
    lines = inp_text.splitlines()
    header_prefix = f"{keyword.upper()}, {keyword.upper().lstrip('*')}={set_name.upper()}"
    start_idx = None
    for idx, raw in enumerate(lines):
        if raw.strip().upper().startswith(header_prefix):
            start_idx = idx
            break
    assert start_idx is not None, f"Missing {header_prefix} in INP file"

    data_lines: list[str] = []
    for raw in lines[start_idx + 1:]:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("*"):
            break
        data_lines.append(stripped)

    assert data_lines, f"{header_prefix} block has no ID lines"
    assert not data_lines[-1].endswith(","), f"{header_prefix} final line has a trailing comma"

    collected_ids: list[int] = []
    for ln in data_lines:
        tokens = [t.strip() for t in ln.split(",") if t.strip()]
        assert 1 <= len(tokens) <= 16, f"{header_prefix} line exceeds 16 IDs: {ln}"
        assert all(t.isdigit() for t in tokens)
        collected_ids.extend(int(t) for t in tokens)
    return collected_ids


class _SpyPlotter:
    """Minimal spy matching the PyVista QtInteractor surface used by SetupController."""

    def __init__(self, trigger_initial_box_cb: bool = True) -> None:
        self.trigger_initial_box_cb = trigger_initial_box_cb
        self.box_widgets: list[dict] = []
        self.clear_box_calls = 0
        self.picking_enabled = False
        self.enable_picking_calls = 0
        self.disable_picking_calls = 0
        self.actors: dict[str, dict] = {}
        self.removed_actors: list[str] = []

    def add_mesh(self, mesh, **kwargs):
        name = kwargs.get("name", f"mesh_{len(self.actors)}")
        self.actors[name] = {"mesh": mesh, **kwargs}
        return name

    def remove_actor(self, name):
        self.removed_actors.append(name)
        self.actors.pop(name, None)

    def clear(self):
        self.actors.clear()

    def enable_element_picking(self, **kwargs):
        self.picking_enabled = True
        self.enable_picking_calls += 1
        self._pick_kwargs = kwargs

    def disable_picking(self):
        self.picking_enabled = False
        self.disable_picking_calls += 1

    def add_box_widget(self, *, callback, bounds, factor=1.0, rotation_enabled=True, color="orange"):
        rec = {
            "callback": callback,
            "bounds": list(bounds),
            "factor": factor,
            "rotation_enabled": rotation_enabled,
            "color": color,
        }
        self.box_widgets.append(rec)
        if self.trigger_initial_box_cb:
            callback(pv.Box(bounds=bounds))
        return rec

    def clear_box_widgets(self):
        self.clear_box_calls += 1
        self.box_widgets.clear()


# ---------------------------------------------------------------------------
# 1. State Persistence & Validation Tests
# ---------------------------------------------------------------------------
def test_session_gauge_bounds_storage_and_reset():
    """Verify gauge_bounds initializes to None, validates/normalizes bounds, and resets."""
    session = ProjectSession()
    assert session.gauge_bounds is None

    # Inverted bounds normalization (xmax < xmin, etc.)
    normalized = session.set_gauge_bounds([10, -10, 5, -5, 2, -2])
    assert normalized == [-10.0, 10.0, -5.0, 5.0, -2.0, 2.0]
    assert session.gauge_bounds == [-10.0, 10.0, -5.0, 5.0, -2.0, 2.0]
    assert all(isinstance(v, float) for v in session.gauge_bounds)

    # Direct assignment also normalizes
    session.gauge_bounds = (4, 1, 8, 2, 6, 3)
    assert session.gauge_bounds == [1.0, 4.0, 2.0, 8.0, 3.0, 6.0]

    # Invalid inputs rejected
    for bad in (
        None,
        [0.0, 1.0, 2.0],
        [0.0, 0.0, 0.0, 1.0, 0.0, 1.0],
        [0.0, math.nan, 0.0, 1.0, 0.0, 1.0],
        [0.0, math.inf, 0.0, 1.0, 0.0, 1.0],
        "012345",
    ):
        with pytest.raises(ValueError):
            session.set_gauge_bounds(bad)  # type: ignore[arg-type]

    session.clear_project_data()
    assert session.gauge_bounds is None

    session_source = (
        Path(__file__).resolve().parents[1]
        / "GUI_code"
        / "scripts"
        / "app"
        / "state"
        / "project_session.py"
    ).read_text(encoding="utf-8")
    assert "PySide6" not in session_source


# ---------------------------------------------------------------------------
# 2. Centroid Filtering Geometry Tests
# ---------------------------------------------------------------------------
def test_select_elements_in_bounds_exact_centroid_filtering():
    """Verify exact centroid filtering for 1st-order and boundary elements."""
    node_ids = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=int)
    node_coords = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [50.0, 50.0, 50.0],
            [51.0, 50.0, 50.0],
            [50.0, 51.0, 50.0],
            [50.0, 50.0, 51.0],
        ],
        dtype=float,
    )
    element_ids = np.array([101, 102], dtype=int)
    element_conn = np.array([[0, 1, 2, 3], [4, 5, 6, 7]], dtype=int)

    sel_elems, sel_nodes = select_elements_in_bounds(
        node_coords=node_coords,
        node_ids=node_ids,
        element_conn=element_conn,
        element_ids=element_ids,
        gauge_bounds=[-1.0, 2.0, -1.0, 2.0, -1.0, 2.0],
    )
    assert sel_elems == [101]
    assert sel_nodes == [1, 2, 3, 4]

    # Inclusive boundary: tet 1 centroid is exact (0.25, 0.25, 0.25)
    sel_elems_edge, _ = select_elements_in_bounds(
        node_coords=node_coords,
        node_ids=node_ids,
        element_conn=element_conn,
        element_ids=element_ids,
        gauge_bounds=[0.25, 1.0, 0.25, 1.0, 0.25, 1.0],
    )
    assert sel_elems_edge == [101]


def test_select_elements_in_bounds_second_order_and_empty():
    """Verify 10-node C3D10 mid-side nodes are all included and empty boxes return []."""
    corners = np.array(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
            [0.0, 0.0, 2.0],
        ],
        dtype=float,
    )
    midsides = np.array(
        [
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 1.0],
        ],
        dtype=float,
    )
    node_coords = np.vstack([corners, midsides])
    node_ids = np.arange(1, 11, dtype=int)
    element_ids = np.array([7], dtype=int)
    element_conn = np.arange(10, dtype=int).reshape(1, 10)

    sel_elems, sel_nodes = select_elements_in_bounds(
        node_coords=node_coords,
        node_ids=node_ids,
        element_conn=element_conn,
        element_ids=element_ids,
        gauge_bounds=[0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
    )
    assert sel_elems == [7]
    assert sel_nodes == list(range(1, 11))

    empty_elems, empty_nodes = select_elements_in_bounds(
        node_coords,
        node_ids,
        element_conn,
        element_ids,
        [100.0, 200.0, 100.0, 200.0, 100.0, 200.0],
    )
    assert empty_elems == []
    assert empty_nodes == []


# ---------------------------------------------------------------------------
# 3. Abaqus / CalculiX .inp Syntax Compliance Tests
# ---------------------------------------------------------------------------
def test_format_abaqus_set_block_strict_ccx_rules():
    """CalculiX requires <=16 items per line and no trailing commas."""
    ids = list(range(1, 36))
    for keyword, name in (("*ELSET", "GAUGE_VOL"), ("*NSET", "GAUGE_VOL_NODES")):
        block = format_abaqus_set_block(keyword, name, ids, per_line=16)
        lines = [ln.strip() for ln in block.strip().splitlines()]
        assert lines[0] == f"{keyword}, {keyword.lstrip('*')}={name}"
        data_lines = lines[1:]
        assert len(data_lines) == 3
        for ln in data_lines:
            tokens = [t.strip() for t in ln.split(",") if t.strip()]
            assert 1 <= len(tokens) <= 16
            assert all(t.isdigit() for t in tokens)
        assert not data_lines[-1].endswith(",")
        parsed_ids = [int(t) for t in re.findall(r"\d+", " ".join(data_lines))]
        assert parsed_ids == ids

    assert format_abaqus_set_block("*ELSET", "GAUGE_VOL", [], per_line=16) == ""
    with pytest.raises(ValueError):
        format_abaqus_set_block("*ELSET", "GAUGE_VOL", [1, 2], per_line=17)


# ---------------------------------------------------------------------------
# 4. End-to-End STEP-to-INP Meshing & ID Concordance Tests
# ---------------------------------------------------------------------------
def test_mesh_step_to_inp_writes_gauge_vol_and_preserves_legacy(tmp_path, capsys):
    """Run real Gmsh meshing with None, partial sub-box, and out-of-range gauge_bounds."""
    step_path = tmp_path / "Cyl_Test.step"
    _export_cylinder_step(step_path, length=60.0, radius=10.0)

    mesh_cfg = {
        "Element_order": 2,
        "Characteristic_length_min": 6.0,
        "Characteristic_length_max": 10.0,
        "Second_order_incomplete": 0,
    }

    # 1. Legacy run (gauge_bounds=None) must NOT contain GAUGE_VOL
    legacy_inp = tmp_path / "legacy_mesh.inp"
    mesh_step_to_inp(
        step_path=str(step_path),
        mesh_output_path=str(legacy_inp),
        mesh_config=mesh_cfg,
        gauge_bounds=None,
        quiet=True,
    )
    legacy_text = legacy_inp.read_text(encoding="utf-8", errors="ignore")
    assert "GAUGE_VOL" not in legacy_text
    assert "TYPE=C3D10" in legacy_text

    # 2. Partial sub-box covering middle third of the 60 mm cylinder
    sub_bounds = [-12.0, 12.0, 20.0, 40.0, -12.0, 12.0]
    vhcf_inp = tmp_path / "vhcf_mesh.inp"
    mesh_step_to_inp(
        step_path=str(step_path),
        mesh_output_path=str(vhcf_inp),
        mesh_config=mesh_cfg,
        gauge_bounds=sub_bounds,
        quiet=True,
    )
    vhcf_text = vhcf_inp.read_text(encoding="utf-8", errors="ignore")
    elset_ids = _assert_ccx_set_block_syntax(vhcf_text, "*ELSET", "GAUGE_VOL")
    nset_ids = _assert_ccx_set_block_syntax(vhcf_text, "*NSET", "GAUGE_VOL_NODES")

    parsed = _parse_inp_blocks(vhcf_inp)
    nodes = parsed["nodes"]
    elements = parsed["elements"]
    assert 0 < len(elset_ids) < len(elements)
    assert 0 < len(nset_ids) < len(nodes)

    # Independent parse-back check: centroids and constituent nodes match 100%
    expected_eids = []
    expected_nids = set()
    for eid, conn in elements.items():
        pts = np.array([nodes[nid] for nid in conn], dtype=float)
        cx, cy, cz = pts.mean(axis=0)
        if (
            sub_bounds[0] <= cx <= sub_bounds[1]
            and sub_bounds[2] <= cy <= sub_bounds[3]
            and sub_bounds[4] <= cz <= sub_bounds[5]
        ):
            expected_eids.append(eid)
            expected_nids.update(conn)

    assert sorted(elset_ids) == sorted(expected_eids)
    assert sorted(nset_ids) == sorted(expected_nids)

    # 3. Out-of-range box logs warning with both requested & mesh bounds, writes no empty block
    capsys.readouterr()
    miss_inp = tmp_path / "miss_mesh.inp"
    miss_bounds = [500.0, 600.0, 500.0, 600.0, 500.0, 600.0]
    mesh_step_to_inp(
        step_path=str(step_path),
        mesh_output_path=str(miss_inp),
        mesh_config=mesh_cfg,
        gauge_bounds=miss_bounds,
        quiet=True,
    )
    out = capsys.readouterr().out
    assert "No volume elements matched gauge_bounds=" in out
    assert "actual mesh bounds=" in out
    miss_text = miss_inp.read_text(encoding="utf-8", errors="ignore")
    assert "GAUGE_VOL" not in miss_text

    # Strict mode raises ValueError on empty match
    with pytest.raises(ValueError, match="No volume elements matched"):
        mesh_step_to_inp(
            step_path=str(step_path),
            mesh_output_path=str(tmp_path / "strict_miss.inp"),
            mesh_config=mesh_cfg,
            gauge_bounds=miss_bounds,
            strict_gauge_bounds=True,
            quiet=True,
        )


# ---------------------------------------------------------------------------
# 5. Solver Deck & Real CCX Execution Tests
# ---------------------------------------------------------------------------
def test_build_frequency_deck_preserves_gauge_sets_and_requests_stress(tmp_path):
    """Verify normalization preserves GAUGE_VOL sets and deck emits *EL FILE / S."""
    step_path = tmp_path / "Cyl_Deck.step"
    _export_cylinder_step(step_path, length=60.0, radius=10.0)
    mesh_inp = tmp_path / "Cyl_Deck_mesh.inp"
    mesh_step_to_inp(
        step_path=str(step_path),
        mesh_output_path=str(mesh_inp),
        mesh_config={
            "Element_order": 1,
            "Characteristic_length_min": 8.0,
            "Characteristic_length_max": 12.0,
        },
        gauge_bounds=[-12.0, 12.0, 15.0, 45.0, -12.0, 12.0],
        quiet=True,
    )

    normalized = _normalize_mesh_for_ccx(str(mesh_inp))
    assert "*ELSET, ELSET=GAUGE_VOL" in normalized
    assert "*NSET, NSET=GAUGE_VOL_NODES" in normalized
    assert "*ELSET, ELSET=Volume1" in normalized

    deck_path = tmp_path / "Cyl_Deck.inp"
    build_frequency_deck(
        mesh_inp_path=str(mesh_inp),
        deck_output_path=str(deck_path),
        material_config={
            "Density_kg_m^3": 4430.0,
            "Youngs_modulus_GPa": 114.0,
            "Poissons_ratio": 0.34,
        },
        step_config={
            "Step_type": "frequency",
            "Number_of_frequencies": 8,
            "Output_nsets": "YMIN,YMAX",
            "Output_variables": "U",
        },
    )
    deck_text = deck_path.read_text(encoding="utf-8")
    assert "*ELSET, ELSET=GAUGE_VOL" in deck_text
    assert "*NSET, NSET=GAUGE_VOL_NODES" in deck_text
    assert "*NODE FILE\nU" in deck_text
    assert "*EL FILE\nS" in deck_text
    assert "*NODE PRINT, NSET=YMIN\nU" in deck_text
    assert "*NODE PRINT, NSET=YMAX\nU" in deck_text
    assert "*EL PRINT" not in deck_text


@pytest.mark.slow
def test_ccx_solve_with_gauge_vol_and_stress_output(tmp_path):
    """Run bundled bin/ccx.exe on a GAUGE_VOL mesh and verify .frd STRESS + zero regressions."""
    project_dir = tmp_path / "ccx_proj"
    mesh_dir = project_dir / "03_Meshes_INP"
    results_dir = project_dir / "04_Results_CCX"
    mesh_dir.mkdir(parents=True)
    results_dir.mkdir(parents=True)

    step_path = tmp_path / "Cyl_Solve.step"
    _export_cylinder_step(step_path, length=60.0, radius=10.0)
    mesh_inp = mesh_dir / "Cyl_Solve_mesh.inp"
    mesh_step_to_inp(
        step_path=str(step_path),
        mesh_output_path=str(mesh_inp),
        mesh_config={
            "Element_order": 1,
            "Characteristic_length_min": 8.0,
            "Characteristic_length_max": 12.0,
        },
        gauge_bounds=[-12.0, 12.0, 15.0, 45.0, -12.0, 12.0],
        quiet=True,
    )

    solve_result = solve_frequency_case(
        mesh_inp_path=str(mesh_inp),
        results_dir=str(results_dir),
        material_config={
            "Density_kg_m^3": 4430.0,
            "Youngs_modulus_GPa": 114.0,
            "Poissons_ratio": 0.34,
        },
        step_config={
            "Step_type": "frequency",
            "Number_of_frequencies": 8,
            "Output_nsets": "YMIN,YMAX",
            "Output_variables": "U",
        },
    )
    assert solve_result["returncode"] == 0, solve_result["stdout"]
    log_text = Path(solve_result["log_path"]).read_text(encoding="utf-8", errors="ignore")
    assert "*ERROR" not in log_text.upper()

    frd_path = results_dir / "Cyl_Solve.frd"
    dat_path = results_dir / "Cyl_Solve.dat"
    assert frd_path.is_file()
    assert dat_path.is_file()
    assert "STRESS" in frd_path.read_text(encoding="utf-8", errors="ignore")

    # Verify legacy .dat and .frd parsers work seamlessly alongside STRESS blocks
    node_sets, node_count = parse_mesh_node_sets(str(mesh_inp))
    assert node_count > 0
    freqs, disps = parse_dat_modal_results(str(dat_path), node_sets)
    metrics = select_longitudinal_mode(disps, input_amplitude=10.0)
    assert metrics is not None and metrics["mode_index"] in freqs

    frd_modes = get_available_modes_and_frequencies(str(project_dir), "Cyl_Solve")
    assert metrics["mode_index"] in frd_modes
    mesh_pv, vec_name = load_base_result_mesh(str(project_dir), "Cyl_Solve", metrics["mode_index"])
    assert vec_name in mesh_pv.point_data


# ---------------------------------------------------------------------------
# 6. Worker Propagation Tests (Including Jacobian Fallback)
# ---------------------------------------------------------------------------
def test_workers_forward_gauge_bounds_including_fallback_remesh(tmp_path, monkeypatch):
    """Verify MeshGenerationWorker and SolverWorker (primary + fallback o1) pass gauge_bounds."""
    step_dir = tmp_path / "02_Geometry_STEP"
    step_dir.mkdir(parents=True)
    (step_dir / "SpecA.step").write_text("DUMMY", encoding="utf-8")

    expected_bounds = [-5.0, 5.0, 10.0, 30.0, -5.0, 5.0]
    mesh_calls: list[dict] = []

    def _fake_mesh_step_to_inp(**kwargs):
        mesh_calls.append(kwargs)
        out_path = Path(kwargs["mesh_output_path"])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("*NODE\n1, 0, 0, 0\n", encoding="utf-8")
        return str(out_path)

    import scripts.app.workers.mesh_worker as mesh_worker_mod
    import scripts.app.workers.solver_worker as solver_worker_mod

    monkeypatch.setattr(mesh_worker_mod, "mesh_step_to_inp", _fake_mesh_step_to_inp)
    monkeypatch.setattr(solver_worker_mod, "mesh_step_to_inp", _fake_mesh_step_to_inp)

    df_mesh = pd.DataFrame([{"Model_name": "*", "Element_order": 2}])
    mw = MeshGenerationWorker(
        project_dir=str(tmp_path),
        df_mesh=df_mesh,
        semantic_roles={},
        target_models=["SpecA"],
        gauge_bounds=expected_bounds,
    )
    mw.run()
    assert len(mesh_calls) == 1
    assert mesh_calls[0]["gauge_bounds"] == expected_bounds

    # Now test SolverWorker triggering Element_order=1 nonpositive jacobian fallback
    mesh_calls.clear()
    solve_calls: list[str] = []

    def _fake_solve_frequency_case(**kwargs):
        solve_calls.append(kwargs["mesh_inp_path"])
        if len(solve_calls) == 1:
            return {
                "returncode": 201,
                "stdout": " *ERROR: nonpositive jacobian detected in element 12",
                "stderr": "",
            }
        return {"returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(solver_worker_mod, "solve_frequency_case", _fake_solve_frequency_case)
    monkeypatch.setattr(solver_worker_mod, "parse_mesh_node_sets", lambda _p: ({}, 1))

    sw = SolverWorker(
        project_dir=str(tmp_path),
        df_mesh=df_mesh,
        df_material=pd.DataFrame([{"Model_name": "*"}]),
        df_step=pd.DataFrame([{"Model_name": "*"}]),
        semantic_roles={},
        input_amplitude=1.0,
        gauge_bounds=expected_bounds,
    )
    sw.run()

    assert len(mesh_calls) == 2
    assert mesh_calls[0]["gauge_bounds"] == expected_bounds
    assert mesh_calls[1]["gauge_bounds"] == expected_bounds
    assert mesh_calls[1]["mesh_config"]["Element_order"] == 1


# ---------------------------------------------------------------------------
# 7. Setup Tab UI & Mode Switching Tests
# ---------------------------------------------------------------------------
def test_compute_initial_gauge_bounds_helper():
    mesh_bounds = (-10.0, 10.0, 0.0, 60.0, -10.0, 10.0)
    init = compute_initial_gauge_bounds(mesh_bounds, existing_bounds=None, fraction=0.4)
    assert init == pytest.approx([-4.0, 4.0, 18.0, 42.0, -4.0, 4.0])

    saved = [-2.0, 2.0, 22.0, 38.0, -2.0, 2.0]
    assert compute_initial_gauge_bounds(mesh_bounds, existing_bounds=saved) == saved


@pytest.mark.ui
def test_setup_tab_gauge_box_mode_switching_overlay_and_picking(ui_harness, capsys):
    """Verify combo_roles mode switching, initial callback suppression, overlay, and clear."""
    win = ui_harness.win
    session = win.session
    ctrl = win.setup_controller

    combo_roles = ui_harness.widget("combo_roles")
    role_items = [combo_roles.itemText(i) for i in range(combo_roles.count())]
    assert GAUGE_ROLE_NAME in role_items

    spy_plotter = _SpyPlotter(trigger_initial_box_cb=True)
    win.widgets.plotter = spy_plotter
    ctrl._preview_mesh = pv.Box(bounds=(-10.0, 10.0, 0.0, 60.0, -10.0, 10.0))
    ctrl._preview_cad_id_array_name = None

    # 1. Selecting gauge role suppresses PyVista initial creation callback -> session stays None
    ui_harness.set_combo("combo_roles", GAUGE_ROLE_NAME)
    assert ctrl._gauge_selection_mode is True
    assert session.gauge_bounds is None
    assert len(spy_plotter.box_widgets) == 1
    assert spy_plotter.box_widgets[0]["rotation_enabled"] is False
    assert spy_plotter.box_widgets[0]["bounds"] == pytest.approx([-4.0, 4.0, 18.0, 42.0, -4.0, 4.0])

    # Face picking is ignored while in gauge mode
    ctrl.on_cell_picked(ctrl._preview_mesh.extract_cells([0]))
    assert session.last_picked_info is None

    # 2. Simulating user box drag saves session.gauge_bounds, renders non-pickable overlay, logs
    capsys.readouterr()
    dragged_bounds = [-3.0, 3.0, 21.0, 39.0, -3.0, 3.0]
    ctrl._on_gauge_box_updated(pv.Box(bounds=dragged_bounds))
    assert session.gauge_bounds == pytest.approx(dragged_bounds)
    assert GAUGE_OVERLAY_ACTOR_NAME in spy_plotter.actors
    overlay_actor = spy_plotter.actors[GAUGE_OVERLAY_ACTOR_NAME]
    assert overlay_actor["pickable"] is False
    assert overlay_actor["reset_camera"] is False
    assert overlay_actor["opacity"] == pytest.approx(0.25)

    out = capsys.readouterr().out + ui_harness.console_text()
    assert "[SetupController] Gauge bounds updated:" in out

    # Single gauge item in list_roles (updating in-place on second drag)
    list_roles = ui_harness.widget("list_roles")
    assert list_roles.count() == 1
    ctrl._on_gauge_box_updated(pv.Box(bounds=[-2.5, 2.5, 22.0, 38.0, -2.5, 2.5]))
    assert list_roles.count() == 1
    assert session.gauge_bounds == pytest.approx([-2.5, 2.5, 22.0, 38.0, -2.5, 2.5])

    # 3. Clicking btn_assign confirms gauge bounds without touching semantic_roles
    ui_harness.click("btn_assign")
    assert session.semantic_roles == {}
    assert list_roles.count() == 1

    # 4. Switching back to Tip - YMAX clears box widgets, keeps overlay, restores picking
    ui_harness.set_combo("combo_roles", 'Tip  - "YMAX"')
    assert ctrl._gauge_selection_mode is False
    assert spy_plotter.clear_box_calls >= 1
    assert spy_plotter.box_widgets == []
    assert spy_plotter.picking_enabled is True
    assert GAUGE_OVERLAY_ACTOR_NAME in spy_plotter.actors

    # 5. Re-entering gauge mode initializes box widget at saved bounds
    ui_harness.set_combo("combo_roles", GAUGE_ROLE_NAME)
    assert spy_plotter.box_widgets[0]["bounds"] == pytest.approx([-2.5, 2.5, 22.0, 38.0, -2.5, 2.5])

    # 6. Deleting gauge item clears session.gauge_bounds, overlay, and list item
    list_roles.setCurrentRow(0)
    assert list_roles.currentItem().data(0x0100) == GAUGE_LIST_ITEM_TAG
    ctrl._on_roles_delete_pressed()
    assert session.gauge_bounds is None
    assert GAUGE_OVERLAY_ACTOR_NAME not in spy_plotter.actors
    assert list_roles.count() == 0


@pytest.mark.ui
def test_gauge_bounds_reset_on_project_create_load_and_analytics_forward(
    ui_harness, dialog_recorder, synthetic_project, tmp_path, monkeypatch
):
    """Verify Create/Load Project reset gauge_bounds + overlay, and Analytics forwards bounds."""
    win = ui_harness.win
    session = win.session
    ctrl = win.setup_controller

    spy_plotter = _SpyPlotter(trigger_initial_box_cb=False)
    win.widgets.plotter = spy_plotter

    # Mutate gauge bounds & overlay
    bounds = [-3.0, 3.0, 20.0, 40.0, -3.0, 3.0]
    ctrl._on_gauge_box_updated(pv.Box(bounds=bounds))
    assert session.gauge_bounds == pytest.approx(bounds)
    assert GAUGE_OVERLAY_ACTOR_NAME in spy_plotter.actors
    assert ui_harness.widget("list_roles").count() == 1

    # Create New Project resets gauge state + overlay + list item
    dialog_recorder.existing_dir_queue.append(str(tmp_path))
    dialog_recorder.input_text_queue.append(("Phase2_New_Proj", True))
    ui_harness.click("btn_new_project")
    ui_harness.pump(80)
    assert session.gauge_bounds is None
    assert GAUGE_OVERLAY_ACTOR_NAME not in spy_plotter.actors
    assert ui_harness.widget("list_roles").count() == 0

    # Load Project resets gauge state + overlay + list item
    win.widgets.plotter = spy_plotter
    ctrl._on_gauge_box_updated(pv.Box(bounds=bounds))
    assert session.gauge_bounds == pytest.approx(bounds)

    # Restore plotter=None before real load_project so load_reference_model uses real/safe QtInteractor
    win.widgets.plotter = None
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))
    ui_harness.click("btn_load")
    ui_harness.pump(120)
    assert session.gauge_bounds is None
    assert ui_harness.widget("list_roles").count() == 0

    # Verify AnalyticsController.generate_selected_meshes passes session.gauge_bounds
    import scripts.app.controllers.analytics_controller as analytics_ctrl_mod

    captured_worker_args: list[dict] = []

    class _FakeMeshWorker:
        def __init__(self, **kwargs):
            captured_worker_args.append(kwargs)
            self.progress_updated = SimpleNamespace(connect=lambda *_a: None)
            self.status_updated = SimpleNamespace(connect=lambda *_a: None)
            self.finished = SimpleNamespace(connect=lambda *_a: None)

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(analytics_ctrl_mod, "MeshGenerationWorker", _FakeMeshWorker)

    session.set_gauge_bounds(bounds)
    ui_harness.switch_tab("Analytics")
    ui_harness.click_table_row(0)
    ui_harness.click("btn_generate_meshes")
    assert len(captured_worker_args) == 1
    assert captured_worker_args[0]["gauge_bounds"] == pytest.approx(bounds)
