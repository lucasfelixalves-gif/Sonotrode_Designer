import os
import time
from glob import glob

import pandas as pd
import pyvista as pv
from pyvistaqt import QtInteractor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QInputDialog, QListWidgetItem, QMessageBox, QVBoxLayout

from .base_controller import BaseController


MATERIAL_COLUMN_ALIASES = {
    "Density": "Density_kg_m^3",
    "Density_ton_m^3": "Density_kg_m^3",
    "Youngs_modulus": "Youngs_modulus_GPa",
}

try:
    from scripts.augment_master_workbook import create_master_workbook
    from scripts.meshing import generate_preview_mesh
    from scripts.app.widgets.tetris_popup import TetrisDialog
    from scripts.app.workers.solver_worker import SolverWorker
    from scripts.modal_inspection_service import clear_inspection_cache
except ModuleNotFoundError:
    from augment_master_workbook import create_master_workbook
    from meshing import generate_preview_mesh
    from app.widgets.tetris_popup import TetrisDialog
    from app.workers.solver_worker import SolverWorker
    from modal_inspection_service import clear_inspection_cache


class SetupController(BaseController):
    def _normalize_material_columns(self, df_material):
        if df_material is None or df_material.empty:
            return df_material

        renamed = {}
        for column in df_material.columns:
            normalized_name = MATERIAL_COLUMN_ALIASES.get(str(column).strip())
            if normalized_name:
                renamed[column] = normalized_name

        if not renamed:
            return df_material

        return df_material.rename(columns=renamed)

    def bind(self):
        self.tetris_window = None

        if hasattr(self.ui, "btn_new_project"):
            self.ui.btn_new_project.clicked.connect(self.create_new_project)
        if hasattr(self.ui, "btn_load"):
            self.ui.btn_load.clicked.connect(self.load_project)
        if hasattr(self.ui, "btn_run"):
            self.ui.btn_run.clicked.connect(self.start_batch_solve)
        if hasattr(self.ui, "btn_assign"):
            self.ui.btn_assign.clicked.connect(self.assign_role)
        if hasattr(self.ui, "btn_assign_amplitude"):
            self.ui.btn_assign_amplitude.clicked.connect(self.assign_input_amplitude)
        if hasattr(self.ui, "list_geometries"):
            self.ui.list_geometries.itemClicked.connect(self._on_geometry_selected)
        if hasattr(self.ui, "btn_abort_sim"):
            self.ui.btn_abort_sim.setEnabled(False)
            self.ui.btn_abort_sim.clicked.connect(self.abort_simulation)
        if hasattr(self.ui, "btn_tetris"):
            self.ui.btn_tetris.clicked.connect(self.open_tetris)

    def _ensure_plotters(self):
        if self.widgets.plotter is None and hasattr(self.ui, "frame_setup_3D"):
            layout = QVBoxLayout(self.ui.frame_setup_3D)
            layout.setContentsMargins(0, 0, 0, 0)
            try:
                self.widgets.plotter = QtInteractor(self.ui.frame_setup_3D)
                layout.addWidget(self.widgets.plotter)
            except Exception as exc:  # noqa: BLE001
                self.widgets.plotter = None
                print(f"[WARNING] Could not initialize setup 3D viewport: {exc}")

        if self.widgets.plotter_results is None and hasattr(self.ui, "frame_results_3d"):
            layout = QVBoxLayout(self.ui.frame_results_3d)
            layout.setContentsMargins(0, 0, 0, 0)
            try:
                self.widgets.plotter_results = QtInteractor(self.ui.frame_results_3d)
                layout.addWidget(self.widgets.plotter_results)
            except Exception as exc:  # noqa: BLE001
                self.widgets.plotter_results = None
                print(f"[WARNING] Could not initialize results 3D viewport: {exc}")

    def _ensure_project_folders(self):
        if not self.session.project_dir:
            return
        for folder in (
            "01_Master_Config",
            "02_Geometry_STEP",
            "03_Meshes_INP",
            "04_Results_CCX",
            "05_Reports",
        ):
            os.makedirs(os.path.join(self.session.project_dir, folder), exist_ok=True)

    def _find_single_master_workbook(self):
        if not self.session.project_dir:
            return None
        config_dir = os.path.join(self.session.project_dir, "01_Master_Config")
        xlsx_files = sorted(glob(os.path.join(config_dir, "*.xlsx")))
        if len(xlsx_files) == 1:
            return xlsx_files[0]
        return None

    def _populate_geometries_list(self, step_dir, load_first=True):
        step_files = sorted(
            glob(os.path.join(step_dir, "*.step"))
            + glob(os.path.join(step_dir, "*.STEP"))
        )
        step_files = list(dict.fromkeys(step_files))

        if not hasattr(self.ui, "list_geometries"):
            return

        self.ui.list_geometries.clear()
        for path in step_files:
            item = QListWidgetItem(os.path.basename(path))
            item.setData(Qt.UserRole, path)
            self.ui.list_geometries.addItem(item)

        if load_first and self.ui.list_geometries.count() > 0:
            self.ui.list_geometries.setCurrentRow(0)
            first_path = self.ui.list_geometries.item(0).data(Qt.UserRole)
            self.load_reference_model(first_path)

    def _load_project_workbook(self, file_path, load_first_geometry=True):
        workbook_dir = os.path.dirname(file_path)
        if os.path.basename(workbook_dir) == "01_Master_Config":
            self.session.project_dir = os.path.dirname(workbook_dir)
        else:
            self.session.project_dir = workbook_dir

        self.session.master_workbook_path = file_path
        if hasattr(self.ui, "line_path"):
            self.ui.line_path.setText(self.session.project_dir)
        self._ensure_project_folders()

        self.session.df_mesh = pd.read_excel(file_path, sheet_name="Meshing_Parameters")
        self.session.df_material = self._normalize_material_columns(
            pd.read_excel(file_path, sheet_name="Materials")
        )
        self.session.df_step = pd.read_excel(file_path, sheet_name="Step_Configuration")

        step_dir = os.path.join(self.session.project_dir, "02_Geometry_STEP")
        self._populate_geometries_list(step_dir, load_first=load_first_geometry)
        self.context.controllers["analytics"].initialize_job_table()

    def ensure_configuration_loaded(self):
        if self.session.df_mesh is not None and self.session.df_material is not None and self.session.df_step is not None:
            return True

        workbook = self.session.master_workbook_path
        if not workbook or not os.path.isfile(workbook):
            workbook = self._find_single_master_workbook()
        if not workbook:
            return False

        self._load_project_workbook(workbook, load_first_geometry=False)
        return True

    def create_new_project(self):
        base_dir = QFileDialog.getExistingDirectory(
            self.main_window, "Select Base Directory for New Project"
        )
        if not base_dir:
            return

        project_name, ok = QInputDialog.getText(
            self.main_window, "New Project", "Enter project name:"
        )
        if not ok or not project_name.strip():
            return
        project_name = project_name.strip()

        master_folder = os.path.join(base_dir, project_name)
        self.session.clear_project_data()
        for subfolder in (
            "01_Master_Config",
            "02_Geometry_STEP",
            "03_Meshes_INP",
            "04_Results_CCX",
            "05_Reports",
        ):
            os.makedirs(os.path.join(master_folder, subfolder), exist_ok=True)

        master_workbook_path = create_master_workbook(master_folder)

        self.session.project_dir = master_folder
        self.session.master_workbook_path = master_workbook_path
        if hasattr(self.ui, "line_path"):
            self.ui.line_path.setText(master_folder)
        self.context.controllers["analytics"].initialize_job_table()
        QMessageBox.information(
            self.main_window,
            "Project Created",
            f"Project '{project_name}' created.\n"
            f"Master workbook created at:\n{master_workbook_path}",
        )

    def load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.main_window,
            "Select Master Excel Workbook",
            "",
            "Excel Files (*.xlsx)",
        )
        if not file_path:
            return

        self._load_project_workbook(file_path, load_first_geometry=True)
        self.context.controllers["analytics"].load_analytics_data()

    def refresh_project_from_disk(self):
        if not self.session.project_dir:
            return False

        step_dir = os.path.join(self.session.project_dir, "02_Geometry_STEP")
        selected_path = None
        if hasattr(self.ui, "list_geometries") and self.ui.list_geometries.currentItem() is not None:
            selected_path = self.ui.list_geometries.currentItem().data(Qt.UserRole)

        self._populate_geometries_list(step_dir, load_first=False)

        if not hasattr(self.ui, "list_geometries"):
            return True

        target_name = os.path.basename(selected_path) if selected_path else None
        selected_index = -1
        if target_name:
            for index in range(self.ui.list_geometries.count()):
                item = self.ui.list_geometries.item(index)
                if item and item.text() == target_name:
                    selected_index = index
                    break

        if selected_index >= 0:
            self.ui.list_geometries.setCurrentRow(selected_index)
        elif self.ui.list_geometries.count() > 0:
            self.ui.list_geometries.setCurrentRow(0)
        else:
            if self.widgets.plotter is not None:
                self.widgets.plotter.clear()
            if hasattr(self.ui, "lbl_info"):
                self.ui.lbl_info.setText("No STEP geometries found in 02_Geometry_STEP.")
            return True

        current_item = self.ui.list_geometries.currentItem()
        if current_item is not None:
            current_step_path = current_item.data(Qt.UserRole)
            if current_step_path:
                self.load_reference_model(current_step_path)

        return True

    def start_batch_solve(self):
        clear_inspection_cache()

        if not self.session.project_dir:
            QMessageBox.warning(self.main_window, "No Project", "Load or create a project first.")
            return

        try:
            if not self.ensure_configuration_loaded():
                QMessageBox.warning(
                    self.main_window,
                    "Missing Configuration",
                    "Place exactly one workbook in 01_Master_Config and click Load.",
                )
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self.main_window,
                "Missing Configuration",
                f"Could not load workbook configuration automatically:\n{exc}",
            )
            return

        if hasattr(self.ui, "btn_run"):
            self.ui.btn_run.setEnabled(False)

        analytics = self.context.controllers["analytics"]
        analytics._set_progress_value(0)
        analytics._set_status_text("Starting batch solve...")
        self.widgets.sim_timer.stop()
        self.session.sim_start_time = time.time()
        analytics.update_sim_timer()
        self.widgets.sim_timer.start(1000)
        if hasattr(self.ui, "btn_abort_sim"):
            self.ui.btn_abort_sim.setEnabled(True)

        self.session.worker = SolverWorker(
            project_dir=self.session.project_dir,
            df_mesh=self.session.df_mesh,
            df_material=self.session.df_material,
            df_step=self.session.df_step,
            semantic_roles=self.session.semantic_roles,
            input_amplitude=self.session.input_amplitude,
        )
        self.session.worker.progress_updated.connect(analytics._set_progress_value)
        self.session.worker.status_updated.connect(analytics._set_status_text)
        self.session.worker.finished.connect(self._on_worker_finished)
        if hasattr(self.ui, "btn_tetris"):
            self.ui.btn_tetris.setEnabled(True)
        self.session.worker.start()

    def _on_worker_finished(self):
        self.widgets.sim_timer.stop()
        if hasattr(self.ui, "btn_abort_sim"):
            self.ui.btn_abort_sim.setEnabled(False)
        if hasattr(self.ui, "btn_run"):
            self.ui.btn_run.setEnabled(True)
        if hasattr(self.ui, "btn_tetris"):
            self.ui.btn_tetris.setEnabled(False)

        if hasattr(self, "tetris_window") and self.tetris_window is not None and self.tetris_window.isVisible():
            self.tetris_window.close()

        self.session.worker = None
        try:
            self.context.controllers["analytics"].load_analytics_data()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(
                self.main_window,
                "Analytics Update",
                f"Batch finished, but analytics refresh failed:\n{exc}",
            )

    def assign_input_amplitude(self):
        """Read and save the physical amplitude input from the spin box."""
        if not hasattr(self.ui, "spin_input_amplitude"):
            return
        
        amplitude_value = self.ui.spin_input_amplitude.value()
        self.session.input_amplitude = float(amplitude_value)
        QMessageBox.information(
            self.main_window,
            "Amplitude Scaling Set",
            f"Physical amplitude scaling set to {amplitude_value:.6g}",
        )

    def abort_simulation(self):
        if self.session.worker is None:
            return

        print("[SYSTEM] Simulation aborted by user.")
        self.session.worker.abort()
        self.context.controllers["analytics"].update_sim_timer()
        self.widgets.sim_timer.stop()
        if hasattr(self.ui, "btn_abort_sim"):
            self.ui.btn_abort_sim.setEnabled(False)

    def open_tetris(self):
        if self.tetris_window is None:
            self.tetris_window = TetrisDialog(self.ui)
        self.tetris_window.show()

    def _on_geometry_selected(self, item):
        step_path = item.data(Qt.UserRole)
        if step_path:
            self.load_reference_model(step_path)

    def _resolve_picked_dataset(self, picked_cell):
        picked = picked_cell
        if hasattr(picked_cell, "n_blocks"):
            picked = next((b for b in picked_cell if b is not None and b.n_cells > 0), None)
        return picked

    def _find_cad_id_array_name(self, dataset):
        if dataset is None or not hasattr(dataset, "cell_data"):
            return None

        candidates = (
            "gmsh:physical",
            "CellEntityIds",
            "gmsh:entity",
            "gmsh:geometrical",
            "PhysicalIds",
        )
        for name in candidates:
            if name in dataset.cell_data:
                return name

        for name in dataset.cell_data.keys():
            lowered = str(name).lower()
            if "physical" in lowered or "entity" in lowered or "gmsh" in lowered:
                return name
        return None

    def _extract_picked_cad_id(self, picked, cad_id_array):
        if picked is None or cad_id_array is None:
            return None

        if cad_id_array in picked.cell_data and len(picked.cell_data[cad_id_array]) > 0:
            return int(round(float(picked.cell_data[cad_id_array][0])))

        if (
            hasattr(self, "_preview_mesh")
            and self._preview_mesh is not None
            and cad_id_array in self._preview_mesh.cell_data
            and "vtkOriginalCellIds" in picked.cell_data
            and len(picked.cell_data["vtkOriginalCellIds"]) > 0
        ):
            original_cell_id = int(picked.cell_data["vtkOriginalCellIds"][0])
            if 0 <= original_cell_id < self._preview_mesh.n_cells:
                return int(round(float(self._preview_mesh.cell_data[cad_id_array][original_cell_id])))

        return None

    def load_reference_model(self, step_path):
        self._ensure_plotters()
        if self.widgets.plotter is None:
            if hasattr(self.ui, "lbl_info"):
                self.ui.lbl_info.setText("3D setup viewport unavailable (OpenGL init failed).")
            return

        try:
            self.widgets.plotter.disable_picking()
        except Exception:  # noqa: BLE001
            pass
        self.widgets.plotter.clear()

        vtk_path = os.path.join(self.session.project_dir, "temp_ref.vtk")
        generate_preview_mesh(step_path=step_path, vtk_output_path=vtk_path, quiet=False)

        mesh = pv.read(vtk_path)
        self._preview_mesh = mesh
        self._preview_cad_id_array_name = self._find_cad_id_array_name(mesh)

        if not self._preview_cad_id_array_name and hasattr(self.ui, "lbl_info"):
            self.ui.lbl_info.setText(
                "Preview loaded, but no Gmsh CAD ID cell-data array was found for concordant picking."
            )

        self.widgets.plotter.add_mesh(
            mesh,
            pickable=True,
            show_edges=True,
            edge_color="#808080",
            color="lightsteelblue",
            opacity=0.92,
            smooth_shading=True,
        )
        self.widgets.plotter.enable_element_picking(
            callback=self.on_cell_picked,
            mode="cell",
            left_clicking=True,
            show=False,
            show_message=False,
        )

    def on_cell_picked(self, cell):
        if cell is None:
            return

        picked = self._resolve_picked_dataset(cell)

        if picked is None or not hasattr(picked, "n_cells") or picked.n_cells == 0:
            return

        cad_id_array = getattr(self, "_preview_cad_id_array_name", None)
        if cad_id_array is None and hasattr(self, "_preview_mesh"):
            cad_id_array = self._find_cad_id_array_name(self._preview_mesh)
            self._preview_cad_id_array_name = cad_id_array
        if cad_id_array is None:
            return

        cad_surface_id = self._extract_picked_cad_id(picked, cad_id_array)
        if cad_surface_id is None:
            return

        selected = None
        if hasattr(self, "_preview_mesh") and self._preview_mesh is not None:
            selected = self._preview_mesh.threshold(
                value=(cad_surface_id - 0.5, cad_surface_id + 0.5),
                scalars=cad_id_array,
                preference="cell",
            )

        if selected is None or selected.n_cells == 0:
            return

        centroid = list(selected.center)

        normal = [0.0, 0.0, 0.0]
        try:
            surf = selected.extract_surface().compute_normals(
                cell_normals=True,
                point_normals=False,
                auto_orient_normals=False,
            )
            if surf.n_cells > 0 and "Normals" in surf.cell_data:
                normal = list(surf.cell_data["Normals"][0])
        except Exception:
            pass

        self.session.last_picked_info = {
            "centroid": centroid,
            "normal": normal,
            "cad_surface_id": cad_surface_id,
        }

        self.widgets.plotter.add_mesh(
            selected,
            name="picked_face",
            color="orangered",
            show_edges=True,
            edge_color="yellow",
            line_width=3,
            opacity=1.0,
            pickable=False,
            reset_camera=False,
        )

    def assign_role(self):
        if self.session.last_picked_info is None:
            QMessageBox.warning(
                self.main_window,
                "No Selection",
                "Pick a face on the 3-D model first.",
            )
            return

        centroid = self.session.last_picked_info["centroid"]
        role_name = self.ui.combo_roles.currentText() if hasattr(self.ui, "combo_roles") else "Role"
        self.session.semantic_roles[role_name] = self.session.last_picked_info.copy()

        if hasattr(self.ui, "list_roles"):
            self.ui.list_roles.addItem(
                f"{role_name} mapped to "
                f"[{centroid[0]:.3f}, {centroid[1]:.3f}, {centroid[2]:.3f}]"
            )
