"""Side panel listing every annotation; a click brings it into view."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.ui.annotation_items import AnnotationManager
from csvjuggler.ui.dialogs.annotation_dialog import KIND_NAMES

ANN_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class AnnotationPanel(QWidget):
    def __init__(self, manager: AnnotationManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.list = QListWidget(self)
        self.list.itemClicked.connect(self._on_clicked)
        self.list.itemDoubleClicked.connect(lambda item: manager.edit(item.data(ANN_ID_ROLE)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_menu)
        self.list.installEventFilter(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.list)
        manager.store.annotations_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        annotations = sorted(self.manager.store.all(), key=lambda a: (a.dataset_alias, a.x))
        for ann in annotations:
            text = tr(Msg.ANN_LIST_ITEM).format(
                kind=tr(KIND_NAMES[ann.kind]), text=ann.text or "—", x=ann.center_x
            )
            if ann.dataset_alias:
                text = f"[{ann.dataset_alias}] {text}"
            item = QListWidgetItem(text)
            item.setData(ANN_ID_ROLE, ann.id)
            item.setToolTip(ann.dataset_path)
            self.list.addItem(item)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        self.manager.focus(item.data(ANN_ID_ROLE))

    def _on_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is not None:
            menu = self.manager.build_annotation_menu(item.data(ANN_ID_ROLE))
            menu.exec(self.list.viewport().mapToGlobal(pos))

    def eventFilter(self, obj, event) -> bool:
        if (
            obj is self.list
            and isinstance(event, QKeyEvent)
            and event.type() == QKeyEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
            and (item := self.list.currentItem()) is not None
        ):
            self.manager.delete(item.data(ANN_ID_ROLE))
            return True
        return super().eventFilter(obj, event)
