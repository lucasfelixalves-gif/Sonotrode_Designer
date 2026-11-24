from __future__ import annotations

import openpyxl
import pytest


@pytest.mark.ui
@pytest.mark.visual
def test_setup_tab_load_preview_amplitude_and_role(ui_harness, dialog_recorder, synthetic_project):
    win = ui_harness.win
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))

    ui_harness.click("btn_load")
    ui_harness.pump(120)

    assert ui_harness.widget("line_path").text() == str(synthetic_project["project_dir"])
    assert ui_harness.widget("list_geometries").count() == 2
    assert win.session.df_mesh is not None
    assert win.session.df_material is not None
    assert win.session.df_step is not None

    preview = getattr(win.setup_controller, "_preview_mesh", None)
    assert preview is not None and preview.n_cells > 0

    ui_harness.set_spinbox("spin_input_amplitude", 20.0)
    ui_harness.click("btn_assign_amplitude")
    assert win.session.input_amplitude == pytest.approx(20.0)
    info_box = dialog_recorder.last("information")
    assert info_box is not None and info_box["title"] == "Amplitude Scaling Set"

    centers = preview.cell_centers().points
    top_cell_idx = int(centers[:, 1].argmax())
    picked_cell = preview.extract_cells([top_cell_idx])
    win.setup_controller.on_cell_picked(picked_cell)
    ui_harness.pump(60)
    assert win.session.last_picked_info is not None

    ui_harness.set_combo("combo_roles", 'Tip  - "YMAX"')
    ui_harness.click("btn_assign")
    assert 'Tip  - "YMAX"' in win.session.semantic_roles
    assert ui_harness.widget("list_roles").count() == 1

    win_shot = ui_harness.screenshot_window("01_setup_tab.png")
    assert win_shot.is_file() and win_shot.stat().st_size > 1000

    view3d_shot = ui_harness.screenshot_3d("setup", "01_setup_3d.png")
    if view3d_shot is not None:
        assert view3d_shot.is_file() and view3d_shot.stat().st_size > 1000


@pytest.mark.ui
@pytest.mark.visual
def test_analytics_tab_table_plots_and_export(ui_harness, dialog_recorder, synthetic_project):
    win = ui_harness.win
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))

    ui_harness.click("btn_load")
    ui_harness.switch_tab("Analytics")

    df = win.session.job_table_df
    assert df is not None and not df.empty
    assert "Length" in df.columns

    solved_rows = df.index[df["Model_name"] == "Cyl_Short"].tolist()
    pending_rows = df.index[df["Model_name"] == "Cyl_Long"].tolist()
    assert len(solved_rows) == 1 and len(pending_rows) == 1

    solved_row_idx = int(solved_rows[0])
    solved_rec = df.loc[solved_row_idx]
    pending_rec = df.loc[int(pending_rows[0])]

    assert solved_rec["Status"] == "Solved"
    assert int(solved_rec["Mode_Index"]) == 1
    assert float(solved_rec["Frequency_Hz"]) == pytest.approx(20150.0, rel=1e-3)
    assert float(solved_rec["Gain_Ratio"]) == pytest.approx(1.0, rel=1e-2)
    assert pending_rec["Status"] == "Pending"

    ui_harness.click("btn_select_all")
    assert len(win.analytics_controller.get_selected_geometries()) == 2

    ui_harness.click("btn_clear_selection")
    assert len(win.analytics_controller.get_selected_geometries()) == 0

    ui_harness.click_table_row(solved_row_idx)
    assert win.analytics_controller.get_selected_geometries() == ["Cyl_Short"]

    ui_harness.set_combo("combo_x", "Length")
    ui_harness.set_combo("combo_y", "Frequency_Hz")
    ui_harness.set_combo("combo_z", "--- None (2D) ---")
    assert len(win.widgets.figure.axes) == 1

    ui_harness.set_combo("combo_z", "Gain_Ratio")
    assert len(win.widgets.figure.axes) == 1
    assert win.widgets.figure.axes[0].name == "3d"

    ui_harness.set_combo("combo_z", "--- None (2D) ---")
    assert len(win.widgets.figure.axes) == 1

    dialog_recorder.input_text_queue.append(("Rig_Test_Summary.xlsx", True))
    ui_harness.click("btn_export_excel")
    export_path = synthetic_project["project_dir"] / "05_Reports" / "Rig_Test_Summary.xlsx"
    assert export_path.is_file()
    wb = openpyxl.load_workbook(export_path)
    try:
        assert wb.active.max_row >= 3
    finally:
        wb.close()

    shot = ui_harness.screenshot_window("02_analytics_tab.png")
    assert shot.is_file() and shot.stat().st_size > 1000


@pytest.mark.ui
@pytest.mark.visual
def test_results_tab_3d_render_modes_warp_and_animation(ui_harness, dialog_recorder, synthetic_project):
    win = ui_harness.win
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))

    ui_harness.click("btn_load")
    ui_harness.switch_tab("Analytics")

    df = win.session.job_table_df
    solved_row_idx = int(df.index[df["Model_name"] == "Cyl_Short"][0])
    ui_harness.click_table_row(solved_row_idx)

    assert ui_harness.widget("btn_render_3D").isEnabled()
    ui_harness.click("btn_render_3D")
    ui_harness.pump(120)

    assert ui_harness.widget("TAB").currentIndex() == 2
    assert win.session.current_model_name == "Cyl_Short"
    assert win.session.current_mode_index == 1
    assert "20150.0 Hz" in ui_harness.widget("label_mode_data").text()
    assert ui_harness.widget("btn_next_mode").isEnabled()
    assert not ui_harness.widget("btn_prev_mode").isEnabled()

    ui_harness.set_slider("slider_warp", 80)
    shot1 = ui_harness.screenshot_window("03_results_tab_mode1_warped.png")
    assert shot1.is_file() and shot1.stat().st_size > 1000
    shot1_3d = ui_harness.screenshot_3d("results", "03_results_3d_mode1.png")
    if shot1_3d is not None:
        assert shot1_3d.is_file() and shot1_3d.stat().st_size > 1000

    ui_harness.click("btn_next_mode")
    ui_harness.pump(100)
    assert win.session.current_mode_index == 2
    assert "24800.0 Hz" in ui_harness.widget("label_mode_data").text()
    assert ui_harness.widget("btn_prev_mode").isEnabled()

    ui_harness.set_slider("slider_warp", 80)
    shot2 = ui_harness.screenshot_window("04_results_tab_mode2_bending.png")
    assert shot2.is_file() and shot2.stat().st_size > 1000
    shot2_3d = ui_harness.screenshot_3d("results", "04_results_3d_mode2.png")
    if shot2_3d is not None:
        assert shot2_3d.is_file() and shot2_3d.stat().st_size > 1000

    ui_harness.click("btn_prev_mode")
    assert win.session.current_mode_index == 1

    ui_harness.click("btn_animation")
    assert win.widgets.animation_timer.isActive()
    assert ui_harness.widget("btn_animation").text() == "Stop moving!"

    ui_harness.pump(180)
    assert win.session.animation_phase > 0.0

    ui_harness.click("btn_animation")
    assert not win.widgets.animation_timer.isActive()
    assert ui_harness.widget("btn_animation").text() == "Make it move!"


@pytest.mark.ui
def test_f5_refresh_and_tetris_dialog(ui_harness, dialog_recorder, synthetic_project):
    win = ui_harness.win
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))

    ui_harness.click("btn_load")
    win._refresh_action.trigger()
    ui_harness.pump(100)
    assert "[SYSTEM] UI refreshed from disk (F5)." in ui_harness.console_text()

    win.setup_controller.open_tetris()
    ui_harness.pump(80)
    assert win.setup_controller.tetris_window is not None
    assert win.setup_controller.tetris_window.isVisible()
    win.setup_controller.tetris_window.close()
    ui_harness.pump(50)
    assert not win.setup_controller.tetris_window.isVisible()
