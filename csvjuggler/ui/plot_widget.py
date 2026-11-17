"""pyqtgraph wrapper: a graph made of vertically stacked subplots sharing the X axis.

The widget displays what its :class:`PlotConfig` describes. ``apply_config`` updates existing
curve items (``setData``/``setPen``) instead of recreating them, and only touches view ranges
when the range settings themselves changed (so the user's zoom survives style changes).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QWidget

from csvjuggler.data.series import Series
from csvjuggler.model.plot_config import (
    PRIMARY_Y_AXIS_ID,
    X_AXIS_ID,
    AxisConfig,
    CurveConfig,
    PlotConfig,
    SubplotConfig,
)
from csvjuggler.model.session import Session
from csvjuggler.ui.plot_items import DateAxis, FormattedAxis, PlotViewBox
from csvjuggler.ui.series_tree import SERIES_MIME_TYPE, decode_series_ids
from csvjuggler.utils.colors import next_color

log = logging.getLogger(__name__)

PEN_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dash": Qt.PenStyle.DashLine,
    "dot": Qt.PenStyle.DotLine,
}
LEGEND_ANCHORS: dict[str, tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = {
    "top-left": ((0, 0), (0, 0), (10, 10)),
    "top-right": ((1, 0), (1, 0), (-10, 10)),
    "bottom-left": ((0, 1), (0, 1), (10, -10)),
    "bottom-right": ((1, 1), (1, 1), (-10, -10)),
}
CURVE_PICK_DISTANCE_PX = 8.0


def display_data(
    series: Series, curve: CurveConfig, x_series: Series | None
) -> tuple[np.ndarray, np.ndarray]:
    """x/y actually drawn for ``curve``: gain/offset applied, X replaced in XY mode."""
    x = series.x
    if x_series is not None:
        if x_series.x is series.x or np.array_equal(x_series.x, series.x):
            x = x_series.y
        else:
            x = np.interp(series.x, x_series.x, x_series.y, left=np.nan, right=np.nan)
    y = series.y
    if curve.gain != 1.0 or curve.offset != 0.0:
        y = curve.gain * y + curve.offset
    return x, y


def _range_key(cfg: AxisConfig) -> tuple[Any, ...]:
    return (cfg.auto_range, cfg.min, cfg.max, cfg.log, cfg.inverted)


class SubPlot:
    """One PlotItem of the graph, its axes and the curve items it holds."""

    def __init__(self, owner: PlotWidget, row: int) -> None:
        self.owner = owner
        self.view_box = PlotViewBox()
        self.left_axis = FormattedAxis("left", PRIMARY_Y_AXIS_ID)
        self.bottom_axis: FormattedAxis | DateAxis = FormattedAxis("bottom", X_AXIS_ID)
        self.plot_item: pg.PlotItem = owner.ci.addPlot(
            row=row,
            col=0,
            viewBox=self.view_box,
            axisItems={"left": self.left_axis, "bottom": self.bottom_axis},
        )
        self.legend = self.plot_item.addLegend()
        self.items: dict[str, pg.PlotDataItem] = {}
        self._data_keys: dict[str, tuple[Any, ...]] = {}
        self._range_keys: dict[str, tuple[Any, ...]] = {}
        self._keep_axes_under_curves()
        self.view_box.menu_requested.connect(self._on_menu)
        self.view_box.double_clicked.connect(lambda _ev: owner.plot_settings_requested.emit())
        self._connect_axis(self.left_axis)
        self._connect_axis(self.bottom_axis)

    # -- helpers --------------------------------------------------------------------------

    @property
    def index(self) -> int:
        return self.owner.subplots.index(self)

    def config(self) -> SubplotConfig:
        return self.owner.config.subplots[self.index]

    def _keep_axes_under_curves(self) -> None:
        # Axes draw the grid; keep them (and the grid) under the curves.
        for name in ("left", "bottom", "right", "top"):
            self.plot_item.getAxis(name).setZValue(-1000)

    def _connect_axis(self, axis: FormattedAxis | DateAxis) -> None:
        axis.menu_requested.connect(
            lambda axis_id, pos: self.owner.axis_menu_requested.emit(self.index, axis_id, pos)
        )
        axis.double_clicked.connect(
            lambda axis_id: self.owner.axis_settings_requested.emit(self.index, axis_id)
        )

    def _on_menu(self, ev) -> None:
        self.owner.plot_menu_requested.emit(self.index, ev.scenePos(), ev.screenPos())

    def view_for_axis(self, axis_id: str) -> pg.ViewBox:
        return self.view_box

    def axis_item(self, axis_id: str) -> FormattedAxis | DateAxis:
        return self.bottom_axis if axis_id == X_AXIS_ID else self.left_axis

    # -- apply ----------------------------------------------------------------------------

    def apply(self, cfg: SubplotConfig, plot_cfg: PlotConfig, is_last: bool) -> list[str]:
        """Synchronise the subplot with ``cfg``. Returns the ids of unresolved series."""
        self._apply_x_axis(plot_cfg.x_axis, show_values=is_last)
        self._apply_y_axes(cfg)
        self.plot_item.showGrid(
            x=plot_cfg.show_grid_x, y=plot_cfg.show_grid_y, alpha=plot_cfg.grid_alpha
        )
        self._apply_legend(plot_cfg.legend_position)
        return self._apply_curves(cfg, plot_cfg)

    def _apply_x_axis(self, cfg: AxisConfig, show_values: bool) -> None:
        want_date = cfg.x_mode == "absolute"
        if want_date != isinstance(self.bottom_axis, DateAxis):
            axis_cls = DateAxis if want_date else FormattedAxis
            self.bottom_axis = axis_cls("bottom", X_AXIS_ID)
            self.plot_item.setAxisItems({"bottom": self.bottom_axis})
            self.bottom_axis.setZValue(-1000)
            self._connect_axis(self.bottom_axis)
        axis = self.bottom_axis
        axis.setStyle(showValues=show_values)
        axis.set_format(cfg)
        axis.setLogMode(cfg.log and not want_date)
        title = cfg.title if show_values else ""
        axis.setLabel(title)
        axis.showLabel(bool(title))
        self._apply_axis_color(axis, cfg.color)
        key = _range_key(cfg)
        if self._range_keys.get(X_AXIS_ID) != key:
            self._range_keys[X_AXIS_ID] = key
            self.view_box.invertX(cfg.inverted)
            if self.index == 0:
                self._apply_range(self.view_box, pg.ViewBox.XAxis, cfg)

    def _apply_y_axes(self, cfg: SubplotConfig) -> None:
        self._apply_y_axis(self.left_axis, self.view_box, cfg.y_axes[0], None)

    def _apply_y_axis(
        self,
        axis: FormattedAxis,
        view_box: pg.ViewBox,
        cfg: AxisConfig,
        default_color: str | None,
    ) -> None:
        axis.set_format(cfg)
        axis.setLogMode(cfg.log)
        axis.setLabel(cfg.title)
        axis.showLabel(bool(cfg.title))
        self._apply_axis_color(axis, cfg.color or default_color)
        key = _range_key(cfg)
        if self._range_keys.get(cfg.axis_id) != key:
            self._range_keys[cfg.axis_id] = key
            view_box.invertY(cfg.inverted)
            self._apply_range(view_box, pg.ViewBox.YAxis, cfg)

    @staticmethod
    def _apply_axis_color(axis: pg.AxisItem, color: str | None) -> None:
        if color:
            axis.setPen(color)
            axis.setTextPen(color)
        else:
            axis.setPen()
            axis.setTextPen()

    @staticmethod
    def _apply_range(view_box: pg.ViewBox, which: int, cfg: AxisConfig) -> None:
        if cfg.auto_range:
            view_box.enableAutoRange(axis=which, enable=True)
            return
        lo, hi = cfg.min, cfg.max
        if cfg.log:
            lo, hi = (float(np.log10(v)) if v > 0 else -1.0 for v in (lo, hi))
        view_box.disableAutoRange(axis=which)
        if which == pg.ViewBox.XAxis:
            view_box.setXRange(lo, hi, padding=0)
        else:
            view_box.setYRange(lo, hi, padding=0)

    def _apply_legend(self, position: str) -> None:
        if position == "hidden":
            self.legend.setVisible(False)
            return
        self.legend.setVisible(True)
        item_pos, parent_pos, offset = LEGEND_ANCHORS.get(position, LEGEND_ANCHORS["top-left"])
        self.legend.anchor(item_pos, parent_pos, offset)

    def _apply_curves(self, cfg: SubplotConfig, plot_cfg: PlotConfig) -> list[str]:
        session = self.owner.session
        wanted = {c.series_id for c in cfg.curves}
        for series_id in list(self.items):
            if series_id not in wanted:
                self.remove_item(series_id)

        x_cfg = plot_cfg.x_axis
        x_series = (
            session.get_series(x_cfg.x_series_id)
            if x_cfg.x_mode == "series" and x_cfg.x_series_id
            else None
        )
        missing: list[str] = []
        for curve in cfg.curves:
            series = session.get_series(curve.series_id)
            if series is None:
                missing.append(curve.series_id)
                if curve.series_id in self.items:
                    self.remove_item(curve.series_id)
                continue
            axis_cfg = cfg.axis(curve.axis_id) or cfg.y_axes[0]
            item = self.items.get(curve.series_id) or self._create_item(curve, axis_cfg.axis_id)
            self._move_to_view(item, self.view_for_axis(axis_cfg.axis_id))
            data_key = (
                id(series.x),
                id(series.y),
                curve.gain,
                curve.offset,
                curve.mode,
                id(x_series.y) if x_series is not None else None,
            )
            if self._data_keys.get(curve.series_id) != data_key:
                self._data_keys[curve.series_id] = data_key
                x, y = display_data(series, curve, x_series)
                item.setData(x, y, stepMode="left" if curve.mode == "step" else None)
            item.setLogMode(x_cfg.log and x_cfg.x_mode != "absolute", axis_cfg.log)
            self._style_item(item, curve, curve.alias or series.label)
        return missing

    def _create_item(self, curve: CurveConfig, axis_id: str) -> pg.PlotDataItem:
        item = pg.PlotDataItem(name=curve.series_id, pen=pg.mkPen(curve.color))
        self.view_for_axis(axis_id).addItem(item)
        self.legend.addItem(item, curve.series_id)
        # Set after the item is in a ViewBox: with clipToView enabled before, pyqtgraph 0.14
        # queries the QGraphicsView instead of the ViewBox and fails.
        item.setDownsampling(auto=True, method="peak")
        item.setClipToView(True)
        item.visibleChanged.connect(lambda sid=curve.series_id: self._on_visibility(sid))
        self.items[curve.series_id] = item
        return item

    @staticmethod
    def _move_to_view(item: pg.PlotDataItem, view_box: pg.ViewBox) -> None:
        current = item.getViewBox()
        if current is not view_box:
            if current is not None:
                current.removeItem(item)
            view_box.addItem(item)

    def _style_item(self, item: pg.PlotDataItem, curve: CurveConfig, name: str) -> None:
        marker = None if curve.marker == "none" else curve.marker
        if curve.mode == "points":
            item.setPen(None)
            marker = marker or "o"
        else:
            item.setPen(pg.mkPen(curve.color, width=curve.width, style=PEN_STYLES[curve.style]))
        item.setSymbol(marker)
        if marker is not None:
            item.setSymbolSize(curve.marker_size)
            item.setSymbolBrush(curve.color)
            item.setSymbolPen(curve.color)
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
        self._data_keys.pop(series_id, None)
        self.legend.removeItem(item)
        view_box = item.getViewBox()
        if view_box is not None:
            view_box.removeItem(item)

    def clear(self) -> None:
        for series_id in list(self.items):
            self.remove_item(series_id)
        self._range_keys.clear()

    # -- picking --------------------------------------------------------------------------

    def contains_scene_point(self, scene_pos: QPointF) -> bool:
        return self.plot_item.sceneBoundingRect().contains(scene_pos)

    def curve_near(self, scene_pos: QPointF, max_px: float = CURVE_PICK_DISTANCE_PX) -> str | None:
        """Id of the visible curve closest (vertically) to ``scene_pos``, if close enough."""
        best: tuple[float, str] | None = None
        for series_id, item in self.items.items():
            if not item.isVisible():
                continue
            x, y = item.getData()
            if x is None or len(x) == 0:
                continue
            view_box = item.getViewBox()
            point = view_box.mapSceneToView(scene_pos)
            order = np.argsort(x) if np.any(np.diff(x) < 0) else slice(None)
            y_at = np.interp(point.x(), x[order], y[order], left=np.nan, right=np.nan)
            if not np.isfinite(y_at):
                continue
            scene_y = view_box.mapViewToScene(QPointF(point.x(), float(y_at))).y()
            dist = abs(scene_y - scene_pos.y())
            if dist <= max_px and (best is None or dist < best[0]):
                best = (dist, series_id)
        return best[1] if best else None


class PlotWidget(pg.GraphicsLayoutWidget):
    """A graph fed by series ids. Accepts series dropped from the series tree."""

    config_changed = Signal()
    missing_series_changed = Signal(list)
    """Emitted after ``apply_config`` with the ids that could not be resolved."""
    x_range_changed = Signal(float, float)
    """The X range of the graph changed (not emitted for :meth:`set_x_range`)."""
    activated = Signal()
    """The user interacted with this graph (it becomes the current one)."""
    plot_menu_requested = Signal(int, QPointF, QPointF)
    """Right click in a subplot: ``(subplot, scene pos, screen pos)``."""
    axis_menu_requested = Signal(int, str, QPointF)
    """Right click on an axis: ``(subplot, axis id, screen pos)``."""
    plot_settings_requested = Signal()
    axis_settings_requested = Signal(int, str)

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
            self.setBackground(config.background)
            self._sync_subplot_count(len(config.subplots))
            missing: list[str] = []
            last = len(self.subplots) - 1
            for i, (sub, sub_cfg) in enumerate(zip(self.subplots, config.subplots, strict=True)):
                title = config.title if (i == 0 and config.show_title and config.title) else None
                sub.plot_item.setTitle(title, size=f"{config.title_size}pt")
                missing += sub.apply(sub_cfg, config, is_last=i == last)
                self.ci.layout.setRowStretchFactor(i, max(1, round(sub_cfg.ratio * 100)))
        finally:
            self._applying = False
        if missing:
            log.warning("Missing series in plot: %s", ", ".join(missing))
        self.missing_series_changed.emit(missing)

    def update_config(self, config: PlotConfig) -> None:
        """Replace the whole configuration (dialogs) and notify."""
        self._config = config
        self._commit()

    def _sync_subplot_count(self, count: int) -> None:
        while len(self.subplots) > count:
            sub = self.subplots.pop()
            sub.clear()
            self.ci.removeItem(sub.plot_item)
        while len(self.subplots) < count:
            sub = SubPlot(self, len(self.subplots))
            if self.subplots:
                sub.plot_item.setXLink(self.subplots[0].plot_item)
            else:
                sub.view_box.sigXRangeChanged.connect(self._on_x_range_changed)
            self.subplots.append(sub)

    def _commit(self) -> None:
        """Apply the (mutated) current config and notify listeners."""
        self.apply_config(self._config)
        self.config_changed.emit()

    def refresh_data(self) -> None:
        """Series objects were replaced (reload): data keys change, items get ``setData``."""
        self.apply_config(self._config)

    def config_copy(self) -> PlotConfig:
        return copy.deepcopy(self._config)

    # -- subplots -------------------------------------------------------------------------

    def split(self) -> None:
        """Add a subplot at the bottom."""
        self._config.subplots.append(SubplotConfig())
        self._commit()

    def remove_subplot(self, index: int) -> None:
        if len(self._config.subplots) <= 1 or not 0 <= index < len(self._config.subplots):
            return
        del self._config.subplots[index]
        # Subplots below the removed one shift up: their items are rebuilt.
        for sub in self.subplots[index:]:
            sub.clear()
        self._commit()

    def subplot_at(self, scene_pos: QPointF) -> int:
        for i, sub in enumerate(self.subplots):
            if sub.contains_scene_point(scene_pos):
                return i
        return 0

    # -- axes -----------------------------------------------------------------------------

    def axis_config(self, subplot: int, axis_id: str) -> AxisConfig | None:
        if axis_id == X_AXIS_ID:
            return self._config.x_axis
        return self._config.subplots[subplot].axis(axis_id)

    def set_axis_config(self, subplot: int, axis: AxisConfig) -> None:
        if axis.axis_id == X_AXIS_ID:
            self._config.x_axis = axis
        else:
            axes = self._config.subplots[subplot].y_axes
            for i, existing in enumerate(axes):
                if existing.axis_id == axis.axis_id:
                    axes[i] = axis
        self._commit()

    def data_range(self, subplot: int, axis_id: str) -> tuple[float, float] | None:
        """Bounds of the data shown on an axis (in data units, even for log axes)."""
        cfg = self.axis_config(subplot, axis_id)
        is_x = axis_id == X_AXIS_ID
        subs = self.subplots if is_x else [self.subplots[subplot]]
        bounds: list[tuple[float, float]] = []
        for sub in subs:
            view_box = sub.view_for_axis(axis_id)
            rng = view_box.childrenBounds()[0 if is_x else 1]
            if rng is not None:
                bounds.append((float(rng[0]), float(rng[1])))
        if not bounds:
            return None
        lo, hi = min(b[0] for b in bounds), max(b[1] for b in bounds)
        if cfg is not None and cfg.log:
            lo, hi = 10.0**lo, 10.0**hi
        return lo, hi

    def auto_range_once(self, subplot: int, axis_id: str) -> None:
        """Fit the axis to the data once, then keep that range as a manual range."""
        cfg = self.axis_config(subplot, axis_id)
        if cfg is None:
            return
        is_x = axis_id == X_AXIS_ID
        sub = self.subplots[0 if is_x else subplot]
        view_box = sub.view_for_axis(axis_id)
        which = pg.ViewBox.XAxis if is_x else pg.ViewBox.YAxis
        view_box.enableAutoRange(axis=which, enable=True)
        view_box.updateAutoRange()
        lo, hi = view_box.viewRange()[0 if is_x else 1]
        if cfg.log:
            lo, hi = 10.0**lo, 10.0**hi
        cfg.auto_range, cfg.min, cfg.max = False, float(lo), float(hi)
        self._commit()

    def set_sync_group(self, group: str) -> None:
        if group != self._config.sync_group:
            self._config.sync_group = group
            self._commit()

    # -- curves ---------------------------------------------------------------------------

    def add_series(self, series_ids: list[str], subplot: int = 0) -> list[str]:
        """Add curves to ``subplot`` (already present ids are skipped). Returns added ids."""
        sub_cfg = self._config.subplots[min(subplot, len(self._config.subplots) - 1)]
        added: list[str] = []
        for series_id in series_ids:
            if sub_cfg.curve(series_id) or self.session.get_series(series_id) is None:
                continue
            color = next_color(c.color for c in self._config.all_curves())
            curve = CurveConfig(series_id=series_id, color=color, axis_id=sub_cfg.y_axes[0].axis_id)
            sub_cfg.curves.append(curve)
            added.append(series_id)
        if added:
            self._commit()
        return added

    def curve_config(self, subplot: int, series_id: str) -> CurveConfig | None:
        return self._config.subplots[subplot].curve(series_id)

    def set_curve_config(self, subplot: int, curve: CurveConfig) -> None:
        curves = self._config.subplots[subplot].curves
        for i, existing in enumerate(curves):
            if existing.series_id == curve.series_id:
                curves[i] = curve
        self._commit()

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

    def series_label(self, curve: CurveConfig) -> str:
        series = self.session.get_series(curve.series_id)
        return curve.alias or (series.label if series else curve.series_id)

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
