import sys
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from PySide6.QtCore import QFile, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout

try:
    from scripts.app.controllers.base_controller import AppContext
    from scripts.app.controllers.setup_controller import SetupController
    from scripts.app.controllers.analytics_controller import AnalyticsController
    from scripts.app.controllers.results_controller import ResultsController
    from scripts.app.state.project_session import ProjectSession
    from scripts.app.workers.stream_redirect import EmittingStream
except ModuleNotFoundError:
    from app.controllers.base_controller import AppContext
    from app.controllers.setup_controller import SetupController
    from app.controllers.analytics_controller import AnalyticsController
    from app.controllers.results_controller import ResultsController
    from app.state.project_session import ProjectSession
    from app.workers.stream_redirect import EmittingStream


class MainWindow(QMainWindow):
    """Thin composition root: UI loading + app context + controller binding."""

    def __init__(self):
        super().__init__()

        ui_path = Path(__file__).parent / "MainWindow.ui"
        ui_file = QFile(str(ui_path))
        ui_file.open(QFile.ReadOnly)
        loader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()

        central = self.ui.centralWidget()
        central.setParent(self)
        self.setCentralWidget(central)
        self.setWindowTitle(self.ui.windowTitle())
        self.resize(self.ui.size())

        self.session = ProjectSession()

        self.widgets = SimpleNamespace()
        self.widgets.plotter = None
        self.widgets.plotter_results = None
        self.widgets.figure = plt.figure()
        self.widgets.canvas = FigureCanvas(self.widgets.figure)
        self.widgets.animation_timer = QTimer(self)
        self.widgets.sim_timer = QTimer(self)
        self.widgets.btn_toggle_ccx_default_style = ""

        self._stdout_original = sys.stdout
        self._stderr_original = sys.stderr
        self._console_stream = EmittingStream(self)
        sys.stdout = self._console_stream
        sys.stderr = self._console_stream

        self.context = AppContext(
            main_window=self,
            ui=self.ui,
            session=self.session,
            widgets=self.widgets,
        )

        self.setup_controller = SetupController(self.context)
        self.analytics_controller = AnalyticsController(self.context)
        self.results_controller = ResultsController(self.context)

        self.context.controllers["setup"] = self.setup_controller
        self.context.controllers["analytics"] = self.analytics_controller
        self.context.controllers["results"] = self.results_controller

        self._console_stream.textWritten.connect(self.analytics_controller.update_console)
        self.widgets.animation_timer.timeout.connect(self.results_controller._animate_step)
        self.widgets.sim_timer.timeout.connect(self.analytics_controller.update_sim_timer)

        if hasattr(self.ui, "frame_plot"):
            plot_layout = QVBoxLayout(self.ui.frame_plot)
            plot_layout.setContentsMargins(0, 0, 0, 0)
            plot_layout.addWidget(self.widgets.canvas)
            self.widgets.toolbar = NavigationToolbar2QT(self.widgets.canvas, self)
            plot_layout.addWidget(self.widgets.toolbar)

        self.setup_controller.bind()
        self.analytics_controller.bind()
        self.results_controller.bind()
        self._setup_refresh_shortcut()

        if hasattr(self.ui, "label_sim_timer"):
            self.ui.label_sim_timer.setText("Elapsed Time: 00:00")
        if hasattr(self.ui, "label"):
            self.ui.label.setText("ElapsedTime: 00:00")

    def _setup_refresh_shortcut(self):
        self._refresh_action = QAction("Refresh From Disk", self)
        self._refresh_action.setShortcut(QKeySequence("F5"))
        self._refresh_action.triggered.connect(self._refresh_ui_from_disk)
        self.addAction(self._refresh_action)

    def _refresh_ui_from_disk(self):
        if not self.session.project_dir:
            self.analytics_controller.update_console("[SYSTEM] F5 refresh skipped: no project loaded.\n")
            return

        mesh_worker = self.session.mesh_worker
        ccx_worker = self.session.ccx_worker
        if (mesh_worker is not None and mesh_worker.isRunning()) or (ccx_worker is not None and ccx_worker.isRunning()):
            self.analytics_controller.update_console("[SYSTEM] F5 refresh skipped: mesh/CCX process is running.\n")
            return

        self.setup_controller.refresh_project_from_disk()
        self.analytics_controller.load_analytics_data()
        self.analytics_controller.update_console("[SYSTEM] UI refreshed from disk (F5).\n")

    def closeEvent(self, event):
        """Gracefully close PyVista plotters before Qt destroys windows."""
        # Stop all timers
        if hasattr(self.widgets, 'animation_timer') and self.widgets.animation_timer.isActive():
            self.widgets.animation_timer.stop()
        if hasattr(self.widgets, 'sim_timer') and self.widgets.sim_timer.isActive():
            self.widgets.sim_timer.stop()
        
        # Close plotters to destroy VTK OpenGL context safely
        if hasattr(self.widgets, 'plotter') and self.widgets.plotter is not None:
            try:
                self.widgets.plotter.close()
            except Exception as e:
                print(f"[WARNING] Error closing plotter: {e}")
        
        if hasattr(self.widgets, 'plotter_results') and self.widgets.plotter_results is not None:
            try:
                self.widgets.plotter_results.close()
            except Exception as e:
                print(f"[WARNING] Error closing plotter_results: {e}")
        
        # Restore stdout/stderr
        sys.stdout = self._stdout_original
        sys.stderr = self._stderr_original
        
        # Call parent closeEvent
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
