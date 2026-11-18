import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSlider, QVBoxLayout, QWidget


class StressPlotPopup(QWidget):
    """Floating plot for static stress samples extracted from a result mesh."""

    def __init__(self, distances, stress_values, title="Stress distribution", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle(title)
        self.resize(720, 480)

        self._distances = np.asarray(distances, dtype=float)
        self._stress_values = np.asarray(stress_values, dtype=float)
        self._figure = Figure()
        self._canvas = FigureCanvas(self._figure)
        self._axis = self._figure.add_subplot(111)
        self._scale_label = QLabel("Amplitude scale: 1.00x")
        self._slider = QSlider()
        self._slider.setOrientation(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 200)
        self._slider.setValue(100)
        self._slider.valueChanged.connect(self._update_plot)
        self._update_plot(self._slider.value())

        layout = QVBoxLayout(self)
        layout.addWidget(self._canvas)
        layout.addWidget(self._scale_label)
        layout.addWidget(self._slider)

    def _update_plot(self, slider_value):
        scale = float(slider_value) / 100.0
        self._scale_label.setText(f"Amplitude scale: {scale:.2f}x")
        self._axis.clear()
        self._axis.plot(self._distances, self._stress_values * scale)
        self._axis.set_xlabel("Distance [mm]")
        self._axis.set_ylabel("Stress [MPa]")
        self._axis.grid(True, alpha=0.25)
        if self.isVisible():
            self._canvas.draw_idle()

    def showEvent(self, event):
        super().showEvent(event)
        self._canvas.draw_idle()
