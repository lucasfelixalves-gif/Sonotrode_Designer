"""CalculiX service for GUI-driven CAE workflow.

Canonical responsibility of this module:
- Build one final CCX deck from one mesh INP and config dictionaries
- Execute one CCX job
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal

try:
    from scripts.ccx_results_parser import (
        parse_dat_modal_results,
        parse_mesh_node_sets,
        select_longitudinal_mode,
    )
except ModuleNotFoundError:
    from ccx_results_parser import (  # type: ignore
        parse_dat_modal_results,
        parse_mesh_node_sets,
        select_longitudinal_mode,
    )


_ACTIVE_CCX_JOB = None


def _read_log_tail(log_path, max_chars=4000):
    if not os.path.isfile(log_path):
        return ""
    with open(log_path, "r", encoding="utf-8", errors="ignore") as src:
        text = src.read()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value, default):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_csv(raw):
    out = []
    for tok in str(raw or "").replace(";", ",").split(","):
        t = tok.strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def _parse_dofs(raw):
    out = []
    for tok in str(raw or "").split(","):
        try:
            v = int(tok.strip())
        except ValueError:
            continue
        if 1 <= v <= 6 and v not in out:
            out.append(v)
    return out


def _coalesce(config, *keys, default=None):
    for key in keys:
        if key in config and config.get(key) not in (None, ""):
            return config.get(key)
    return default


def _resolve_ccx_executable(ccx_executable):
    explicit = str(ccx_executable or "").strip()
    if explicit and explicit not in {"ccx", "ccx.exe"}:
        return explicit

    for name in (explicit, "ccx", "ccx.exe"):
        if not name:
            continue
        found = shutil.which(name)
        if found:
            return found

    env_root = os.path.dirname(sys.executable)
    probe_dirs = (
        os.path.join(env_root, "Library", "bin"),
        os.path.join(env_root, "Scripts"),
        os.path.join(env_root, "bin"),
    )
    for directory in probe_dirs:
        for name in ("ccx.exe", "ccx"):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate

    repo_root = Path(__file__).resolve().parents[2]
    bin_dir = repo_root / "bin"
    for name in ("ccx.exe", "ccx"):
        candidate = bin_dir / name
        if candidate.is_file():
            return str(candidate)

    raise RuntimeError("CCX executable not found in PATH or active environment.")


def _normalize_mesh_for_ccx(mesh_inp_path):
    """Load mesh INP and return CCX-friendly lines with ELSET=Volume1 guaranteed."""
    with open(mesh_inp_path, "r", encoding="utf-8", errors="ignore") as src:
        raw_lines = src.readlines()

    out_lines = []
    element_ids = []
    in_node_block = False
    in_element_block = False
    has_volume1_elset = False

    for raw in raw_lines:
        line = raw.rstrip("\n")
        stripped = line.strip()
        upper = stripped.upper()

        if stripped.startswith("*"):
            in_node_block = upper.startswith("*NODE")
            in_element_block = upper.startswith("*ELEMENT")
            if upper.startswith("*ELSET") and "ELSET=VOLUME1" in upper:
                has_volume1_elset = True
            out_lines.append(line)
            continue

        if in_node_block and stripped:
            parts = [p.strip() for p in stripped.split(",")]
            if len(parts) >= 4:
                try:
                    nid = int(parts[0])
                    x = float(parts[1])
                    y = float(parts[2])
                    z = float(parts[3])
                    out_lines.append(f"{nid}, {x:.16f}, {y:.16f}, {z:.16f}")
                    continue
                except ValueError:
                    pass

        if in_element_block and stripped and not stripped.startswith("**"):
            token = stripped.split(",", 1)[0].strip()
            try:
                element_ids.append(int(token))
            except ValueError:
                pass

        out_lines.append(line)

    if element_ids and not has_volume1_elset:
        out_lines.append("*ELSET, ELSET=Volume1")
        chunk = []
        for eid in element_ids:
            chunk.append(str(eid))
            if len(chunk) == 16:
                out_lines.append(", ".join(chunk))
                chunk = []
        if chunk:
            out_lines.append(", ".join(chunk))

    return "\n".join(out_lines).rstrip()


def _extract_nset_names(mesh_content):
    names = set()
    for line in mesh_content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("*"):
            continue
        upper = stripped.upper()
        if not upper.startswith("*NSET"):
            continue
        match = re.search(r"\bNSET\s*=\s*([^,\s]+)", upper)
        if match:
            names.add(match.group(1).strip().upper())
    return names


def _append_bbox_nsets_if_missing(mesh_content, required_names):
    """Append Y-extrema NSETs when required sets are missing from the mesh deck."""
    required = [name.strip().upper() for name in required_names if str(name).strip()]
    if not required:
        return mesh_content

    existing = _extract_nset_names(mesh_content)
    missing = [name for name in required if name not in existing]
    if not missing:
        return mesh_content

    node_coords = {}
    in_node_block = False
    for raw in mesh_content.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("*"):
            in_node_block = line.upper().startswith("*NODE")
            continue
        if not in_node_block:
            continue

        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            nid = int(parts[0])
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])
        except ValueError:
            continue
        node_coords[nid] = (x, y, z)

    if not node_coords:
        return mesh_content

    y_values = [coord[1] for coord in node_coords.values()]
    y_min = min(y_values)
    y_max = max(y_values)
    span = max(y_max - y_min, 1.0)
    tol = max(1e-8, 1e-4 * span)

    lines = [mesh_content.rstrip(), ""]
    for name in missing:
        if name == "YMIN":
            ids = sorted(nid for nid, (_, y, _) in node_coords.items() if abs(y - y_min) <= tol)
        elif name == "YMAX":
            ids = sorted(nid for nid, (_, y, _) in node_coords.items() if abs(y - y_max) <= tol)
        else:
            continue

        if not ids:
            continue

        lines.append(f"*NSET, NSET={name}")
        chunk = []
        for nid in ids:
            chunk.append(str(nid))
            if len(chunk) == 16:
                lines.append(", ".join(chunk))
                chunk = []
        if chunk:
            lines.append(", ".join(chunk))

    return "\n".join(lines).rstrip()


def build_frequency_deck(
    *,
    mesh_inp_path,
    deck_output_path,
    material_config,
    step_config,
):
    """Create a final frequency deck by appending physics cards to mesh content."""
    material_config = material_config or {}
    step_config = step_config or {}

    mesh_content = _normalize_mesh_for_ccx(mesh_inp_path)

    # Accept both legacy and unit-suffixed workbook headers.
    density = _as_float(
        _coalesce(material_config, "Density_kg_m^3", "Density_ton_m^3", "Density", default=0.0),
        0.0,
    )
    young = _as_float(
        _coalesce(material_config, "Youngs_modulus_GPa", "Youngs_modulus", default=0.0),
        0.0,
    )
    poisson = _as_float(
        _coalesce(material_config, "Poissons_ratio", "Poisson_ratio", default=0.3),
        0.3,
    )

    step_type = str(
        _coalesce(step_config, "Step_type", "step_type", default="frequency")
    ).strip().lower()
    if step_type != "frequency":
        raise ValueError("Only Step_type='frequency' is supported in GUI solver.")

    if young <= 0.0 or density <= 0.0:
        raise ValueError(
            "Material values must be positive (Youngs_modulus[_GPa], Density[_kg_m^3])."
        )

    # Workbook conventions: E in GPa, density in kg/m^3.
    # CCX deck in this workflow uses N-mm-tonne units.
    youngs_mpa = young * 1e3
    density_tonne_per_mm3 = density * 1e-12

    number_of_frequencies = _as_int(
        _coalesce(step_config, "Number_of_frequencies", "number_of_frequencies", default=10),
        10,
    )
    lower_freq = _as_float(
        _coalesce(step_config, "Lower_frequency_hz", "lower_frequency_hz", default=0.0),
        0.0,
    )
    upper_freq = _as_float(
        _coalesce(step_config, "Upper_frequency_hz", "upper_frequency_hz", default=0.0),
        0.0,
    )

    constrained_nset = str(
        _coalesce(step_config, "Constrained_nset", "constrained_nset", default="")
    ).strip().upper()
    constrained_dofs = _parse_dofs(
        _coalesce(step_config, "Constrained_dofs", "constrained_dofs", default="")
    )

    output_nsets = _parse_csv(
        _coalesce(step_config, "Output_nsets", "output_nsets", default="YMIN,YMAX")
    ) or ["YMIN", "YMAX"]
    output_vars = _parse_csv(
        _coalesce(step_config, "Output_variables", "output_variables", default="U")
    ) or ["U"]

    # Ensure required result NSETs exist so NODE PRINT does not fail.
    mesh_content = _append_bbox_nsets_if_missing(mesh_content, output_nsets)

    if lower_freq > 0.0 or upper_freq > 0.0:
        frequency_line = f"{number_of_frequencies}, {lower_freq}, {upper_freq}"
    else:
        frequency_line = f"{number_of_frequencies}"

    lines = [
        mesh_content,
        "",
        "*MATERIAL, NAME=MAT1",
        "*DENSITY",
        f"{density_tonne_per_mm3:.8E}",
        "*ELASTIC",
        f"{youngs_mpa:.8G}, {poisson:.8G}",
        "*SOLID SECTION, ELSET=Volume1, MATERIAL=MAT1",
        "",
        "*STEP, PERTURBATION",
        "*FREQUENCY, SOLVER=PARDISO",
        frequency_line,
    ]

    if constrained_nset and constrained_dofs:
        lines.append("*BOUNDARY")
        for dof in constrained_dofs:
            lines.append(f"{constrained_nset}, {dof}, {dof}")

    lines.append("*NODE FILE")
    lines.append(",".join(output_vars))

    if output_nsets:
        for nset in output_nsets:
            lines.append(f"*NODE PRINT, NSET={nset}")
            lines.append(",".join(output_vars))

    lines.extend(["*END STEP", ""])

    os.makedirs(os.path.dirname(deck_output_path), exist_ok=True)
    with open(deck_output_path, "w", encoding="utf-8") as dst:
        dst.write("\n".join(lines))

    return deck_output_path


def run_ccx_job(*, base_name, results_dir, ccx_executable="ccx", cpu_count=0):
    """Execute one CCX solve in results_dir and return CompletedProcess."""
    global _ACTIVE_CCX_JOB
    job = CCXJobRunner(
        base_name=base_name,
        results_dir=results_dir,
        ccx_executable=ccx_executable,
        cpu_count=cpu_count,
    )
    _ACTIVE_CCX_JOB = job
    try:
        return job.run()
    finally:
        _ACTIVE_CCX_JOB = None


class CCXJobRunner:
    def __init__(self, *, base_name, results_dir, ccx_executable="ccx", cpu_count=0):
        self.base_name = base_name
        self.results_dir = results_dir
        self.ccx_executable = ccx_executable
        self.cpu_count = cpu_count
        self._process = None

    def run(self):
        executable = _resolve_ccx_executable(self.ccx_executable)
        env = os.environ.copy()
        if self.cpu_count and int(self.cpu_count) > 0:
            env["OMP_NUM_THREADS"] = str(int(self.cpu_count))

        command = [executable, "-i", self.base_name]
        log_path = os.path.join(self.results_dir, f"{self.base_name}.log")
        try:
            with open(log_path, "w", encoding="utf-8", errors="ignore") as log_file:
                self._process = subprocess.Popen(
                    command,
                    cwd=self.results_dir,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                returncode = self._process.wait()
            log_tail = _read_log_tail(log_path)
            return subprocess.CompletedProcess(
                args=command,
                returncode=returncode,
                stdout=log_tail,
                stderr="",
            )
        finally:
            self._process = None

    def abort(self):
        process = self._process
        if process is None:
            return False
        if process.poll() is not None:
            return False

        process.kill()
        return True


class CCXSolverWorker(QThread):
    """Run CCX only for selected models from the analytics table."""

    progress_updated = Signal(int)
    status_updated = Signal(str)

    def __init__(
        self,
        *,
        project_dir,
        df_mesh=None,
        df_material,
        df_step,
        target_models,
        ccx_executable="ccx",
        cpu_count=0,
        input_amplitude=1.0,
    ):
        super().__init__()
        self.project_dir = project_dir
        self.df_mesh = df_mesh
        self.df_material = df_material
        self.df_step = df_step
        self.target_models = list(target_models or [])
        self.ccx_executable = ccx_executable
        self.cpu_count = cpu_count
        self.input_amplitude = input_amplitude
        self._abort_requested = False
        self._process = None

    def _get_config_row(self, df, model_name):
        if df is None or "Model_name" not in df.columns:
            return {}

        names = df["Model_name"].astype(str).str.strip()
        exact_match = df[names == str(model_name).strip()]
        if not exact_match.empty:
            return exact_match.iloc[0].to_dict()

        fallback = df[names == "*"]
        if not fallback.empty:
            return fallback.iloc[0].to_dict()

        return {}

    def abort(self):
        self._abort_requested = True
        process = self._process
        if process is None:
            return False
        if process.poll() is not None:
            return False

        process.kill()
        return True

    def _run_one_model(self, base_name, mesh_inp_path, results_dir, material_cfg, step_cfg, mesh_cfg):
        final_deck_path = os.path.join(results_dir, f"{base_name}.inp")
        build_frequency_deck(
            mesh_inp_path=mesh_inp_path,
            deck_output_path=final_deck_path,
            material_config=material_cfg,
            step_config=step_cfg,
        )

        executable = _resolve_ccx_executable(self.ccx_executable)
        env = os.environ.copy()
        job_cpu_count = _as_int(self.cpu_count, 0)
        if job_cpu_count <= 0:
            job_cpu_count = _as_int(
                _coalesce(step_cfg, "Num_threads", "num_threads", "Num_cpus", "num_cpus", default=0),
                0,
            )
        if job_cpu_count <= 0 and isinstance(mesh_cfg, dict):
            job_cpu_count = _as_int(
                _coalesce(mesh_cfg, "Num_threads", "num_threads", "Num_cpus", "num_cpus", default=0),
                0,
            )
        if job_cpu_count > 0:
            env["OMP_NUM_THREADS"] = str(job_cpu_count)

        command = [executable, "-i", base_name]
        log_path = os.path.join(results_dir, f"{base_name}.log")
        try:
            with open(log_path, "w", encoding="utf-8", errors="ignore") as log_file:
                self._process = subprocess.Popen(
                    command,
                    cwd=results_dir,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )
                returncode = self._process.wait()
        finally:
            self._process = None

        return {
            "returncode": returncode,
            "stdout": "",
            "stderr": "",
            "log_path": log_path,
            "log_tail": _read_log_tail(log_path),
        }

    def run(self):
        mesh_dir = os.path.join(self.project_dir, "03_Meshes_INP")
        results_dir = os.path.join(self.project_dir, "04_Results_CCX")
        os.makedirs(results_dir, exist_ok=True)

        selected = []
        for model_name in self.target_models:
            primary_mesh = os.path.join(mesh_dir, f"{model_name}_mesh.inp")
            fallback_mesh = os.path.join(mesh_dir, f"{model_name}_mesh_fallback_o1.inp")
            if os.path.isfile(primary_mesh):
                selected.append((model_name, primary_mesh))
            elif os.path.isfile(fallback_mesh):
                selected.append((model_name, fallback_mesh))

        total = len(selected)
        if total == 0:
            self.status_updated.emit("SOLVE|WARN|No selected mesh files found in 03_Meshes_INP")
            self.progress_updated.emit(0)
            return

        for index, (base_name, mesh_inp_path) in enumerate(selected, start=1):
            if self._abort_requested:
                break

            try:
                mesh_cfg = self._get_config_row(self.df_mesh, base_name)
                material_cfg = self._get_config_row(self.df_material, base_name)
                step_cfg = self._get_config_row(self.df_step, base_name)

                try:
                    _, node_count = parse_mesh_node_sets(mesh_inp_path)
                except Exception:  # noqa: BLE001
                    node_count = 0

                self.status_updated.emit(
                    f"SOLVE | Starting {base_name} ({node_count:,} nodes) [{index}/{total}]"
                )
                solve_result = self._run_one_model(
                    base_name,
                    mesh_inp_path,
                    results_dir,
                    material_cfg,
                    step_cfg,
                    mesh_cfg,
                )

                if self._abort_requested:
                    self.status_updated.emit(f"SOLVE|ABORT|Aborted during {base_name}")
                    break

                if solve_result["returncode"] == 0:
                    self.status_updated.emit(f"SOLVE|DONE|{base_name} ({index}/{total})")
                    dat_path = os.path.join(results_dir, f"{base_name}.dat")
                    if os.path.isfile(dat_path):
                        try:
                            node_sets, _ = parse_mesh_node_sets(mesh_inp_path)
                            mode_frequencies, mode_displacements = parse_dat_modal_results(
                                dat_path,
                                node_sets,
                            )
                            metrics = select_longitudinal_mode(
                                mode_displacements,
                                input_amplitude=self.input_amplitude,
                            )
                            if metrics is not None:
                                self.status_updated.emit(
                                    f"SOLVE|METRICS|{base_name}: metrics extracted for table refresh"
                                )
                            else:
                                self.status_updated.emit(
                                    f"SOLVE|METRICS|{base_name}: no modal metrics extracted"
                                )
                        except Exception as parse_exc:  # noqa: BLE001
                            self.status_updated.emit(
                                f"SOLVE|METRICS|{base_name}: metrics parse failed: {parse_exc}"
                            )
                    else:
                        self.status_updated.emit(
                            f"SOLVE|METRICS|{base_name}: .dat not found for metrics parsing"
                        )
                else:
                    err = (
                        solve_result.get("log_tail")
                        or solve_result.get("stderr")
                        or solve_result.get("stdout")
                        or "Unknown ccx error"
                    ).strip()
                    self.status_updated.emit(f"SOLVE|FAIL|{base_name}: {err}")
            except Exception as exc:  # noqa: BLE001
                self.status_updated.emit(f"SOLVE|ERROR|{base_name}: {exc}")

            self.progress_updated.emit(int(index * 100 / total))

        if self._abort_requested:
            self.status_updated.emit("SOLVE|ABORT|Selected CCX run aborted")
        else:
            self.status_updated.emit("SOLVE|COMPLETE|Selected CCX run completed")


def abort_active_ccx_job():
    job = _ACTIVE_CCX_JOB
    if job is None:
        return False
    return job.abort()


def solve_frequency_case(
    *,
    mesh_inp_path,
    results_dir,
    material_config,
    step_config,
    ccx_executable="ccx",
    mesh_config=None,
    cpu_count=None,
):
    """Build a deck from one mesh and run one frequency solve."""
    base_name = os.path.splitext(os.path.basename(mesh_inp_path))[0]
    if base_name.endswith("_mesh"):
        base_name = base_name[:-5]

    final_deck_path = os.path.join(results_dir, f"{base_name}.inp")
    build_frequency_deck(
        mesh_inp_path=mesh_inp_path,
        deck_output_path=final_deck_path,
        material_config=material_config,
        step_config=step_config,
    )

    if cpu_count is None:
        cpu_count = _as_int(
            _coalesce(step_config, "Num_threads", "num_threads", "Num_cpus", "num_cpus", default=0),
            0,
        )
    if (not cpu_count or int(cpu_count) <= 0) and isinstance(mesh_config, dict):
        cpu_count = _as_int(
            _coalesce(mesh_config, "Num_threads", "num_threads", "Num_cpus", "num_cpus", default=0),
            0,
        )

    result = run_ccx_job(
        base_name=base_name,
        results_dir=results_dir,
        ccx_executable=ccx_executable,
        cpu_count=cpu_count,
    )

    log_path = os.path.join(results_dir, f"{base_name}.log")
    log_text = "\n".join(
        segment.strip() for segment in (result.stdout, result.stderr) if segment and segment.strip()
    )
    if log_text:
        with open(log_path, "w", encoding="utf-8") as log_file:
            log_file.write(log_text + "\n")

    return {
        "base_name": base_name,
        "deck_path": final_deck_path,
        "log_path": log_path,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
