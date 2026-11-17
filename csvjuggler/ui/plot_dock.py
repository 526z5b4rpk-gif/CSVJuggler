"""A dock holding one plot and its local toolbar."""

from __future__ import annotations

from PySide6.QtWidgets import QDockWidget, QToolBar, QVBoxLayout, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.plot_widget import PlotWidget


class PlotDock(QDockWidget):
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

        toolbar = QToolBar(self)
        toolbar.setMovable(False)
        toolbar.addAction(tr(Msg.ACTION_AUTO_RANGE), self.plot.plotItem.enableAutoRange)
        toolbar.addAction(tr(Msg.ACTION_CLEAR_PLOT), self.plot.clear_curves)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(toolbar)
        layout.addWidget(self.plot)
        self.setWidget(body)
