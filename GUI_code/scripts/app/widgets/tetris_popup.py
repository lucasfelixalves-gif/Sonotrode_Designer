from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout

from .tetris_engine import TetrisBoard


class TetrisDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Tetris")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setFixedSize(300, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.board = TetrisBoard(self)
        layout.addWidget(self.board)
