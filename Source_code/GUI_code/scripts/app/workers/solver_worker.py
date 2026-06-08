import os
from glob import glob
from pathlib import Path

from PySide6.QtCore import QThread, Signal

try:
    from scripts.ccx_solver import abort_active_ccx_job, solve_frequency_case
    from scripts.ccx_results_parser import (
        parse_dat_modal_results,
        parse_mesh_node_sets,
        select_longitudinal_mode,
    )
    from scripts.meshing import mesh_step_to_inp
except ModuleNotFoundError:
    from ccx_solver import abort_active_ccx_job, solve_frequency_case
    from ccx_results_parser import (
        parse_dat_modal_results,
        parse_mesh_node_sets,
        select_longitudinal_mode,
    )
    from meshing import mesh_step_to_inp


class SolverWorker(QThread):
    """Background worker that orchestrates meshing and CCX services."""

    progress_updated = Signal(int)
    status_updated = Signal(str)

    def __init__(
        self,
        project_dir,
        df_mesh,
        df_material,
        df_step,
        semantic_roles,
        input_amplitude=1.0,
    ):
        super().__init__()
        self.project_dir = project_dir
        self.df_mesh = df_mesh
        self.df_material = df_material
        self.df_step = df_step
        self.semantic_roles = semantic_roles
        self.input_amplitude = input_amplitude
        self._abort_requested = False

    def abort(self):
        self._abort_requested = True
        abort_active_ccx_job()

    def _get_config_row(self, df, model_name):
        """Return exact model row; fall back to '*' row when needed."""
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

    def run(self):
        step_dir = os.path.join(self.project_dir, "02_Geometry_STEP")
        mesh_dir = os.path.join(self.project_dir, "03_Meshes_INP")
        results_dir = os.path.join(self.project_dir, "04_Results_CCX")
        os.makedirs(mesh_dir, exist_ok=True)
        os.makedirs(results_dir, exist_ok=True)

        step_files = sorted(
            glob(os.path.join(step_dir, "*.step"))
            + glob(os.path.join(step_dir, "*.STEP"))
        )
        step_files = list(dict.fromkeys(step_files))

        total = len(step_files)
        if total == 0:
            self.status_updated.emit("No STEP files found in 02_Geometry_STEP.")
            self.progress_updated.emit(0)
            return

        for index, step_path in enumerate(step_files, start=1):
            if self._abort_requested:
                break

            base_name = Path(step_path).stem
            self.status_updated.emit(f"Preparing {base_name} ({index}/{total})")

            try:
                mesh_cfg = self._get_config_row(self.df_mesh, base_name)
                material_cfg = self._get_config_row(self.df_material, base_name)
                step_cfg = self._get_config_row(self.df_step, base_name)

                mesh_inp_path = os.path.join(mesh_dir, f"{base_name}_mesh.inp")
                solved_mesh_inp_path = mesh_inp_path
                self.status_updated.emit(f"Meshing {base_name} ({index}/{total})")
                mesh_step_to_inp(
                    step_path=step_path,
                    mesh_output_path=mesh_inp_path,
                    mesh_config=mesh_cfg,
                    semantic_roles=self.semantic_roles,
                    quiet=True,
                )
                if self._abort_requested:
                    break
                self.status_updated.emit(
                    f"MESH | Generated primary mesh -> {os.path.basename(mesh_inp_path)} "
                    f"(requested Element_order={mesh_cfg.get('Element_order', 2) if isinstance(mesh_cfg, dict) else 2})"
                )

                try:
                    _, node_count = parse_mesh_node_sets(mesh_inp_path)
                except Exception:  # noqa: BLE001
                    node_count = 0

                self.status_updated.emit(
                    f"SOLVE | Starting {base_name} ({node_count:,} nodes) [{index}/{total}]"
                )
                solve_result = solve_frequency_case(
                    mesh_inp_path=mesh_inp_path,
                    results_dir=results_dir,
                    material_config=material_cfg,
                    step_config=step_cfg,
                    mesh_config=mesh_cfg,
                    ccx_executable="ccx",
                )

                if self._abort_requested:
                    self.status_updated.emit(f"Batch aborted during {base_name}.")
                    break

                if solve_result["returncode"] != 0:
                    err_text = (
                        (solve_result.get("stderr") or "")
                        + "\n"
                        + (solve_result.get("stdout") or "")
                    ).lower()
                    if "nonpositive jacobian" in err_text:
                        self.status_updated.emit(
                            f"WARNING | {base_name}: Non-positive Jacobian detected. Generating 1st-order fallback mesh..."
                        )
                        retry_mesh_cfg = dict(mesh_cfg or {})
                        retry_mesh_cfg["Element_order"] = 1
                        retry_mesh_inp_path = os.path.join(
                            mesh_dir,
                            f"{base_name}_mesh_fallback_o1.inp",
                        )
                        mesh_step_to_inp(
                            step_path=step_path,
                            mesh_output_path=retry_mesh_inp_path,
                            mesh_config=retry_mesh_cfg,
                            semantic_roles=self.semantic_roles,
                            quiet=True,
                        )
                        solved_mesh_inp_path = retry_mesh_inp_path
                        self.status_updated.emit(
                            f"MESH | Generated fallback mesh -> {os.path.basename(retry_mesh_inp_path)} (Element_order=1)"
                        )
                        self.status_updated.emit(
                            f"SOLVE | Restarting {base_name} with fallback mesh..."
                        )
                        solve_result = solve_frequency_case(
                            mesh_inp_path=solved_mesh_inp_path,
                            results_dir=results_dir,
                            material_config=material_cfg,
                            step_config=step_cfg,
                            mesh_config=retry_mesh_cfg,
                            ccx_executable="ccx",
                        )

                if solved_mesh_inp_path == mesh_inp_path:
                    self.status_updated.emit(
                        "MESH | Solving with primary mesh (no fallback used)."
                    )
                else:
                    self.status_updated.emit(
                        f"MESH | Solving with fallback mesh -> {os.path.basename(solved_mesh_inp_path)}"
                    )

                if solve_result["returncode"] == 0:
                    dat_path = os.path.join(results_dir, f"{base_name}.dat")
                    if os.path.isfile(dat_path):
                        try:
                            node_sets, node_count = parse_mesh_node_sets(solved_mesh_inp_path)
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
                                    f"Solved {base_name} ({index}/{total}) | Metrics extracted for table refresh"
                                )
                            else:
                                self.status_updated.emit(
                                    f"Solved {base_name} ({index}/{total}) | No modal metrics extracted"
                                )
                        except Exception as parse_exc:  # noqa: BLE001
                            self.status_updated.emit(
                                f"Solved {base_name} ({index}/{total}) | Summary parse failed: {parse_exc}"
                            )
                    else:
                        self.status_updated.emit(
                            f"Solved {base_name} ({index}/{total}) | .dat not found for metrics parsing"
                        )
                else:
                    err = (
                        solve_result["stderr"]
                        or solve_result["stdout"]
                        or "Unknown ccx error"
                    ).strip()
                    self.status_updated.emit(f"ccx failed for {base_name}: {err}")
            except Exception as exc:  # noqa: BLE001
                self.status_updated.emit(f"Error in {base_name}: {exc}")

            self.progress_updated.emit(int(index * 100 / total))

        if self._abort_requested:
            self.status_updated.emit("Batch solve aborted.")
        else:
            self.status_updated.emit("Batch solve completed.")
