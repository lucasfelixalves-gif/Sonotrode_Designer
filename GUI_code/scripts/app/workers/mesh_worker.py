import os

from PySide6.QtCore import QThread, Signal

try:
    from scripts.meshing import mesh_step_to_inp
except ModuleNotFoundError:
    from meshing import mesh_step_to_inp


class MeshGenerationWorker(QThread):
    """Generate meshes for a selected set of model names."""

    progress_updated = Signal(int)
    status_updated = Signal(str)

    def __init__(self, project_dir, df_mesh, semantic_roles, target_models):
        super().__init__()
        self.project_dir = project_dir
        self.df_mesh = df_mesh
        self.semantic_roles = semantic_roles
        self.target_models = list(target_models or [])

    def _get_config_row(self, model_name):
        if self.df_mesh is None or "Model_name" not in self.df_mesh.columns:
            return {}

        names = self.df_mesh["Model_name"].astype(str).str.strip()
        exact_match = self.df_mesh[names == str(model_name).strip()]
        if not exact_match.empty:
            return exact_match.iloc[0].to_dict()

        fallback = self.df_mesh[names == "*"]
        if not fallback.empty:
            return fallback.iloc[0].to_dict()

        return {}

    def run(self):
        step_dir = os.path.join(self.project_dir, "02_Geometry_STEP")
        mesh_dir = os.path.join(self.project_dir, "03_Meshes_INP")
        os.makedirs(mesh_dir, exist_ok=True)

        selected = []
        for model_name in self.target_models:
            step_path = None
            for ext in (".step", ".STEP"):
                candidate = os.path.join(step_dir, f"{model_name}{ext}")
                if os.path.isfile(candidate):
                    step_path = candidate
                    break
            if step_path:
                selected.append((model_name, step_path))

        total = len(selected)
        if total == 0:
            self.status_updated.emit("MESH|WARN|No selected STEP files found in 02_Geometry_STEP")
            self.progress_updated.emit(0)
            return

        for index, (base_name, step_path) in enumerate(selected, start=1):
            try:
                mesh_cfg = self._get_config_row(base_name)
                mesh_inp_path = os.path.join(mesh_dir, f"{base_name}_mesh.inp")
                self.status_updated.emit(f"MESH|START|{base_name} ({index}/{total})")
                mesh_step_to_inp(
                    step_path=step_path,
                    mesh_output_path=mesh_inp_path,
                    mesh_config=mesh_cfg,
                    semantic_roles=self.semantic_roles,
                    quiet=True,
                )
                self.status_updated.emit(f"MESH|DONE|{base_name} ({index}/{total})")
            except Exception as exc:  # noqa: BLE001
                self.status_updated.emit(f"MESH|FAIL|{base_name}: {exc}")

            self.progress_updated.emit(int(index * 100 / total))

        self.status_updated.emit("MESH|COMPLETE|Selected mesh generation completed")
