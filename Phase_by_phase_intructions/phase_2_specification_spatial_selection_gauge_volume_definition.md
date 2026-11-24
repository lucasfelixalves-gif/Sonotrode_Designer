# Phase 2: Spatial Selection & Gauge Volume Definition

> **⚠️ CRITICAL AI DIRECTIVE: STRICT PRESERVATION OF INDEPENDENT BEHAVIORS**
> Do not alter any behavior, function, signal, or script that is not strictly related to the changes requested in this document. Existing pipelines—especially SolidWorks STEP export handling, existing surface semantic role picking (`YMAX`, `YMIN`, etc.), the core Gmsh volume meshing algorithm, and the logic that merges geometrical parameters into the final pandas DataFrame—must remain completely untouched. Legacy workflows where `gauge_bounds` is `None` must continue to operate identically to before.

---

## 1. Objective & Detailed Intended Behavior

In ultrasonic Very High Cycle Fatigue (VHCF) testing, failure is governed by localized stress inside the specimen's narrowest region (the gauge section), not by global tip displacement. Because internal finite elements cannot be selected by clicking an outer CAD surface, Phase 2 introduces a **3D Spatial Bounding Box** in the Setup Tab and bridges its coordinates directly into the Gmsh meshing engine and CalculiX solver deck.

### 1.1. Semantic Role Extension & Safe Mode Switching (Setup Tab)
1. **New Semantic Role:** The existing semantic role dropdown on the Setup Tab gains a new option:
   * `"Gauge Section (Stress Harvesting)"`
2. **Coexistence with Surface Face Picking (CRITICAL):**
   * When the user selects any **existing surface role** (e.g., `Tip - "YMAX"`, `Base - "YMIN"`), the 3D PyVista viewer must operate in its original **surface face-picking mode**. Any active interactive bounding box widget must be deactivated/hidden so it does not intercept mouse clicks meant for surface faces.
   * When the user selects **`"Gauge Section (Stress Harvesting)"`**, the 3D PyVista viewer must cleanly transition to **Bounding Box selection mode**:
     * Surface face-picking callbacks are temporarily paused/ignored so dragging the box handles does not accidentally assign surface roles.
     * An interactive PyVista 3D box widget (`add_box_widget`) appears over the loaded preview mesh (`temp_ref.vtk`).

### 1.2. Interactive 3D Bounding Box Workflow
1. **Smart Initialization:**
   * If `self.session.gauge_bounds` is `None`, the bounding box initializes centered on the loaded preview mesh's geometric center, spanning roughly 30%–50% of the mesh's bounding box dimensions (so it is immediately visible and easy to grab without obscuring the entire model).
   * If `self.session.gauge_bounds` already exists (e.g., the user is refining a previous selection), the box widget initializes at those exact saved bounds.
2. **Manipulation & Coordinate Extraction:**
   * The user drags the 6 face handles of the PyVista box widget to envelope the specimen's gauge section (e.g., the narrow neck of a flat/longitudinal specimen, or the central biaxial zone of a disc specimen).
   * Rotation of the box widget must be **disabled** (`rotation_enabled=False`) so the selected region remains a strict Axis-Aligned Bounding Box (AABB) defined unambiguously by 6 coordinates:
     $$[x_{\min}, x_{\max}, y_{\min}, y_{\max}, z_{\min}, z_{\max}]$$
   * Whenever the user finishes dragging or confirms the selection (via the widget callback and/or an explicit "Assign Role" / "Confirm Gauge Volume" button), the controller extracts the exact axis-aligned bounds from the box's polydata and saves them to `self.session.gauge_bounds`.
3. **Persistent Visual Confirmation (Translucent Overlay):**
   * Once bounds are saved, the viewer renders a **translucent geometric box** (e.g., `pyvista.Box(bounds=gauge_bounds)`, color `"red"` or `"orange"`, `opacity=0.25`, with wireframe edges visible) under a dedicated named actor (e.g., `name="gauge_vol_overlay"`).
   * This translucent overlay remains visible even after the user switches back to another semantic role (such as `YMAX` or `YMIN`), giving continuous visual proof of where stress will be harvested.
   * Re-selecting or updating the box replaces the existing `"gauge_vol_overlay"` actor cleanly without duplicating actors in the VTK scene.
   * Clearing/resetting the project removes the overlay actor and clears the box widget.

### 1.3. State Persistence & Batch Pipeline Propagation
1. **Session Storage:** `ProjectSession` stores `self.gauge_bounds: list[float] | None = None`.
   * Bounds are always stored in strict VTK/PyVista order: `[xmin, xmax, ymin, ymax, zmin, zmax]` as standard Python `float`s, guaranteed to satisfy $x_{\min} < x_{\max}$, $y_{\min} < y_{\max}$, and $z_{\min} < z_{\max}$.
   * Resetting or loading a new project resets `self.gauge_bounds = None`.
2. **Worker Propagation:**
   * Both `MeshWorker` and `SolverWorker` must receive `gauge_bounds` from `ProjectSession` and forward it into `mesh_step_to_inp(...)`.
   * **Fallback Remesh Preservation:** In `SolverWorker`, if CalculiX aborts with a `nonpositive jacobian` error and triggers the automatic `Element_order=1` fallback remesh, `gauge_bounds` **must also be passed** to the fallback `mesh_step_to_inp(...)` call so `GAUGE_VOL` is not silently lost.

### 1.4. Meshing Engine Behavior (`scripts/meshing.py`)
1. **Centroid-Based Volume Element Filtering:**
   * After Gmsh generates the 3D volume mesh and converts it into Abaqus `.inp` volume elements (e.g., `C3D10` or `C3D4`), if `gauge_bounds` is provided:
     1. For every 3D volume element $e$ in the mesh, compute its geometric centroid $\mathbf{c}_e = (c_x, c_y, c_z)$ as the arithmetic mean of the coordinates of its corner/all constituent nodes:
        $$\mathbf{c}_e = \frac{1}{N_e} \sum_{i=1}^{N_e} \mathbf{p}_i$$
     2. Select all volume elements whose centroids fall inclusively within the AABB:
        $$x_{\min} \le c_x \le x_{\max} \quad \land \quad y_{\min} \le c_y \le y_{\max} \quad \land \quad z_{\min} \le c_z \le z_{\max}$$
     3. Collect the unique, sorted 1-based element IDs for `GAUGE_VOL`, and collect the unique, sorted 1-based node IDs belonging to those selected elements for `GAUGE_VOL_NODES`.
2. **Abaqus/CalculiX `.inp` Output Format:**
   * Append two valid sets to the generated `*_mesh.inp` file:
     * `*ELSET, ELSET=GAUGE_VOL`
     * `*NSET, NSET=GAUGE_VOL_NODES`
   * **Strict CalculiX Formatting:** Every ID line must contain at most **16 comma-separated integers per line**, with no trailing comma on the final line of a set block. All IDs must be strictly 1-based and match the exact node/element numbering written in `*NODE` and `*ELEMENT`.
3. **Edge-Case Handling:**
   * If `gauge_bounds is None`: Skip `GAUGE_VOL` generation entirely (100% backward-compatible with legacy sonotrode meshing).
   * If `gauge_bounds` is provided, **but 0 volume elements fall inside the box**: Log a loud, explicit warning (or raise a descriptive `ValueError` if strict mode is active) stating the requested bounds vs. the actual mesh bounds `[mx_min, mx_max, my_min, my_max, mz_min, mz_max]`, and **do not write an empty `*ELSET, ELSET=GAUGE_VOL` block** (an empty ELSET causes CalculiX to abort with a syntax error).

### 1.5. Solver Deck Stress Output (`scripts/ccx_solver.py`)
1. **Enabling Stress Output:**
   * When generating the CalculiX frequency analysis deck (`.inp` in `04_Results_CCX/`), detect whether the normalized mesh contains `ELSET=GAUGE_VOL` (or `NSET=GAUGE_VOL_NODES`).
   * Preserve all existing displacement output cards (`*NODE PRINT` / `*NODE FILE` for `U` on `YMIN`, `YMAX`, etc.).
   * Ensure the frequency step requests **stress tensor output (`S`)** in the `.frd` file (via `*EL FILE` with `S`—or `*NODE FILE` with `U` and `*EL FILE` with `S`) so CalculiX writes nodal/elemental stress tensors for Phase 3 parsing and Phase 4 3D colormaps.
   * Optionally, if `GAUGE_VOL` exists, include `*EL PRINT, ELSET=GAUGE_VOL` with `S` (or rely on `.frd` stress output as designed—document clearly which file carries the stress tensor so Phase 3 matches it).

---

## 2. Required AI Agent Skills & Domain Knowledge

Before modifying the codebase, the AI agent executing this phase must apply the following technical skills:

* **PyVista Interactive Widgets (`pyvistaqt.QtInteractor`):**
  * Mastery of `plotter.add_box_widget(callback=..., bounds=..., factor=1.0, rotation_enabled=False, color=...)` and `plotter.clear_box_widgets()`.
  * Understanding how `callback(polydata)` receives a `pyvista.PolyData` representing the box, from which `polydata.bounds` returns `(xmin, xmax, ymin, ymax, zmin, zmax)`.
  * Safe actor lifecycle management using `plotter.add_mesh(..., name="gauge_vol_overlay")` and `plotter.remove_actor("gauge_vol_overlay")` without triggering VTK segfaults.
* **3D Computational Geometry & NumPy Vectorization:**
  * Computing element centroids for thousands of 3D tetrahedral elements (`C3D4` / `C3D10`) efficiently using NumPy array indexing (`node_coords[elem_conn].mean(axis=1)`), avoiding slow Python loops.
  * Handling coordinate system consistency between the preview mesh (`temp_ref.vtk`) and the final Gmsh volume mesh (`*_mesh.inp`).
* **Abaqus / CalculiX `.inp` Syntax:**
  * Strict adherence to CalculiX card rules: 1-based indexing, maximum 16 entries per line, no empty `*ELSET`/`*NSET` definitions, and valid placement of `*EL FILE` / `*NODE FILE` inside the `*STEP` ... `*END STEP` frequency block.
  * Understanding how `ccx_solver.py` normalizes mesh `.inp` files so that `ELSET=GAUGE_VOL` and `NSET=GAUGE_VOL_NODES` are preserved during normalization.
* **Asynchronous Worker Plumbing (PySide6 `QThread` / Workers):**
  * Tracing data flow from `ProjectSession` $\rightarrow$ `SetupController` $\rightarrow$ `MeshWorker` / `SolverWorker` $\rightarrow$ `meshing.py` / `ccx_solver.py`, including error/fallback retry paths.

---

## 3. Step-by-Step Implementation Plan

Execute these steps in exact sequential order. Do not skip ahead.

### Step 2.1: Extend the State Model
* **Target File:** `scripts/app/state/project_session.py`
* **Action:**
  1. Add `self.gauge_bounds: list[float] | None = None` in `__init__`.
  2. Reset `self.gauge_bounds = None` inside `reset()` / `clear()`.
  3. Add a small helper method `set_gauge_bounds(self, bounds)` that validates `len(bounds) == 6`, converts all entries to `float`, ensures `(xmin < xmax, ymin < ymax, zmin < zmax)` (sorting pairs if inverted), and stores `[xmin, xmax, ymin, ymax, zmin, zmax]`.

### Step 2.2: Add Pure Helper Functions for Bounds & INP Formatting
* **Target File:** `scripts/meshing.py` (or a small dedicated helper section at the top of `meshing.py`)
* **Action:**
  1. Write a pure, unit-testable function:
     ```python
     def select_elements_in_bounds(
         node_coords: np.ndarray,
         node_ids: np.ndarray,
         element_conn: np.ndarray,
         element_ids: np.ndarray,
         gauge_bounds: list[float],
     ) -> tuple[list[int], list[int]]:
         """
         Return sorted 1-based (selected_element_ids, selected_node_ids)
         whose element centroids lie within [xmin, xmax, ymin, ymax, zmin, zmax].
         """
     ```
  2. Write a pure, unit-testable formatter function:
     ```python
     def format_abaqus_set_block(keyword: str, name: str, ids: list[int], per_line: int = 16) -> str:
         """
         Format *ELSET or *NSET block with <=16 comma-separated IDs per line
         and no trailing comma on the final line.
         """
     ```
  3. Integrate both helpers into `mesh_step_to_inp(..., gauge_bounds=None)`:
     * Keep `gauge_bounds=None` as an optional keyword argument with default `None` so all existing callers remain unbroken.
     * After writing `*NODE`, `*ELEMENT`, and existing surface `*NSET` blocks, if `gauge_bounds is not None`:
       * Call `select_elements_in_bounds(...)` on the volume elements actually written to the `.inp`.
       * If `selected_element_ids` is non-empty, append `*ELSET, ELSET=GAUGE_VOL` and `*NSET, NSET=GAUGE_VOL_NODES`.
       * If empty, print/log a clear warning with both `gauge_bounds` and the mesh's actual coordinate bounds, and do **not** write empty set cards.

### Step 2.3: Update Solver Deck Generation for Stress Output
* **Target File:** `scripts/ccx_solver.py`
* **Action:**
  1. Verify that mesh normalization (`normalize_mesh_inp` or equivalent) preserves `*ELSET, ELSET=GAUGE_VOL` and `*NSET, NSET=GAUGE_VOL_NODES` untouched.
  2. In the frequency step writer, ensure `*EL FILE` includes `S` (stress tensor) in addition to `*NODE FILE` `U`, so `.frd` files always contain modal stress fields when solving VHCF specimens.
  3. Confirm that existing `*NODE PRINT` outputs for `YMIN` and `YMAX` remain untouched so legacy `.dat` parsing continues to work without regressions.

### Step 2.4: Propagate `gauge_bounds` Through Workers
* **Target Files:** `scripts/app/workers/mesh_worker.py` and `scripts/app/workers/solver_worker.py`
* **Action:**
  1. Add `gauge_bounds=None` to the worker constructors (`__init__`) and store `self.gauge_bounds = gauge_bounds`.
  2. Pass `gauge_bounds=self.gauge_bounds` into every call to `mesh_step_to_inp(...)`—including the `Element_order=1` Jacobian fallback remesh in `solver_worker.py`.

### Step 2.5: Implement 3D Bounding Box UI in Setup Controller
* **Target File:** `scripts/app/controllers/setup_controller.py`
* **Action:**
  1. Add `"Gauge Section (Stress Harvesting)"` to the semantic role combo box items (either in `MainWindow.ui` or where role items are populated in `setup_controller.py`—check where existing roles like `"YMAX"`/`"YMIN"` are defined and follow the exact same pattern).
  2. Connect the role dropdown's `currentTextChanged` signal to a mode-switching handler:
     * If `"Gauge Section (Stress Harvesting)"` is selected and a preview mesh is loaded:
       * Pause surface-picking assignment.
       * Compute initial bounds (use `self.session.gauge_bounds` if present; otherwise compute a centered 40% sub-box of the preview mesh's bounds).
       * Activate `self.plotter.add_box_widget(callback=self._on_gauge_box_updated, bounds=init_bounds, factor=1.0, rotation_enabled=False)`.
     * If any other semantic role is selected:
       * Call `self.plotter.clear_box_widgets()`.
       * Resume normal surface face picking.
  3. Implement `_on_gauge_box_updated(self, box_polydata)`:
     * Extract `bounds = list(box_polydata.bounds)`.
     * Update `self.session.set_gauge_bounds(bounds)`.
     * Render/update the translucent overlay mesh (`pyvista.Box(bounds=bounds)`, `color="orange"`, `opacity=0.25`, `show_edges=True`, `name="gauge_vol_overlay"`).
     * Log the updated bounds to the console: `[SetupController] Gauge bounds updated: [xmin, xmax, ymin, ymax, zmin, zmax]`.
  4. Pass `gauge_bounds=self.session.gauge_bounds` when instantiating `MeshWorker` and `SolverWorker`.
  5. On project reset/load, clear box widgets and remove the `"gauge_vol_overlay"` actor.

---

## 4. The Critical Need for Testing in Phase 2

Phase 2 is the **highest-risk integration boundary** in the entire VHCF Specimen Designer upgrade. Unlike Phase 1 (pure UI/state), Phase 2 bridges two completely different domains:
1. **Interactive 3D OpenGL/VTK graphics** (where an AI coding agent *cannot visually see* the render window to verify handle dragging, overlay opacity, or face-picking interference).
2. **Strict text-based FEA solver decks** (where a single formatting mistake—such as 0-based node indexing, a trailing comma, >16 IDs on a line, an empty `*ELSET`, or a coordinate mismatch—causes CalculiX `ccx.exe` to abort silently or evaluate stress on the wrong part of the specimen).

**Rule:** Phase 2 is **NOT** considered complete until **both** the automated `pytest` verification suite (Section 4.1) AND the manual human-in-the-loop 3D + CCX inspection checklist (Section 4.2) pass 100%.

### 4.1. Automated Test Suite (`tests/test_phase2_gauge_volume.py`)

Create and run `tests/test_phase2_gauge_volume.py` via `pytest` in the `sonotrode_lab` environment. This suite validates all deterministic math, state persistence, `.inp` syntax rules, and solver deck generation without requiring a live GPU.

```python
import os
import sys
import re
import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from app.state.project_session import ProjectSession
from meshing import select_elements_in_bounds, format_abaqus_set_block


# ---------------------------------------------------------------------------
# 1. State Persistence & Validation Tests
# ---------------------------------------------------------------------------
def test_session_gauge_bounds_storage_and_reset():
    """Verify gauge_bounds initializes to None, validates/normalizes bounds, and resets."""
    session = ProjectSession()
    assert session.gauge_bounds is None

    # Test inverted bounds normalization (xmax < xmin)
    session.set_gauge_bounds([10.0, -10.0, 5.0, -5.0, 2.0, -2.0])
    assert session.gauge_bounds == [-10.0, 10.0, -5.0, 5.0, -2.0, 2.0]
    assert all(isinstance(v, float) for v in session.gauge_bounds)

    # Test invalid length rejection
    with pytest.raises(ValueError):
        session.set_gauge_bounds([0.0, 1.0, 2.0])

    # Test reset clears gauge_bounds
    if hasattr(session, "reset"):
        session.reset()
    else:
        session.clear()
    assert session.gauge_bounds is None


# ---------------------------------------------------------------------------
# 2. Centroid Filtering Geometry Tests
# ---------------------------------------------------------------------------
def test_select_elements_in_bounds_exact_centroid_filtering():
    """
    Create a synthetic 2-tetrahedron mesh:
      - Element 101 centroid at (0.25, 0.25, 0.25) -> INSIDE gauge box
      - Element 102 centroid at (50.25, 50.25, 50.25) -> OUTSIDE gauge box
    Verify only Element 101 and its exact 1-based nodes are selected.
    """
    node_ids = np.array([1, 2, 3, 4, 5, 6, 7, 8], dtype=int)
    node_coords = np.array([
        # Tet 1 (near origin)
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        # Tet 2 (far away)
        [50.0, 50.0, 50.0],
        [51.0, 50.0, 50.0],
        [50.0, 51.0, 50.0],
        [50.0, 50.0, 51.0],
    ], dtype=float)

    element_ids = np.array([101, 102], dtype=int)
    # 0-based indices into node_coords (or 1-based depending on helper signature; match implementation)
    element_conn = np.array([
        [0, 1, 2, 3],
        [4, 5, 6, 7],
    ], dtype=int)

    bounds = [-1.0, 2.0, -1.0, 2.0, -1.0, 2.0]
    sel_elems, sel_nodes = select_elements_in_bounds(
        node_coords=node_coords,
        node_ids=node_ids,
        element_conn=element_conn,
        element_ids=element_ids,
        gauge_bounds=bounds,
    )

    assert sel_elems == [101]
    assert sel_nodes == [1, 2, 3, 4]


def test_select_elements_in_bounds_empty_box():
    """Verify an out-of-range bounding box cleanly returns empty lists without crashing."""
    node_ids = np.array([1, 2, 3, 4], dtype=int)
    node_coords = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=float)
    element_ids = np.array([1], dtype=int)
    element_conn = np.array([[0, 1, 2, 3]], dtype=int)

    sel_elems, sel_nodes = select_elements_in_bounds(
        node_coords, node_ids, element_conn, element_ids, [100.0, 200.0, 100.0, 200.0, 100.0, 200.0]
    )
    assert sel_elems == []
    assert sel_nodes == []


# ---------------------------------------------------------------------------
# 3. Abaqus / CalculiX .inp Syntax Compliance Tests
# ---------------------------------------------------------------------------
def test_format_abaqus_set_block_strict_ccx_rules():
    """
    CalculiX rejects lines with >16 items or trailing commas on the last line.
    Verify formatting for 35 IDs (2 full lines of 16 + 1 line of 3).
    """
    ids = list(range(1, 36))
    block = format_abaqus_set_block("*ELSET", "GAUGE_VOL", ids, per_line=16)
    lines = [ln.strip() for ln in block.strip().splitlines()]

    assert lines[0] == "*ELSET, ELSET=GAUGE_VOL"
    data_lines = lines[1:]
    assert len(data_lines) == 3

    # Each data line must have <= 16 integers
    for ln in data_lines:
        tokens = [t.strip() for t in ln.split(",") if t.strip()]
        assert len(tokens) <= 16
        assert all(t.isdigit() for t in tokens)

    # Final line must NOT end with a trailing comma
    assert not data_lines[-1].endswith(",")

    # All IDs preserved in order
    parsed_ids = [int(t) for t in re.findall(r"\d+", " ".join(data_lines))]
    assert parsed_ids == ids


# ---------------------------------------------------------------------------
# 4. End-to-End STEP-to-INP Integration Test (if a sample STEP exists)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.environ.get("TEST_STEP_FILE"),
    reason="Set TEST_STEP_FILE=/path/to/specimen.step to run real Gmsh STEP-to-INP test",
)
def test_mesh_step_to_inp_writes_gauge_vol_and_preserves_legacy(tmp_path):
    """Run real Gmsh meshing with and without gauge_bounds on a sample STEP file."""
    from meshing import mesh_step_to_inp

    step_path = os.environ["TEST_STEP_FILE"]
    mesh_cfg = {
        "Element_order": 2,
        "Characteristic_length_min": 2.0,
        "Characteristic_length_max": 4.0,
        "Second_order_incomplete": 0,
    }

    # 1. Legacy run (gauge_bounds=None) must NOT contain GAUGE_VOL
    legacy_inp = tmp_path / "legacy_mesh.inp"
    mesh_step_to_inp(
        step_path=step_path,
        mesh_output_path=str(legacy_inp),
        mesh_config=mesh_cfg,
        gauge_bounds=None,
        quiet=True,
    )
    legacy_text = legacy_inp.read_text(encoding="utf-8", errors="ignore")
    assert "GAUGE_VOL" not in legacy_text

    # 2. VHCF run with wide bounds covering the entire model MUST contain GAUGE_VOL
    vhcf_inp = tmp_path / "vhcf_mesh.inp"
    mesh_step_to_inp(
        step_path=step_path,
        mesh_output_path=str(vhcf_inp),
        mesh_config=mesh_cfg,
        gauge_bounds=[-1e6, 1e6, -1e6, 1e6, -1e6, 1e6],
        quiet=True,
    )
    vhcf_text = vhcf_inp.read_text(encoding="utf-8", errors="ignore")
    assert "*ELSET, ELSET=GAUGE_VOL" in vhcf_text
    assert "*NSET, NSET=GAUGE_VOL_NODES" in vhcf_text
```

### 4.2. Mandatory Human-in-the-Loop 3D Visual & CCX Smoke Test Checklist

After `pytest tests/test_phase2_gauge_volume.py` passes completely, the human engineer **must** execute the following visual and solver verification in `python scripts/main.py`:

1. **3D Box Widget & Face Picking Coexistence:**
   - [ ] Load a project with at least one `.step` specimen and click it in the Setup list so the 3D preview renders.
   - [ ] Select `Base - "YMIN"` and click a face on the mesh. Confirm normal face picking still highlights and assigns the face.
   - [ ] Switch the semantic role dropdown to `"Gauge Section (Stress Harvesting)"`. Confirm the interactive 3D box widget appears without crashing and cannot be rotated.
   - [ ] Drag the box handles to tightly wrap the narrow gauge section of the specimen. Confirm the terminal prints `[SetupController] Gauge bounds updated: [...]` and a translucent overlay box appears in the exact dragged location.
   - [ ] Switch back to `Tip - "YMAX"`. Confirm the interactive drag handles disappear, the translucent overlay box remains visible, and face clicking works normally again.
2. **Manual `.inp` File Inspection:**
   - [ ] Run meshing on the specimen. Open the generated `03_Meshes_INP/<model>_mesh.inp` in a text editor.
   - [ ] Scroll to the bottom and verify both `*ELSET, ELSET=GAUGE_VOL` and `*NSET, NSET=GAUGE_VOL_NODES` exist, contain realistic element/node counts (not 0 and not 100% of the mesh), and have $\le 16$ integers per line with no trailing commas.
3. **Real CalculiX Execution Verification:**
   - [ ] Run **Run CCX** on that single specimen.
   - [ ] Inspect `04_Results_CCX/<model>.log` and confirm CalculiX exits with `returncode == 0` and **zero** `*ERROR` messages regarding `GAUGE_VOL` or `*EL FILE`.
   - [ ] Confirm `04_Results_CCX/<model>.frd` is generated and contains stress blocks (`STRESS`).