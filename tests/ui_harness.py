from __future__ import annotations

import io
import math
import os
from pathlib import Path
from typing import Any

import gmsh
import openpyxl
from PIL import Image
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from scripts.augment_master_workbook import augment_workbook
from scripts.ccx_results_parser import parse_mesh_node_sets
from scripts.meshing import mesh_step_to_inp


class DialogRecorder:
    """Intercept Qt modal dialogs in tests so automated runs never block."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.open_file_queue: list[str] = []
        self.existing_dir_queue: list[str] = []
        self.input_text_queue: list[tuple[str, bool]] = []

    def clear(self) -> None:
        self.records.clear()
        self.open_file_queue.clear()
        self.existing_dir_queue.clear()
        self.input_text_queue.clear()

    def last(self, kind: str | None = None) -> dict[str, Any] | None:
        if kind is None:
            return self.records[-1] if self.records else None
        for rec in reversed(self.records):
            if rec.get("kind") == kind:
                return rec
        return None

    def install(self, monkeypatch) -> None:
        def _record_box(kind: str, _parent, title: str, text: str, *_args, **_kwargs):
            self.records.append({"kind": kind, "title": str(title), "text": str(text)})
            return QMessageBox.StandardButton.Ok

        def _get_open_file_name(_parent, caption: str = "", _dir: str = "", _filter: str = "", *_args, **_kwargs):
            chosen = self.open_file_queue.pop(0) if self.open_file_queue else ""
            self.records.append({"kind": "open_file", "title": str(caption), "text": str(chosen)})
            return chosen, "Excel Files (*.xlsx)" if chosen else ""

        def _get_existing_directory(_parent, caption: str = "", _dir: str = "", *_args, **_kwargs):
            chosen = self.existing_dir_queue.pop(0) if self.existing_dir_queue else ""
            self.records.append({"kind": "existing_dir", "title": str(caption), "text": str(chosen)})
            return chosen

        def _get_text(_parent, title: str = "", label: str = "", *args, **kwargs):
            default_text = kwargs.get("text", "")
            if not default_text and len(args) >= 2 and isinstance(args[1], str):
                default_text = args[1]
            if self.input_text_queue:
                val, ok = self.input_text_queue.pop(0)
            else:
                val, ok = str(default_text), True
            self.records.append({"kind": "input_text", "title": str(title), "text": f"{label} -> {val!r} (ok={ok})"})
            return val, ok

        monkeypatch.setattr(QMessageBox, "information", lambda p, title, text, *a, **k: _record_box("information", p, title, text, *a, **k))
        monkeypatch.setattr(QMessageBox, "warning", lambda p, title, text, *a, **k: _record_box("warning", p, title, text, *a, **k))
        monkeypatch.setattr(QMessageBox, "critical", lambda p, title, text, *a, **k: _record_box("critical", p, title, text, *a, **k))
        monkeypatch.setattr(QFileDialog, "getOpenFileName", _get_open_file_name)
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", _get_existing_directory)
        monkeypatch.setattr(QInputDialog, "getText", _get_text)


class UIHarness:
    """High-level driver and visual screenshot helper for MainWindow tests."""

    def __init__(self, win, qtbot, screenshots_dir: Path) -> None:
        self.win = win
        self.qtbot = qtbot
        self.screenshots_dir = Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    def pump(self, ms: int = 50) -> None:
        QApplication.processEvents()
        if ms > 0:
            self.qtbot.wait(ms)
            QApplication.processEvents()

    def widget(self, name: str):
        if not hasattr(self.win.ui, name):
            raise AssertionError(f"Missing UI widget '{name}' on MainWindow.ui")
        return getattr(self.win.ui, name)

    def switch_tab(self, tab: int | str) -> None:
        tab_widget = self.widget("TAB")
        if isinstance(tab, int):
            target_idx = tab
        else:
            needle = str(tab).strip().lower()
            target_idx = -1
            for idx in range(tab_widget.count()):
                if tab_widget.tabText(idx).strip().lower() == needle:
                    target_idx = idx
                    break
            assert target_idx >= 0, f"Tab named {tab!r} not found in TAB widget"
        tab_widget.setCurrentIndex(target_idx)
        self.pump(80)

    def click(self, widget_or_name) -> None:
        w = self.widget(widget_or_name) if isinstance(widget_or_name, str) else widget_or_name
        assert w.isEnabled(), f"Widget '{w.objectName()}' is disabled and cannot be clicked"
        self.qtbot.mouseClick(w, Qt.LeftButton)
        self.pump(80)

    def set_spinbox(self, name: str, value: float) -> None:
        w = self.widget(name)
        w.setValue(value)
        self.pump(50)

    def set_combo(self, name: str, text_or_index: str | int) -> None:
        w = self.widget(name)
        if isinstance(text_or_index, int):
            assert 0 <= text_or_index < w.count(), f"Combo '{name}' index {text_or_index} out of range ({w.count()})"
            w.setCurrentIndex(text_or_index)
        else:
            idx = w.findText(text_or_index)
            if idx < 0:
                items = [w.itemText(i) for i in range(w.count())]
                raise AssertionError(f"Combo '{name}' does not contain {text_or_index!r}; options={items}")
            w.setCurrentIndex(idx)
        self.pump(50)

    def set_slider(self, name: str, value: int) -> None:
        w = self.widget(name)
        w.setValue(int(value))
        self.pump(80)

    def click_table_row(self, row: int, col: int = 0) -> None:
        table = self.widget("table_results")
        model = table.model()
        assert model is not None, "table_results has no model attached"
        assert 0 <= row < model.rowCount(), f"Row {row} out of range ({model.rowCount()})"
        index = model.index(row, col)
        table.scrollTo(index)
        self.pump(30)
        rect = table.visualRect(index)
        assert rect.isValid(), f"visualRect invalid for row={row}, col={col}"
        self.qtbot.mouseClick(table.viewport(), Qt.LeftButton, pos=rect.center())
        self.pump(80)

    def console_text(self) -> str:
        return self.widget("plainTextEdit_console").toPlainText()

    def _grab_plotter_image(self, plotter) -> Image.Image | None:
        if plotter is None:
            return None
        try:
            plotter.render()
            arr = plotter.screenshot(return_img=True)
        except Exception:
            return None
        if arr is None:
            return None
        return Image.fromarray(arr).convert("RGBA")

    def screenshot_3d(self, which: str, filename: str) -> Path | None:
        if which == "setup":
            plotter = self.win.widgets.plotter
        elif which == "results":
            plotter = self.win.widgets.plotter_results
        else:
            raise ValueError(f"Unknown 3D plotter selector: {which!r}")

        self.pump(60)
        img = self._grab_plotter_image(plotter)
        if img is None:
            return None

        out_path = self.screenshots_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out_path)
        return out_path

    def screenshot_window(self, filename: str, composite_3d: bool = True) -> Path:
        self.pump(100)
        pixmap = self.win.grab()

        ba = QByteArray()
        qbuf = QBuffer(ba)
        qbuf.open(QIODevice.WriteOnly)
        pixmap.save(qbuf, "PNG")
        qbuf.close()
        win_img = Image.open(io.BytesIO(bytes(ba))).convert("RGBA")

        if composite_3d:
            dpr = float(pixmap.devicePixelRatio() or 1.0)
            for plotter in (self.win.widgets.plotter, self.win.widgets.plotter_results):
                if plotter is None or not plotter.isVisible():
                    continue
                img_3d = self._grab_plotter_image(plotter)
                if img_3d is None:
                    continue
                top_left = plotter.mapTo(self.win, QPoint(0, 0))
                x = int(round(top_left.x() * dpr))
                y = int(round(top_left.y() * dpr))
                w = max(1, int(round(plotter.width() * dpr)))
                h = max(1, int(round(plotter.height() * dpr)))
                resized = img_3d.resize((w, h), Image.Resampling.LANCZOS)
                win_img.paste(resized, (x, y))

        out_path = self.screenshots_dir / filename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        win_img.convert("RGB").save(out_path)
        return out_path


def _read_inp_node_coords(inp_path: Path) -> dict[int, tuple[float, float, float]]:
    coords: dict[int, tuple[float, float, float]] = {}
    in_node_block = False
    with open(inp_path, "r", encoding="utf-8", errors="ignore") as src:
        for raw_line in src:
            line = raw_line.strip()
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
                coords[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
            except ValueError:
                continue
    return coords


def _export_cylinder_step(step_path: Path, *, length: float, radius: float) -> None:
    started_gmsh = False
    try:
        if not gmsh.isInitialized():
            gmsh.initialize()
            started_gmsh = True
        gmsh.clear()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add(step_path.stem)
        gmsh.model.occ.addCylinder(0.0, 0.0, 0.0, 0.0, float(length), 0.0, float(radius))
        gmsh.model.occ.synchronize()
        gmsh.write(str(step_path))
    finally:
        try:
            gmsh.clear()
        except Exception:
            pass
        if started_gmsh:
            gmsh.finalize()


def _write_synthetic_dat_and_frd(
    *,
    mesh_inp_path: Path,
    dat_path: Path,
    frd_path: Path,
    length: float = 60.0,
    radius: float = 10.0,
) -> None:
    node_coords = _read_inp_node_coords(mesh_inp_path)
    node_sets, _ = parse_mesh_node_sets(str(mesh_inp_path), set_names=("YMIN", "YMAX"))
    ymin_ids = sorted(node_sets.get("YMIN", set()))
    ymax_ids = sorted(node_sets.get("YMAX", set()))

    def _mode1_disp(x: float, y: float, z: float) -> tuple[float, float, float]:
        # Pure longitudinal half-wave mode along Y (anti-phase tip vs base)
        return (0.0, 0.01 * ((y - (length / 2.0)) / (length / 2.0)), 0.0)

    def _mode2_disp(x: float, y: float, z: float) -> tuple[float, float, float]:
        # Transverse bending mode along X
        return (
            0.015 * math.sin(math.pi * y / length),
            0.0005 * (x / radius),
            0.0,
        )

    dat_lines = [
        "     E I G E N V A L U E   O U T P U T",
        "",
        "  MODE NO    EIGENVALUE           REAL PART            IMAGINARY PART",
        "                                  (RAD/TIME)           (CYCLES/TIME)",
        "      1   1.602901E+10   1.266057E+05   2.015000E+04   0.000000E+00",
        "      2   2.428154E+10   1.558254E+05   2.480000E+04   0.000000E+00",
        "",
    ]

    for mode_idx, freq_hz, disp_fn in (
        (1, 20150.0, _mode1_disp),
        (2, 24800.0, _mode2_disp),
    ):
        dat_lines.append(f"     E I G E N V A L U E   N U M B E R     {mode_idx}")
        for set_name, nids in (("YMIN", ymin_ids), ("YMAX", ymax_ids)):
            dat_lines.append("")
            dat_lines.append(f" displacements (vx,vy,vz) for set {set_name} and time  {freq_hz:.7E}")
            dat_lines.append("")
            for nid in nids:
                ux, uy, uz = disp_fn(*node_coords[nid])
                dat_lines.append(f" {nid:9d} {ux:13.5E} {uy:13.5E} {uz:13.5E}")
        dat_lines.append("")

    dat_path.write_text("\n".join(dat_lines) + "\n", encoding="utf-8")

    sorted_nids = sorted(node_coords.keys())
    frd_lines = [
        "    1CSONOTRODE_RIG",
        f"    2C                  {len(sorted_nids):10d}                                     1",
    ]
    for mode_idx, freq_hz, disp_fn in (
        (1, 20150.0, _mode1_disp),
        (2, 24800.0, _mode2_disp),
    ):
        frd_lines.extend([
            f"    1PMODE                     {mode_idx}",
            f"  100CL  101{freq_hz:12.5E}{len(sorted_nids):12d}                     2    1           1",
            " -4  DISP        4    1",
            " -5  D1          1    2    1    0",
            " -5  D2          1    2    2    0",
            " -5  D3          1    2    3    0",
            " -5  ALL         1    2    0    0    1ALL",
        ])
        for nid in sorted_nids:
            ux, uy, uz = disp_fn(*node_coords[nid])
            frd_lines.append(f" -1{nid:10d}{ux:12.5E}{uy:12.5E}{uz:12.5E}")
        frd_lines.append(" -3")

    frd_lines.append("  9999")
    frd_path.write_text("\n".join(frd_lines) + "\n", encoding="utf-8")


def build_synthetic_project(root_dir: Path) -> dict[str, Any]:
    """Create a complete lightweight project folder with real STEP/INP and synthetic DAT/FRD outputs."""
    project_dir = Path(root_dir)
    config_dir = project_dir / "01_Master_Config"
    step_dir = project_dir / "02_Geometry_STEP"
    mesh_dir = project_dir / "03_Meshes_INP"
    results_dir = project_dir / "04_Results_CCX"
    reports_dir = project_dir / "05_Reports"
    for d in (config_dir, step_dir, mesh_dir, results_dir, reports_dir):
        d.mkdir(parents=True, exist_ok=True)

    cyl_short_step = step_dir / "Cyl_Short.step"
    cyl_long_step = step_dir / "Cyl_Long.step"
    _export_cylinder_step(cyl_short_step, length=60.0, radius=10.0)
    _export_cylinder_step(cyl_long_step, length=80.0, radius=10.0)

    wb_path = config_dir / "Demo_Sonotrode.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Design Table for: Demo_Sonotrode", "", ""])
    ws.append(["", "Length@Sketch1", "Radius@Sketch1"])
    ws.append(["DEFAULT", 50.0, 10.0])
    ws.append(["Cyl_Short", 60.0, 10.0])
    ws.append(["Cyl_Long", 80.0, 10.0])
    wb.save(wb_path)

    augment_workbook(str(wb_path), "Sheet1")

    wb = openpyxl.load_workbook(wb_path)
    ws_mesh = wb["Meshing_Parameters"]
    headers = {str(ws_mesh.cell(row=1, column=c).value).strip(): c for c in range(1, ws_mesh.max_column + 1)}
    ws_mesh.cell(row=2, column=headers["Element_order"]).value = 1
    ws_mesh.cell(row=2, column=headers["Characteristic_length_min"]).value = 8.0
    ws_mesh.cell(row=2, column=headers["Characteristic_length_max"]).value = 12.0
    wb.save(wb_path)

    mesh_inp_path = mesh_dir / "Cyl_Short_mesh.inp"
    mesh_step_to_inp(
        step_path=str(cyl_short_step),
        mesh_output_path=str(mesh_inp_path),
        mesh_config={
            "Element_order": 1,
            "Characteristic_length_min": 8.0,
            "Characteristic_length_max": 12.0,
        },
        semantic_roles=None,
        quiet=True,
    )

    dat_path = results_dir / "Cyl_Short.dat"
    frd_path = results_dir / "Cyl_Short.frd"
    _write_synthetic_dat_and_frd(
        mesh_inp_path=mesh_inp_path,
        dat_path=dat_path,
        frd_path=frd_path,
        length=60.0,
        radius=10.0,
    )

    return {
        "project_dir": project_dir,
        "workbook_path": wb_path,
        "models": ["Cyl_Short", "Cyl_Long"],
        "solved_model": "Cyl_Short",
        "pending_model": "Cyl_Long",
        "mesh_inp_path": mesh_inp_path,
        "dat_path": dat_path,
        "frd_path": frd_path,
    }
