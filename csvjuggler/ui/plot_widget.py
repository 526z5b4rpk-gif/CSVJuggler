"""pyqtgraph wrapper: displays the curves described by a :class:`PlotConfig`."""

from __future__ import annotations

import logging

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QWidget

from csvjuggler.model.plot_config import CurveConfig, PlotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.series_tree import SERIES_MIME_TYPE, decode_series_ids
from csvjuggler.utils.colors import next_color

log = logging.getLogger(__name__)


class PlotWidget(pg.PlotWidget):
    """A plot fed by series ids. Accepts series dropped from the series tree."""

    config_changed = Signal()
    missing_series_changed = Signal(list)
    """Emitted after ``apply_config`` with the ids that could not be resolved."""

    def __init__(
        self, session: Session, config: PlotConfig | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._config = PlotConfig()
        self._items: dict[str, pg.PlotDataItem] = {}
        self._legend = self.plotItem.addLegend()
        self.setAcceptDrops(True)
        self.apply_config(config or PlotConfig())

    # -- config ---------------------------------------------------------------------------

    @property
    def config(self) -> PlotConfig:
        return self._config

    def apply_config(self, config: PlotConfig) -> None:
        """Make the display match ``config``. Existing items are updated, never recreated."""
        self._config = config
        plot = self.plotItem
        plot.setTitle(config.title or None)
        plot.showGrid(x=config.show_grid_x, y=config.show_grid_y, alpha=config.grid_alpha)
        self._legend.setVisible(config.show_legend)

        wanted = {c.series_id for c in config.curves}
        for series_id in list(self._items):
            if series_id not in wanted:
                self._remove_item(series_id)

        missing: list[str] = []
        for curve in config.curves:
            item = self._items.get(curve.series_id) or self._create_item(curve)
            if item is None:
                missing.append(curve.series_id)
                continue
            self._style_item(item, curve)
        if missing:
            log.warning("Missing series in plot: %s", ", ".join(missing))
        self.missing_series_changed.emit(missing)

    # -- curves ---------------------------------------------------------------------------

    def add_series(self, series_ids: list[str]) -> list[str]:
        """Add curves for ``series_ids`` (already present ones are skipped). Returns added ids."""
        added: list[str] = []
        for series_id in series_ids:
            if self._config.curve(series_id) or self._session.get_series(series_id) is None:
                continue
            color = next_color(c.color for c in self._config.curves)
            self._config.curves.append(CurveConfig(series_id=series_id, color=color))
            added.append(series_id)
        if added:
            self.apply_config(self._config)
            self.config_changed.emit()
        return added

    def clear_curves(self) -> None:
        if not self._config.curves:
            return
        self._config.curves.clear()
        self.apply_config(self._config)
        self.config_changed.emit()

    def curve_item(self, series_id: str) -> pg.PlotDataItem | None:
        return self._items.get(series_id)

    def _create_item(self, curve: CurveConfig) -> pg.PlotDataItem | None:
        series = self._session.get_series(curve.series_id)
        if series is None:
            return None
        item = pg.PlotDataItem(series.x, series.y, name=curve.alias or series.label)
        self.plotItem.addItem(item)
        # Set after addItem: with clipToView enabled before the item has a ViewBox parent,
        # pyqtgraph 0.14 queries the QGraphicsView instead of the ViewBox and fails.
        item.setDownsampling(auto=True, method="peak")
        item.setClipToView(True)
        self._items[curve.series_id] = item
        return item

    def _style_item(self, item: pg.PlotDataItem, curve: CurveConfig) -> None:
        item.setPen(pg.mkPen(curve.color, width=curve.width))
        item.setVisible(curve.visible)
        series = self._session.get_series(curve.series_id)
        name = curve.alias or (series.label if series else curve.series_id)
        if item.name() != name:
            item.opts["name"] = name
            self._legend.removeItem(item)
            self._legend.addItem(item, name)

    def _remove_item(self, series_id: str) -> None:
        item = self._items.pop(series_id)
        self._legend.removeItem(item)
        self.plotItem.removeItem(item)

    # -- drag and drop --------------------------------------------------------------------

    @staticmethod
    def _accept_series_drag(event: QDragMoveEvent) -> None:
        # QDragEnterEvent derives from QDragMoveEvent.
        if event.mimeData().hasFormat(SERIES_MIME_TYPE):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        self._accept_series_drag(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        self._accept_series_drag(event)

    def dropEvent(self, event: QDropEvent) -> None:
        ids = decode_series_ids(event.mimeData())
        if not ids:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.add_series(ids)
