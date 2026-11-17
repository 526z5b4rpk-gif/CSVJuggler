"""Tree of loaded series (dataset → series), with a filter field. Drag source."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QMimeData, QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QLineEdit, QTreeView, QVBoxLayout, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.session import Session

SERIES_MIME_TYPE = "application/x-csvjuggler-series-ids"
SERIES_ID_ROLE = Qt.ItemDataRole.UserRole + 1


def encode_series_ids(series_ids: Sequence[str]) -> QMimeData:
    mime = QMimeData()
    mime.setData(SERIES_MIME_TYPE, "\n".join(series_ids).encode("utf-8"))
    return mime


def decode_series_ids(mime: QMimeData) -> list[str]:
    if not mime.hasFormat(SERIES_MIME_TYPE):
        return []
    raw = bytes(mime.data(SERIES_MIME_TYPE).data()).decode("utf-8")
    return [s for s in raw.split("\n") if s]


class SeriesModel(QStandardItemModel):
    """Two levels: datasets, then their series. Series items carry their id."""

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session = session
        session.datasets_changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        self.clear()
        root = self.invisibleRootItem()
        for dataset in self._session.datasets:
            ds_item = QStandardItem(dataset.alias)
            ds_item.setEditable(False)
            if dataset.path is not None:
                ds_item.setToolTip(str(dataset.path))
            for series in dataset.series.values():
                item = QStandardItem(series.label)
                item.setEditable(False)
                item.setData(series.id, SERIES_ID_ROLE)
                unit = f" [{series.unit}]" if series.unit else ""
                item.setToolTip(f"{series.id}{unit} — {len(series)} pts")
                ds_item.appendRow(item)
            root.appendRow(ds_item)

    def mimeTypes(self) -> list[str]:
        return [SERIES_MIME_TYPE]

    def mimeData(self, indexes: Sequence[QModelIndex | QPersistentModelIndex]) -> QMimeData:
        ids: list[str] = []
        for index in indexes:
            item = self.itemFromIndex(self.index(index.row(), index.column(), index.parent()))
            if item is None:
                continue
            ids.extend(self._ids_of(item))
        return encode_series_ids(list(dict.fromkeys(ids)))  # dedupe, keep order

    def _ids_of(self, item: QStandardItem) -> list[str]:
        series_id = item.data(SERIES_ID_ROLE)
        if series_id:
            return [series_id]
        return [item.child(r).data(SERIES_ID_ROLE) for r in range(item.rowCount())]


class SeriesTree(QWidget):
    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model = SeriesModel(session, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setPlaceholderText(tr(Msg.FILTER_PLACEHOLDER))
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)

        self.view = QTreeView(self)
        self.view.setModel(self.proxy)
        self.view.setHeaderHidden(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setDragEnabled(True)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.view.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.model.modelReset.connect(self.view.expandAll)
        self.proxy.rowsInserted.connect(lambda *_: self.view.expandAll())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.view)
        self.view.expandAll()

    def selected_series_ids(self) -> list[str]:
        indexes = [self.proxy.mapToSource(i) for i in self.view.selectionModel().selectedIndexes()]
        return decode_series_ids(self.model.mimeData(indexes))
