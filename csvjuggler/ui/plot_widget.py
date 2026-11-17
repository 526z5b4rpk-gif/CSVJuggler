"""pyqtgraph wrapper: a graph made of vertically stacked subplots sharing the X axis.

The widget displays what its :class:`PlotConfig` describes. ``apply_config`` updates existing
curve items (``setData``/``setPen``) instead of recreating them.
"""

from __future__ import annotations

import logging

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QWidget

from csvjuggler.model.plot_config import CurveConfig, PlotConfig, SubplotConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.series_tree import SERIES_MIME_TYPE, decode_series_ids
from csvjuggler.utils.colors import next_color

log = logging.getLogger(__name__)


class SubPlot:
    """One PlotItem of the graph and the curve items it holds."""

    def __init__(self, owner: PlotWidget, plot_item: pg.PlotItem) -> None:
        self.owner = owner
        self.plot_item = plot_item
        self.legend = plot_item.addLegend()
        self.items: dict[str, pg.PlotDataItem] = {}
        # Axes draw the grid; keep them (and the grid) under the curves.
        for name in ("left", "bottom", "right", "top"):
            plot_item.getAxis(name).setZValue(-1000)

    @property
    def view_box(self) -> pg.ViewBox:
        return self.plot_item.getViewBox()

    def apply(self, config: SubplotConfig, plot_config: PlotConfig) -> list[str]:
        """Synchronise items with ``config``. Returns the ids of unresolved series."""
        session = self.owner.session
        self.plot_item.showGrid(
            x=plot_config.show_grid_x, y=plot_config.show_grid_y, alpha=plot_config.grid_alpha
        )
        self.legend.setVisible(plot_config.show_legend)

        wanted = {c.series_id for c in config.curves}
        for series_id in list(self.items):
            if series_id not in wanted:
                self.remove_item(series_id)

        missing: list[str] = []
        for curve in config.curves:
            series = session.get_series(curve.series_id)
            item = self.items.get(curve.series_id)
            if series is None:
                missing.append(curve.series_id)
                if item is not None:
                    self.remove_item(curve.series_id)
                continue
            if item is None:
                item = self._create_item(curve, series.x, series.y)
            self._style_item(item, curve, curve.alias or series.label)
        return missing

    def refresh_data(self, config: SubplotConfig) -> None:
        """Push new series data into existing items (after a reload)."""
        for curve in config.curves:
            series = self.owner.session.get_series(curve.series_id)
            item = self.items.get(curve.series_id)
            if series is not None and item is not None:
                item.setData(series.x, series.y)

    def _create_item(self, curve: CurveConfig, x, y) -> pg.PlotDataItem:
        item = pg.PlotDataItem(
            x, y, name=curve.alias or curve.series_id, pen=pg.mkPen(curve.color, width=curve.width)
        )
        self.plot_item.addItem(item)
        # Set after addItem: with clipToView enabled before the item has a ViewBox parent,
        # pyqtgraph 0.14 queries the QGraphicsView instead of the ViewBox and fails.
        item.setDownsampling(auto=True, method="peak")
        item.setClipToView(True)
        item.visibleChanged.connect(lambda sid=curve.series_id: self._on_visibility(sid))
        self.items[curve.series_id] = item
        return item

    def _style_item(self, item: pg.PlotDataItem, curve: CurveConfig, name: str) -> None:
        item.setPen(pg.mkPen(curve.color, width=curve.width))
        if item.isVisible() != curve.visible:
            item.setVisible(curve.visible)
        if item.name() != name:
            item.opts["name"] = name
            self.legend.removeItem(item)
            self.legend.addItem(item, name)

    def _on_visibility(self, series_id: str) -> None:
        """Legend clicks toggle item visibility; mirror it into the config."""
        item = self.items.get(series_id)
        if item is not None:
            self.owner.set_curve_visible(series_id, item.isVisible())

    def remove_item(self, series_id: str) -> None:
        item = self.items.pop(series_id)
        self.legend.removeItem(item)
        self.plot_item.removeItem(item)

    def contains_scene_point(self, scene_pos: QPointF) -> bool:
        return self.plot_item.sceneBoundingRect().contains(scene_pos)


class PlotWidget(pg.GraphicsLayoutWidget):
    """A graph fed by series ids. Accepts series dropped from the series tree."""

    config_changed = Signal()
    missing_series_changed = Signal(list)
    """Emitted after ``apply_config`` with the ids that could not be resolved."""
    x_range_changed = Signal(float, float)
    """The X range of the graph changed (not emitted for :meth:`set_x_range`)."""
    activated = Signal()
    """The user interacted with this graph (it becomes the current one)."""

    def __init__(
        self, session: Session, config: PlotConfig | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._config = PlotConfig()
        self.subplots: list[SubPlot] = []
        self._applying = False
        self._syncing_x = False
        self.setAcceptDrops(True)
        self.apply_config(config or PlotConfig())

    # -- config ---------------------------------------------------------------------------

    @property
    def config(self) -> PlotConfig:
        return self._config

    def apply_config(self, config: PlotConfig) -> None:
        """Make the display match ``config``."""
        self._config = config
        self._applying = True
        try:
            self._sync_subplot_count(len(config.subplots))
            missing: list[str] = []
            for i, (sub, sub_cfg) in enumerate(zip(self.subplots, config.subplots, strict=True)):
                sub.plot_item.setTitle(config.title or None if i == 0 else None)
                missing += sub.apply(sub_cfg, config)
                self.ci.layout.setRowStretchFactor(i, max(1, round(sub_cfg.ratio * 100)))
            # Only the bottom subplot shows the X tick labels.
            for i, sub in enumerate(self.subplots):
                sub.plot_item.getAxis("bottom").setStyle(showValues=i == len(self.subplots) - 1)
        finally:
            self._applying = False
        if missing:
            log.warning("Missing series in plot: %s", ", ".join(missing))
        self.missing_series_changed.emit(missing)

    def _sync_subplot_count(self, count: int) -> None:
        while len(self.subplots) > count:
            sub = self.subplots.pop()
            for series_id in list(sub.items):
                sub.remove_item(series_id)
            self.ci.removeItem(sub.plot_item)
        while len(self.subplots) < count:
            plot_item = self.ci.addPlot(row=len(self.subplots), col=0)
            sub = SubPlot(self, plot_item)
            if self.subplots:
                plot_item.setXLink(self.subplots[0].plot_item)
            else:
                sub.view_box.sigXRangeChanged.connect(self._on_x_range_changed)
            self.subplots.append(sub)

    def _commit(self) -> None:
        """Apply the (mutated) current config and notify listeners."""
        self.apply_config(self._config)
        self.config_changed.emit()

    def refresh_data(self) -> None:
        for sub, sub_cfg in zip(self.subplots, self._config.subplots, strict=True):
            sub.refresh_data(sub_cfg)
        self.apply_config(self._config)

    # -- subplots -------------------------------------------------------------------------

    def split(self) -> None:
        """Add a subplot at the bottom."""
        self._config.subplots.append(SubplotConfig())
        self._commit()

    def remove_subplot(self, index: int) -> None:
        if len(self._config.subplots) <= 1 or not 0 <= index < len(self._config.subplots):
            return
        del self._config.subplots[index]
        self._commit()

    def subplot_at(self, scene_pos: QPointF) -> int:
        for i, sub in enumerate(self.subplots):
            if sub.contains_scene_point(scene_pos):
                return i
        return 0

    # -- curves ---------------------------------------------------------------------------

    def add_series(self, series_ids: list[str], subplot: int = 0) -> list[str]:
        """Add curves to ``subplot`` (already present ids are skipped). Returns added ids."""
        sub_cfg = self._config.subplots[min(subplot, len(self._config.subplots) - 1)]
        added: list[str] = []
        for series_id in series_ids:
            if sub_cfg.curve(series_id) or self.session.get_series(series_id) is None:
                continue
            color = next_color(c.color for c in self._config.all_curves())
            sub_cfg.curves.append(CurveConfig(series_id=series_id, color=color))
            added.append(series_id)
        if added:
            self._commit()
        return added

    def remove_curve(self, series_id: str, subplot: int) -> None:
        curves = self._config.subplots[subplot].curves
        curves[:] = [c for c in curves if c.series_id != series_id]
        self._commit()

    def set_curve_visible(self, series_id: str, visible: bool) -> None:
        if self._applying:
            return
        changed = False
        for curve in self._config.all_curves():
            if curve.series_id == series_id and curve.visible != visible:
                curve.visible = visible
                changed = True
        if changed:
            self._commit()

    def clear_curves(self) -> None:
        if not self._config.all_curves():
            return
        for sub_cfg in self._config.subplots:
            sub_cfg.curves.clear()
        self._commit()

    def curve_item(self, series_id: str, subplot: int = 0) -> pg.PlotDataItem | None:
        return self.subplots[subplot].items.get(series_id)

    # -- X range --------------------------------------------------------------------------

    def x_range(self) -> tuple[float, float]:
        lo, hi = self.subplots[0].view_box.viewRange()[0]
        return float(lo), float(hi)

    def set_x_range(self, lo: float, hi: float) -> None:
        """Set the X range without emitting :attr:`x_range_changed` (used by sync)."""
        self._syncing_x = True
        try:
            self.subplots[0].view_box.setXRange(lo, hi, padding=0)
        finally:
            self._syncing_x = False

    def auto_range(self) -> None:
        for sub in self.subplots:
            sub.plot_item.enableAutoRange()

    def _on_x_range_changed(self, _vb, rng) -> None:
        if not self._syncing_x:
            self.x_range_changed.emit(float(rng[0]), float(rng[1]))

    # -- events ---------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.activated.emit()
        super().mousePressEvent(event)

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
        scene_pos = self.mapToScene(event.position().toPoint())
        self.activated.emit()
        self.add_series(ids, self.subplot_at(scene_pos))
