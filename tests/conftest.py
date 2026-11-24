from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.main import MainWindow
from scripts.modal_inspection_service import clear_inspection_cache
from ui_harness import DialogRecorder, UIHarness, build_synthetic_project


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--screenshots-dir",
        action="store",
        default=str(Path(__file__).resolve().parent / "artifacts"),
        help="Directory where UI/3D verification screenshots are saved.",
    )


@pytest.fixture(scope="session")
def screenshots_dir(request) -> Path:
    path = Path(request.config.getoption("--screenshots-dir")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def synthetic_project(tmp_path_factory) -> dict:
    root = tmp_path_factory.mktemp("sonotrode_demo_project")
    return build_synthetic_project(root)


@pytest.fixture
def dialog_recorder(monkeypatch) -> DialogRecorder:
    recorder = DialogRecorder()
    recorder.install(monkeypatch)
    return recorder


@pytest.fixture
def main_window(qapp, dialog_recorder):
    orig_stdout = sys.stdout
    orig_stderr = sys.stderr
    clear_inspection_cache()

    win = MainWindow()
    win.show()
    qapp.processEvents()
    try:
        yield win
    finally:
        for timer_name in ("animation_timer", "sim_timer"):
            timer = getattr(win.widgets, timer_name, None)
            if timer is not None and timer.isActive():
                timer.stop()

        tetris_win = getattr(win.setup_controller, "tetris_window", None)
        if tetris_win is not None and tetris_win.isVisible():
            tetris_win.close()

        win.close()
        qapp.processEvents()

        sys.stdout = orig_stdout
        sys.stderr = orig_stderr
        clear_inspection_cache()


@pytest.fixture
def ui_harness(main_window, qtbot, screenshots_dir) -> UIHarness:
    return UIHarness(main_window, qtbot, screenshots_dir)
