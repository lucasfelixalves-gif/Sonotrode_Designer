import math

import numpy as np
import pyvista as pv
from matplotlib.colors import ListedColormap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QVBoxLayout
from pyvistaqt import QtInteractor

from .base_controller import BaseController

try:
    from scripts.modal_inspection_service import (
        get_available_modes_and_frequencies,
        load_base_mesh_preview,
        load_base_result_mesh,
        warp_result_mesh,
    )
    from scripts.app.widgets.stress_plot_popup import StressPlotPopup
except ModuleNotFoundError:
    from modal_inspection_service import (
        get_available_modes_and_frequencies,
        load_base_mesh_preview,
        load_base_result_mesh,
        warp_result_mesh,
    )
    from app.widgets.stress_plot_popup import StressPlotPopup


class ResultsController(BaseController):
    """Controller for Tab 3: 3D results and animations."""

    def bind(self):
        self._path_points = []
        self._stress_popups = []

        if hasattr(self.ui, "table_results"):
            self.ui.table_results.clicked.connect(self.on_table_row_selected)

        button = self._get_render_button()
        if button is not None:
            button.clicked.connect(self.render_3d_result)
            button.setEnabled(False)

        if hasattr(self.ui, "slider_warp"):
            self.ui.slider_warp.setRange(-99, 99)
            self.ui.slider_warp.valueChanged.connect(self.update_warped_mesh)

        if hasattr(self.ui, "btn_prev_mode"):
            self.ui.btn_prev_mode.clicked.connect(self.load_prev_mode)
            self.ui.btn_prev_mode.setEnabled(False)
        if hasattr(self.ui, "btn_next_mode"):
            self.ui.btn_next_mode.clicked.connect(self.load_next_mode)
            self.ui.btn_next_mode.setEnabled(False)

        if hasattr(self.ui, "btn_animation"):
            self.ui.btn_animation.clicked.connect(self.toggle_animation)
        if hasattr(self.ui, "combo_active_scalar"):
            self.ui.combo_active_scalar.currentTextChanged.connect(self.update_warped_mesh)

        if hasattr(self.ui, "label_mode_data"):
            self.ui.label_mode_data.setText("Mode nº: -- | Frequency: -- Hz")

    def _get_render_button(self):
        if hasattr(self.ui, "btn_render_3D"):
            return self.ui.btn_render_3D
        if hasattr(self.ui, "btn_load_3d"):
            return self.ui.btn_load_3d
        return None

    def _get_results_tab_widget(self):
        if hasattr(self.ui, "tabWidget"):
            return self.ui.tabWidget
        if hasattr(self.ui, "TAB"):
            return self.ui.TAB
        return None

    def _ensure_results_plotter(self):
        if hasattr(self.ui, "frame_results_3d") and self.widgets.plotter_results is None:
            results_layout = QVBoxLayout(self.ui.frame_results_3d)
            results_layout.setContentsMargins(0, 0, 0, 0)
            try:
                self.widgets.plotter_results = QtInteractor(self.ui.frame_results_3d)
                results_layout.addWidget(self.widgets.plotter_results)
                self.widgets.plotter_results.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu
                )
                self.widgets.plotter_results.customContextMenuRequested.connect(
                    self._show_results_context_menu
                )
            except Exception as exc:  # noqa: BLE001
                self.widgets.plotter_results = None
                print(f"[WARNING] Could not initialize results 3D viewport: {exc}")

    def _get_sorted_mode_indices(self):
        return sorted(self.session.available_modes_dict.keys()) if self.session.available_modes_dict else []

    def _set_mode_navigation_state(self):
        sorted_modes = self._get_sorted_mode_indices()
        if not sorted_modes or self.session.current_mode_index not in sorted_modes:
            has_prev = False
            has_next = False
        else:
            current_pos = sorted_modes.index(self.session.current_mode_index)
            has_prev = current_pos > 0
            has_next = current_pos < (len(sorted_modes) - 1)

        if hasattr(self.ui, "btn_prev_mode"):
            self.ui.btn_prev_mode.setEnabled(has_prev)
        if hasattr(self.ui, "btn_next_mode"):
            self.ui.btn_next_mode.setEnabled(has_next)

    def _set_mode_label(self):
        if not hasattr(self.ui, "label_mode_data"):
            return

        frequency = self.session.available_modes_dict.get(self.session.current_mode_index)
        if frequency is None:
            self.ui.label_mode_data.setText(f"Mode nº: {self.session.current_mode_index} | Frequency: -- Hz")
        else:
            self.ui.label_mode_data.setText(
                f"Mode nº: {self.session.current_mode_index} | Frequency: {frequency:.1f} Hz"
            )

    def _ensure_mode_cache(self, model_name):
        if self.session.current_model_name != model_name or not self.session.available_modes_dict:
            self.session.available_modes_dict = get_available_modes_and_frequencies(
                self.session.project_dir,
                model_name,
            )

    def on_table_row_selected(self, index):
        # AGGRESSIVE TIMER STOP: Prevent animation from firing during mode switch
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        if self.session.job_table_df is None or self.session.job_table_df.empty:
            return
        if not index.isValid():
            return
        row = index.row()
        if row < 0 or row >= len(self.session.job_table_df):
            return
        if "Model_name" not in self.session.job_table_df.columns:
            return

        row_data = self.session.job_table_df.iloc[row]
        model_name = str(row_data.get("Model_name", "")).strip()
        mode_value = row_data.get("Mode_Index", "--")
        status_value = str(row_data.get("Status", "")).strip().lower()
        if not model_name or status_value not in {"meshed", "solved"}:
            return

        mode_index = None
        if status_value == "solved":
            try:
                mode_index = int(float(mode_value))
            except (TypeError, ValueError):
                return

        self.session.selected_result_row = {
            "Model_name": model_name,
            "Mode_Index": mode_index,
            "Status": status_value,
        }
        render_button = self._get_render_button()
        if render_button is not None:
            render_button.setEnabled(True)
        if hasattr(self.ui, "lbl_info"):
            if status_value == "solved":
                self.ui.lbl_info.setText(f"Ready to load: {model_name} (Mode {mode_index})")
            else:
                self.ui.lbl_info.setText(f"Ready to load: {model_name} (Meshed preview)")

    def render_3d_result(self):
        # AGGRESSIVE TIMER STOP: Prevent animation from interfering with initial render
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        self.context.controllers["setup"]._ensure_plotters()
        self._ensure_results_plotter()

        if not self.session.selected_result_row:
            QMessageBox.warning(self.main_window, "No Result Selected", "Select a row in the results table first.")
            return

        render_button = self._get_render_button()
        if render_button is None or not hasattr(self.ui, "slider_warp"):
            QMessageBox.warning(
                self.main_window,
                "UI Incomplete",
                "Phase 5 controls are not present in the loaded .ui file (btn_render_3D/slider_warp).",
            )
            return

        render_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tab_widget = self._get_results_tab_widget()
            if tab_widget is not None:
                tab_widget.setCurrentIndex(2)

            model_name = self.session.selected_result_row["Model_name"]
            status_value = str(self.session.selected_result_row.get("Status", "")).strip().lower()
            if status_value == "meshed":
                self._trigger_mesh_preview(model_name)
            else:
                mode_index = self.session.selected_result_row["Mode_Index"]
                self._trigger_3d_render(model_name, mode_index)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.main_window, "3D Load Failed", str(exc))
            if hasattr(self.ui, "lbl_info"):
                self.ui.lbl_info.setText(f"3D load failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
            render_button.setEnabled(True)

    def _trigger_3d_render(self, model_name, mode_index):
        # AGGRESSIVE TIMER STOP: Prevent animation mid-mesh-load
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        try:
            requested_mode = int(mode_index)
        except (TypeError, ValueError):
            raise ValueError(f"Invalid mode index: {mode_index}")

        self._ensure_mode_cache(model_name)

        self.session.current_model_name = model_name
        self.session.current_mode_index = requested_mode
        self.session.current_render_status = "solved"

        sorted_modes = self._get_sorted_mode_indices()
        if sorted_modes and self.session.current_mode_index not in self.session.available_modes_dict:
            self.session.current_mode_index = sorted_modes[0]

        self.session.base_result_mesh, _ = load_base_result_mesh(
            self.session.project_dir,
            model_name,
            self.session.current_mode_index,
        )
        self.session.result_camera_initialized = False
        self.update_warped_mesh()

        if hasattr(self.ui, "lbl_info"):
            self.ui.lbl_info.setText(f"Loaded: {model_name} (Mode {self.session.current_mode_index})")

        self._set_mode_label()
        self._set_mode_navigation_state()

    def _trigger_mesh_preview(self, model_name):
        # AGGRESSIVE TIMER STOP: Prevent animation during mesh preview load
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        self.session.current_model_name = model_name
        self.session.current_mode_index = None
        self.session.current_render_status = "meshed"
        self.session.available_modes_dict = {}
        self.session.base_result_mesh = load_base_mesh_preview(self.session.project_dir, model_name)
        self.session.result_camera_initialized = False
        self.update_warped_mesh()

        if hasattr(self.ui, "label_mode_data"):
            self.ui.label_mode_data.setText("Mode nº: -- | Frequency: -- Hz")
        if hasattr(self.ui, "btn_prev_mode"):
            self.ui.btn_prev_mode.setEnabled(False)
        if hasattr(self.ui, "btn_next_mode"):
            self.ui.btn_next_mode.setEnabled(False)
        if hasattr(self.ui, "lbl_info"):
            self.ui.lbl_info.setText(f"Loaded: {model_name} (Meshed preview)")

    def load_next_mode(self):
        # AGGRESSIVE TIMER STOP: Prevent animation during mode navigation
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        sorted_modes = self._get_sorted_mode_indices()
        if not self.session.current_model_name or not sorted_modes:
            return
        if self.session.current_mode_index not in sorted_modes:
            return

        current_pos = sorted_modes.index(self.session.current_mode_index)
        if current_pos >= len(sorted_modes) - 1:
            return

        new_mode = sorted_modes[current_pos + 1]
        self._trigger_3d_render(self.session.current_model_name, new_mode)

    def load_prev_mode(self):
        # AGGRESSIVE TIMER STOP: Prevent animation during mode navigation
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        
        sorted_modes = self._get_sorted_mode_indices()
        if not self.session.current_model_name or not sorted_modes:
            return
        if self.session.current_mode_index not in sorted_modes:
            return

        current_pos = sorted_modes.index(self.session.current_mode_index)
        if current_pos <= 0:
            return

        new_mode = sorted_modes[current_pos - 1]
        self._trigger_3d_render(self.session.current_model_name, new_mode)

    def update_warped_mesh(self, *_):
        if self.session.base_result_mesh is None or self.widgets.plotter_results is None:
            return

        self.widgets.plotter_results.clear()
        if self.session.current_render_status == "solved":
            warped, vec_name = warp_result_mesh(
                self.session.base_result_mesh,
                self.ui.slider_warp.value(),
            )
            scalar_name = self._resolve_active_scalar(warped)
            self.widgets.plotter_results.add_mesh(
                warped,
                scalars=scalar_name or vec_name,
                cmap="turbo",
                show_scalar_bar=True,
                opacity=0.92,
                show_edges=True,
                edge_color="gray",
            )
        elif "Boundary_Nodes" in self.session.base_result_mesh.point_data:
            binary_cmap = ListedColormap(["#B0BEC5", "#FF0000"])
            self.widgets.plotter_results.add_mesh(
                self.session.base_result_mesh,
                scalars="Boundary_Nodes",
                cmap=binary_cmap,
                clim=[0, 1],
                n_colors=2,
                categories=True,
                show_scalar_bar=False,
                scalar_bar_args={"title": "Boundary Nodes", "n_labels": 2},
                opacity=0.92,
                show_edges=True,
                edge_color="gray",
            )
        else:
            self.widgets.plotter_results.add_mesh(
                self.session.base_result_mesh,
                color="#B0BEC5",
                opacity=0.92,
                show_edges=True,
                edge_color="gray",
            )

        if not self.session.result_camera_initialized:
            self.widgets.plotter_results.reset_camera()
            self.session.result_camera_initialized = True

    def _resolve_active_scalar(self, mesh, allow_fallback=True):
        active_text = (
            self.ui.combo_active_scalar.currentText()
            if hasattr(self.ui, "combo_active_scalar")
            else "Displacement Magnitude (U)"
        )
        scalar_map = {
            "Displacement Magnitude (U)": "Displacement_Magnitude",
            "Displacement Y (U2)": "Displacement_Y",
            "Von Mises Stress": "Von Mises Stress",
            "Max Principal Stress": "Max Principal Stress",
        }
        scalar_name = scalar_map.get(active_text)
        if scalar_name and (
            scalar_name in mesh.point_data or scalar_name in mesh.cell_data
        ):
            return scalar_name
        if active_text in {"Von Mises Stress", "Max Principal Stress"}:
            print(f"[WARNING] Scalar field is unavailable: {active_text}")
        return "Displacement_Magnitude" if allow_fallback else None

    def _show_results_context_menu(self, position):
        if self.session.base_result_mesh is None:
            return

        menu = QMenu(self.widgets.plotter_results)
        path_action = menu.addAction("Define Stress Path (Line)")
        plane_action = menu.addAction("Define Cross-Section (Plane)")
        selected_action = menu.exec(
            self.widgets.plotter_results.mapToGlobal(position)
        )
        if selected_action == path_action:
            self._start_stress_path()
        elif selected_action == plane_action:
            self._define_cross_section()

    def _start_stress_path(self):
        self._path_points = []
        self.widgets.plotter_results.enable_point_picking(
            callback=self._on_stress_path_point,
            use_mesh=True,
            show_message=True,
            show_point=True,
            pickable_window=True,
        )
        print("[SYSTEM] Pick two points to define a stress path.")

    def _on_stress_path_point(self, point):
        if point is None:
            return
        self._path_points.append(np.asarray(point, dtype=float))
        if len(self._path_points) < 2:
            return

        self.widgets.plotter_results.disable_picking()
        point_a, point_b = self._path_points
        line = pv.Line(point_a, point_b, resolution=100)
        self.widgets.plotter_results.add_mesh(
            line,
            name="stress_path",
            color="yellow",
            line_width=3,
            reset_camera=False,
        )
        sampled = self.session.base_result_mesh.sample(line)
        self._open_stress_popup(sampled, np.linspace(0.0, line.length, sampled.n_points))

    def _define_cross_section(self):
        axis, accepted = QInputDialog.getItem(
            self.main_window,
            "Cross-Section Axis",
            "Select plane normal:",
            ["X", "Y", "Z"],
            0,
            False,
        )
        if not accepted:
            return

        bounds = self.session.base_result_mesh.bounds
        axis_index = {"X": 0, "Y": 1, "Z": 2}[axis]
        coordinate, accepted = QInputDialog.getDouble(
            self.main_window,
            "Cross-Section Coordinate",
            f"{axis}-coordinate:",
            float((bounds[axis_index * 2] + bounds[axis_index * 2 + 1]) / 2.0),
            float(bounds[axis_index * 2]),
            float(bounds[axis_index * 2 + 1]),
            6,
        )
        if not accepted:
            return

        origin = [0.0, 0.0, 0.0]
        origin[axis_index] = coordinate
        sliced = self.session.base_result_mesh.slice(normal=axis, origin=origin)
        distances = np.linalg.norm(sliced.points - np.asarray(origin), axis=1)
        self.widgets.plotter_results.add_mesh(
            sliced,
            name=f"stress_plane_{axis}",
            scalars=self._resolve_active_scalar(sliced),
            cmap="turbo",
            opacity=0.45,
            reset_camera=False,
        )
        self._open_stress_popup(sliced, distances)

    def _open_stress_popup(self, sampled_mesh, distances):
        scalar_name = self._resolve_active_scalar(sampled_mesh, allow_fallback=False)
        if scalar_name is None:
            QMessageBox.warning(
                self.main_window,
                "Scalar Unavailable",
                "The selected scalar field is not available for extraction.",
            )
            return
        if scalar_name not in sampled_mesh.point_data and scalar_name not in sampled_mesh.cell_data:
            QMessageBox.warning(
                self.main_window,
                "Scalar Unavailable",
                "The selected scalar field is not available for extraction.",
            )
            return
        values = np.asarray(sampled_mesh[scalar_name], dtype=float)
        if values.size == 0:
            QMessageBox.warning(self.main_window, "No Stress Data", "No scalar values were sampled.")
            return
        popup = StressPlotPopup(
            distances[: values.size],
            values,
            title=f"{scalar_name} distribution",
            parent=self.main_window,
        )
        self._stress_popups.append(popup)
        popup.destroyed.connect(lambda: self._remove_stress_popup(popup))
        popup.show()

    def _remove_stress_popup(self, popup):
        if popup in self._stress_popups:
            self._stress_popups.remove(popup)

    def toggle_animation(self):
        if not hasattr(self.ui, "slider_warp"):
            QMessageBox.warning(self.main_window, "UI Incomplete", "slider_warp control was not found in the loaded UI.")
            return

        if self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
            self.ui.btn_animation.setText("Make it move!")
        else:
            # Ensure no pending render is happening before starting animation
            if self.session.base_result_mesh is not None and self.widgets.plotter_results is not None:
                self.session.animation_phase = 0.0
                self.widgets.animation_timer.start(50)
                self.ui.btn_animation.setText("Stop moving!")

    def _animate_step(self):
        if not hasattr(self.ui, "slider_warp"):
            self.widgets.animation_timer.stop()
            return

        self.session.animation_phase += 0.15
        sine_wave = math.sin(self.session.animation_phase)
        new_slider_val = int(sine_wave * 99)
        self.ui.slider_warp.setValue(new_slider_val)
