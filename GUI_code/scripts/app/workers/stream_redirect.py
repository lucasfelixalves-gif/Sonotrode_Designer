from PySide6.QtCore import QObject, Signal


class EmittingStream(QObject):
    """File-like stream that emits text through a Qt signal."""

    textWritten = Signal(str)

    def write(self, text):
        if text:
            self.textWritten.emit(str(text))

    def flush(self):
        # Stream API compatibility (no buffered state to flush).
        pass
