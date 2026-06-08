import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class DataFrameTableModel(QAbstractTableModel):
    """Qt table model bridge for displaying a pandas DataFrame."""

    def __init__(self, dataframe, parent=None):
        super().__init__(parent)
        self._df = dataframe.copy() if dataframe is not None else pd.DataFrame()

    def set_dataframe(self, dataframe):
        self.beginResetModel()
        self._df = dataframe.copy() if dataframe is not None else pd.DataFrame()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._df.index)

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter

        if role != Qt.DisplayRole:
            return None

        value = self._df.iat[index.row(), index.column()]
        if pd.isna(value):
            return ""
        col_name = self._df.columns[index.column()]
        if index.column() >= 3:
            try:
                return f"{float(value):.1f}"
            except (ValueError, TypeError):
                pass
        return str(value)

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        col_name = self._df.columns[index.column()]
        if col_name == "Mode_Index":
            return Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable
        return Qt.ItemIsSelectable | Qt.ItemIsEnabled

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        col_name = self._df.columns[index.column()]
        if col_name != "Mode_Index":
            return False
        try:
            self._df.iat[index.row(), index.column()] = int(value)
            self.dataChanged.emit(index, index)
            return True
        except (ValueError, TypeError):
            return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)
