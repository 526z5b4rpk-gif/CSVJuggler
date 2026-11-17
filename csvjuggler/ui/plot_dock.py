"""A dock holding one graph and its local toolbar."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDockWidget, QInputDialog, QToolBar, QVBoxLayout, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.plot_menus import PlotController
from csvjuggler.ui.plot_widget import PlotWidget


class PlotDock(QDockWidget):
    closed = Signal(object)
    """Emitted with the dock when the user closes it."""
    title_changed = Signal(str)

    def __init__(
        self,
        session: Session,
        dock_id: str,
        title: str,
        config: PlotConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName(dock_id)  # stable name, needed by QMainWindow.saveState
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.plot = PlotWidget(session, config)
        self.controller = PlotController(self.plot, self)

        self.toolbar = QToolBar(self)
        self.toolbar.setMovable(False)
        self.toolbar.addAction(tr(Msg.ACTION_AUTO_RANGE), self.plot.auto_range)
        self.toolbar.addAction(tr(Msg.ACTION_SPLIT), self.plot.split)
        self.toolbar.addAction(
            tr(Msg.ACTION_UNSPLIT), lambda: self.plot.remove_subplot(len(self.plot.subplots) - 1)
        )
        self.toolbar.addAction(tr(Msg.MENU_PLOT_SETTINGS), self.controller.edit_plot_settings)
        self.toolbar.addAction(tr(Msg.ACTION_RENAME), self.ask_rename)
        self.toolbar.addAction(tr(Msg.ACTION_CLEAR_PLOT), self.plot.clear_curves)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.plot)
        self.setWidget(body)

    @property
    def dock_id(self) -> str:
        return self.objectName()

    def rename(self, title: str) -> None:
        if title and title != self.windowTitle():
            self.setWindowTitle(title)
            self.title_changed.emit(title)

    def ask_rename(self) -> None:
        title, ok = QInputDialog.getText(
            self, tr(Msg.RENAME_PLOT_TITLE), tr(Msg.RENAME_PLOT_LABEL), text=self.windowTitle()
        )
        if ok:
            self.rename(title.strip())

    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        if event.isAccepted():
            self.closed.emit(self)
