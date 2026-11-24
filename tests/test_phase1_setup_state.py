from __future__ import annotations

import math
from pathlib import Path

import pytest

from scripts.app.state.project_session import ProjectSession


def test_project_session_defaults_and_reset():
    """Verify ProjectSession initializes, validates, and resets Phase 1 attributes."""
    session = ProjectSession()
    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == 300.0
    assert session.active_scalar == "Displacement Magnitude (U)"

    session.specimen_type = "Disc Specimen (Biaxial)"
    session.yield_strength = 450.5
    session.active_scalar = "Von Mises Stress"

    session.clear_project_data()

    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == 300.0
    assert session.active_scalar == "Displacement Magnitude (U)"

    session.yield_strength = 0.0
    assert session.yield_strength == 0.0

    for bad_value in (-1.0, -0.01, math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            session.yield_strength = bad_value
        with pytest.raises(ValueError):
            ProjectSession(yield_strength=bad_value)

    session_source = (
        Path(__file__).resolve().parents[1]
        / "GUI_code"
        / "scripts"
        / "app"
        / "state"
        / "project_session.py"
    ).read_text(encoding="utf-8")
    assert "PySide6" not in session_source


@pytest.mark.ui
def test_ui_widgets_and_controller_bindings(ui_harness, capsys):
    """Verify Phase 1 widgets exist on MainWindow.ui and bind properly to ProjectSession."""
    win = ui_harness.win
    session = win.session

    assert ui_harness.widget("label_specimen_type").text() == "Specimen Type:"
    assert ui_harness.widget("label_yield_strength").text() == "Material Yield Strength:"
    assert ui_harness.widget("label_active_scalar").text() == "Active Scalar Field:"

    combo_specimen = ui_harness.widget("combo_specimen_type")
    spin_yield = ui_harness.widget("spin_yield_strength")
    combo_scalar = ui_harness.widget("combo_active_scalar")

    specimen_items = [combo_specimen.itemText(i) for i in range(combo_specimen.count())]
    assert specimen_items == [
        "Longitudinal Specimen",
        "Disc Specimen (Biaxial)",
        "Flat/Thin-Walled Specimen",
    ]

    scalar_items = [combo_scalar.itemText(i) for i in range(combo_scalar.count())]
    assert scalar_items == [
        "Displacement Magnitude (U)",
        "Displacement Y (U2)",
        "Von Mises Stress",
        "Max Principal Stress",
    ]

    assert spin_yield.minimum() == pytest.approx(0.0)
    assert spin_yield.maximum() == pytest.approx(5000.0)
    assert spin_yield.decimals() == 1
    assert spin_yield.singleStep() == pytest.approx(10.0)
    assert spin_yield.value() == pytest.approx(300.0)
    assert spin_yield.suffix() == " MPa"

    assert combo_specimen.currentText() == "Longitudinal Specimen"
    assert combo_scalar.currentText() == "Displacement Magnitude (U)"

    capsys.readouterr()
    console_before = len(ui_harness.console_text())

    ui_harness.set_combo("combo_specimen_type", "Flat/Thin-Walled Specimen")
    assert session.specimen_type == "Flat/Thin-Walled Specimen"
    output = capsys.readouterr().out + ui_harness.console_text()[console_before:]
    assert "[SetupController] Specimen type updated to: Flat/Thin-Walled Specimen" in output

    console_before = len(ui_harness.console_text())
    ui_harness.set_spinbox("spin_yield_strength", 620.0)
    assert session.yield_strength == pytest.approx(620.0)
    output = capsys.readouterr().out + ui_harness.console_text()[console_before:]
    assert "[SetupController] Yield strength updated to: 620.0 MPa" in output

    console_before = len(ui_harness.console_text())
    ui_harness.set_combo("combo_active_scalar", "Max Principal Stress")
    assert session.active_scalar == "Max Principal Stress"
    output = capsys.readouterr().out + ui_harness.console_text()[console_before:]
    assert "[ResultsController] Active scalar set to: Max Principal Stress" in output


@pytest.mark.ui
def test_session_and_ui_reset_on_create_and_load_project(ui_harness, dialog_recorder, synthetic_project, tmp_path, capsys):
    """Verify Create New Project and Load Project reset Phase 1 session state and UI controls."""
    win = ui_harness.win
    session = win.session

    ui_harness.set_combo("combo_specimen_type", "Disc Specimen (Biaxial)")
    ui_harness.set_spinbox("spin_yield_strength", 450.5)
    ui_harness.set_combo("combo_active_scalar", "Von Mises Stress")

    # Cancelled dialogs must not reset session or UI state
    ui_harness.click("btn_new_project")
    ui_harness.click("btn_load")
    assert session.specimen_type == "Disc Specimen (Biaxial)"
    assert session.yield_strength == pytest.approx(450.5)
    assert session.active_scalar == "Von Mises Stress"

    capsys.readouterr()
    console_before_create = ui_harness.console_text()
    dialog_recorder.existing_dir_queue.append(str(tmp_path))
    dialog_recorder.input_text_queue.append(("Phase1_New_Proj", True))
    ui_harness.click("btn_new_project")
    ui_harness.pump(80)

    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == pytest.approx(300.0)
    assert session.active_scalar == "Displacement Magnitude (U)"
    assert ui_harness.widget("combo_specimen_type").currentText() == "Longitudinal Specimen"
    assert ui_harness.widget("spin_yield_strength").value() == pytest.approx(300.0)
    assert ui_harness.widget("combo_active_scalar").currentText() == "Displacement Magnitude (U)"

    output_after_create = capsys.readouterr().out + ui_harness.console_text()[len(console_before_create):]
    assert "[SetupController]" not in output_after_create
    assert "[ResultsController]" not in output_after_create

    # Mutate again, then verify Load Project resets cleanly without extra update logs
    ui_harness.set_combo("combo_specimen_type", "Flat/Thin-Walled Specimen")
    ui_harness.set_spinbox("spin_yield_strength", 710.0)
    ui_harness.set_combo("combo_active_scalar", "Displacement Y (U2)")

    capsys.readouterr()
    console_before_load = ui_harness.console_text()
    dialog_recorder.open_file_queue.append(str(synthetic_project["workbook_path"]))
    ui_harness.click("btn_load")
    ui_harness.pump(120)

    assert session.specimen_type == "Longitudinal Specimen"
    assert session.yield_strength == pytest.approx(300.0)
    assert session.active_scalar == "Displacement Magnitude (U)"
    assert ui_harness.widget("combo_specimen_type").currentText() == "Longitudinal Specimen"
    assert ui_harness.widget("spin_yield_strength").value() == pytest.approx(300.0)
    assert ui_harness.widget("combo_active_scalar").currentText() == "Displacement Magnitude (U)"

    output_after_load = capsys.readouterr().out + ui_harness.console_text()[len(console_before_load):]
    assert "[SetupController]" not in output_after_load
    assert "[ResultsController]" not in output_after_load
