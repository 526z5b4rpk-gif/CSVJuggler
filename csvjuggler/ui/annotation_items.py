"""Graphic items of annotations, their per-graph layer and the session-wide manager.

- :class:`AnnotationManager` decides where each annotation is shown (its graph/subplot,
  every graph of the sync group for linked vertical lines, or — when its graph does not
  exist, e.g. after opening a companion file — every graph showing its dataset).
- :class:`AnnotationLayer` (one per graph) owns the pyqtgraph items and reports user
  interaction (move, double-click, right click, selection) through an :class:`AnnotationHub`.
- Items are rebuilt when their annotation changes; the store is the single source of truth.
"""

from __future__ import annotations

import contextlib
import copy
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QMenu, QWidget

from csvjuggler.data.analysis import format_number
from csvjuggler.i18n import Msg, tr
from csvjuggler.model.annotation import Annotation, AnnotationKind
from csvjuggler.model.plot_config import CurveConfig
from csvjuggler.model.session import Session
from csvjuggler.ui.cursors import curve_value
from csvjuggler.ui.plot_widget import PlotWidget

log = logging.getLogger(__name__)

PlotsProvider = Callable[[], list[tuple[str, PlotWidget]]]
"""Returns ``(dock_id, plot)`` for every open graph."""
REGION_FILL_ALPHA = 60
ANNOTATION_Z = 50


class AnnotationHub(QObject):
    moved = Signal(str, float, float, float)
    """``(id, x, y, x2)`` after a drag."""
    edit_requested = Signal(str)
    menu_requested = Signal(str, QPointF)
    selected = Signal(str)
    delete_requested = Signal(str)
    offset_changed = Signal(str, float, float)
    """Bubble ``(id, dx, dy)``: new position of the bubble relative to its point (pixels)."""


def _font(ann: Annotation) -> QFont:
    font = QFont()
    font.setPointSize(ann.font_size)
    return font


def _fill(ann: Annotation) -> pg.QtGui.QBrush | None:
    return pg.mkBrush(ann.text_background) if ann.text_background else None


def _handle_click(item: pg.GraphicsObject, ann: Annotation, hub: AnnotationHub, ev) -> bool:
    """Common click behaviour. Returns True when the event was consumed."""
    if ev.button() == Qt.MouseButton.RightButton:
        ev.accept()
        hub.selected.emit(ann.id)
        hub.menu_requested.emit(ann.id, ev.screenPos())
        return True
    if ev.button() == Qt.MouseButton.LeftButton:
        hub.selected.emit(ann.id)
        if ev.double():
            ev.accept()
            hub.edit_requested.emit(ann.id)
            return True
    return False


CoordsFormatter = Callable[[float, float], str]
"""Text of the anchor point coordinates, ``(x, y)`` → e.g. ``"x = 5.2 s   y = 1500 rpm"``."""


def _text_size(font: QFont, text: str) -> QSizeF:
    """Size of a (multi-line) text, rounded up so that nothing gets clipped."""
    if not text:
        return QSizeF(0.0, 0.0)
    metrics = QFontMetricsF(font)
    lines = text.split("\n")
    width = max(metrics.horizontalAdvance(line) for line in lines)
    return QSizeF(math.ceil(width) + 2.0, math.ceil(metrics.lineSpacing() * len(lines)))


class TextAnnotationItem(pg.GraphicsObject):
    """Text in a rounded bubble anchored at (x, y), draggable unless locked.

    With ``ann.arrow`` the bubble sits above-right of the point and a tail points to it
    (a small dot marks the point); otherwise the bubble's bottom-left corner is the point.
    :class:`BubbleAnnotationItem` attaches the point to a curve.
    With ``ann.show_coords`` a last line shows the point coordinates (updated while dragging).
    Pixel-sized: the item cancels the view scale with its own transform (as ``pg.TextItem``).
    """

    PADDING = (8.0, 5.0)
    RADIUS = 6.0
    TAIL_OFFSET = QPointF(14.0, -22.0)
    """Bubble bottom-left corner relative to the point, when it has a tail."""
    TAIL_HALF_WIDTH = 6.0
    """Half width of the tail where it leaves the bubble."""
    POINT_RADIUS = 3.0
    POINT_PICK_RADIUS = 8.0
    """Clicking that close to the point grabs the point (bubble: slides along the curve)."""
    SHADOW = QPointF(2.0, 2.0)
    LINE_GAP = 2.0

    def __init__(
        self, ann: Annotation, hub: AnnotationHub, coords: CoordsFormatter | None = None
    ) -> None:
        super().__init__()
        self.ann, self.hub = ann, hub
        self.coords = coords
        self._last_transform: QTransform | None = None
        self.offset = self._initial_offset()
        """Bubble bottom-left corner relative to the point (pixels), None = no tail."""
        x, y = self._initial_point()
        self.setPos(x, y)
        self.setOpacity(ann.opacity)
        self.font = _font(ann)
        self.coords_font = QFont(self.font)
        self.coords_font.setPointSize(max(5, ann.font_size - 1))
        self._drag_offset = QPointF()
        self._layout(x, y)

    def _initial_offset(self) -> QPointF | None:
        return QPointF(self.TAIL_OFFSET) if self.ann.arrow else None

    def _initial_point(self) -> tuple[float, float]:
        return self.ann.x, self.ann.y

    def coords_text(self, x: float, y: float) -> str:
        if not self.ann.show_coords or self.coords is None:
            return ""
        return self.coords(x, y)

    def _layout(self, x: float, y: float) -> None:
        """Compute the bubble geometry for the texts shown with the point at (x, y)."""
        self.prepareGeometryChange()
        self.text = self.ann.text
        self.coords_line = self.coords_text(x, y)
        if not self.text and not self.coords_line:
            self.text = " "
        text_size = _text_size(self.font, self.text)
        coords_size = _text_size(self.coords_font, self.coords_line)
        gap = self.LINE_GAP if self.text and self.coords_line else 0.0
        pad_x, pad_y = self.PADDING
        width = max(text_size.width(), coords_size.width()) + 2 * pad_x
        height = text_size.height() + gap + coords_size.height() + 2 * pad_y
        origin = self.offset if self.offset is not None else QPointF(0.0, 0.0)
        self.box = QRectF(origin.x(), origin.y() - height, width, height)
        left, top = self.box.left() + pad_x, self.box.top() + pad_y
        self.text_rect = QRectF(left, top, text_size.width(), text_size.height())
        self.coords_rect = QRectF(
            left, top + text_size.height() + gap, coords_size.width(), coords_size.height()
        )
        path = QPainterPath()
        path.addRoundedRect(self.box, self.RADIUS, self.RADIUS)
        if self.offset is not None:
            # Triangle from the point to the bubble centre: the union with the box keeps
            # only the part outside it, whatever side of the point the bubble is on.
            center = self.box.center()
            length = math.hypot(center.x(), center.y()) or 1.0
            normal = QPointF(-center.y() / length, center.x() / length) * self.TAIL_HALF_WIDTH
            tail = QPainterPath(QPointF(0.0, 0.0))
            tail.lineTo(center + normal)
            tail.lineTo(center - normal)
            tail.closeSubpath()
            path = path.united(tail)
        self.path = path.simplified()
        self.hit_path = self.path
        if self.offset is not None:
            # united (not addEllipse): with the odd-even fill rule an overlap becomes a hole
            point = QPainterPath()
            point.addEllipse(QPointF(0.0, 0.0), self.POINT_PICK_RADIUS, self.POINT_PICK_RADIUS)
            self.hit_path = self.path.united(point)
        self._bounds = self.hit_path.boundingRect().adjusted(
            -3, -3, 3 + self.SHADOW.x(), 3 + self.SHADOW.y()
        )
        self.update()

    def _update_transform(self) -> None:
        """Cancel the view scale (pixel-sized bubble) while keeping hit-testing working.

        Same technique as ``pg.TextItem``: ``ItemIgnoresTransformations`` would break
        pyqtgraph's mouse interaction (the item is never found under the cursor).
        """
        parent = self.parentItem()
        pt = parent.sceneTransform() if parent is not None else QTransform()
        if pt == self._last_transform:
            return
        self._last_transform = pt
        inv, _ok = pt.inverted()
        self.setTransform(
            QTransform(inv.m11(), inv.m12(), inv.m13(), inv.m21(), inv.m22(), inv.m23(), 0, 0, 1)
        )

    def viewTransformChanged(self) -> None:
        self._update_transform()

    def itemChange(self, change, value):
        if change == self.GraphicsItemChange.ItemParentHasChanged:
            self._last_transform = None
            self._update_transform()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        return self.hit_path

    def paint(self, painter: QPainter, *_args: object) -> None:
        self._update_transform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.ann.color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawPath(self.path.translated(self.SHADOW))
        background = QColor(self.ann.text_background or "#ffffff")
        if not self.ann.text_background:
            background.setAlpha(0)
        painter.setBrush(background)
        painter.setPen(QPen(color, 1.5))
        painter.drawPath(self.path)
        if self.offset is not None:
            painter.setBrush(color)
            painter.setPen(QPen(QColor("#ffffff"), 1.0))
            painter.drawEllipse(QPointF(0.0, 0.0), self.POINT_RADIUS + 0.5, self.POINT_RADIUS + 0.5)
        flags = int(Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextDontClip)
        painter.setPen(color)
        if self.text:
            painter.setFont(self.font)
            painter.drawText(self.text_rect, flags, self.text)
        if self.coords_line:
            painter.setFont(self.coords_font)
            painter.setPen(QColor(90, 90, 90))
            painter.drawText(self.coords_rect, flags, self.coords_line)

    def mouseDragEvent(self, ev) -> None:
        if self.ann.locked or ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        parent = self.parentItem()
        point = parent.mapFromScene(ev.scenePos())
        if ev.isStart():
            self._drag_offset = self.pos() - parent.mapFromScene(ev.buttonDownScenePos())
            self.hub.selected.emit(self.ann.id)
        pos = point + self._drag_offset
        self.setPos(pos)
        if self.coords_line:
            self._layout(pos.x(), pos.y())
        if ev.isFinish():
            self.hub.moved.emit(self.ann.id, pos.x(), pos.y(), self.ann.x2)

    def mouseClickEvent(self, ev) -> None:
        if not _handle_click(self, self.ann, self.hub, ev):
            ev.accept()


class BubbleAnnotationItem(TextAnnotationItem):
    """Bubble whose point is attached to a curve: y = displayed curve value at x.

    Dragging the bubble moves it around its point (the tail follows); dragging the point
    slides it along the curve.

    The item always lives in the main view of its subplot (secondary views are stacked
    below the plot, so the grid and the other curves would be drawn over it). For a curve
    on a secondary axis, :meth:`attach` gives the curve's view: the point's y is converted
    from that view and re-placed whenever either view changes.
    """

    def __init__(
        self,
        ann: Annotation,
        hub: AnnotationHub,
        coords: CoordsFormatter | None,
        anchor_y: Callable[[float], float],
    ) -> None:
        self.anchor_y = anchor_y
        super().__init__(ann, hub, coords)
        self.data_view: pg.ViewBox | None = None
        self.curve_visible = True
        self.point = (ann.x, self.pos().y())
        """The point in the curve's data coordinates."""
        self.setVisible(math.isfinite(self.point[1]))
        self._sliding = False
        self._press_local = QPointF()
        self._press_offset = QPointF()

    def attach(self, data_view: pg.ViewBox | None, curve_visible: bool = True) -> None:
        """Call once added to its (main) view. ``data_view``: view of a secondary axis."""
        self.curve_visible = curve_visible
        if data_view is not None and data_view is not self.getViewBox():
            self.data_view = data_view
            data_view.sigRangeChanged.connect(self._replace)
            data_view.sigResized.connect(self._replace)
            host = self.getViewBox()
            if host is not None:
                host.sigRangeChanged.connect(self._replace)
                host.sigResized.connect(self._replace)
        self._place(*self.point)

    def detach(self) -> None:
        if self.data_view is None:
            return
        for view in (self.data_view, self.getViewBox()):
            if view is None:
                continue
            for signal in (view.sigRangeChanged, view.sigResized):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(self._replace)
        self.data_view = None

    def _replace(self, *_args: object) -> None:
        self._place(*self.point)

    def _place(self, x: float, y: float) -> None:
        """Put the point at data (x, y) of the curve's view."""
        self.point = (x, y)
        host = self.getViewBox()
        visible = math.isfinite(y) and self.curve_visible
        if visible and self.data_view is not None and host is not None:
            pos = host.mapSceneToView(self.data_view.mapViewToScene(QPointF(x, y)))
        else:
            pos = QPointF(x, y)
        if visible:
            self.setPos(pos)
        self.setVisible(visible)

    def _initial_offset(self) -> QPointF | None:
        return QPointF(self.ann.offset_x, self.ann.offset_y)

    def _initial_point(self) -> tuple[float, float]:
        return self.ann.x, self.anchor_y(self.ann.x)

    def mouseDragEvent(self, ev) -> None:
        if self.ann.locked or ev.button() != Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        self._update_transform()  # pixel coordinates must match the current view
        if ev.isStart():
            self._press_local = self.mapFromScene(ev.buttonDownScenePos())
            self._sliding = math.hypot(self._press_local.x(), self._press_local.y()) <= (
                self.POINT_PICK_RADIUS
            )
            self._press_offset = QPointF(self.offset or QPointF())
            self.hub.selected.emit(self.ann.id)
        if self._sliding:
            x = self.parentItem().mapFromScene(ev.scenePos()).x()  # X is shared by all views
            y = self.anchor_y(x)
            if math.isfinite(y):
                self._place(x, y)
                self._layout(x, y)
            if ev.isFinish():
                self.hub.moved.emit(self.ann.id, self.point[0], self.point[1], self.ann.x2)
            return
        self.offset = self._press_offset + (self.mapFromScene(ev.scenePos()) - self._press_local)
        self._layout(*self.point)
        if ev.isFinish():
            self.hub.offset_changed.emit(self.ann.id, self.offset.x(), self.offset.y())


class LineAnnotationItem(pg.InfiniteLine):
    """Vertical (event) or horizontal (threshold) line with a label."""

    def __init__(self, ann: Annotation, hub: AnnotationHub) -> None:
        vertical = ann.kind == "vline"
        color = QColor(ann.color)
        super().__init__(
            pos=ann.x if vertical else ann.y,
            angle=90 if vertical else 0,
            movable=not ann.locked,
            pen=pg.mkPen(color, width=1.5),
            hoverPen=pg.mkPen(color, width=3),
            label=ann.text or None,
            labelOpts={
                "position": 0.95 if vertical else 0.05,
                "color": ann.color,
                "fill": _fill(ann),
                "movable": True,
                "anchors": [(0, 0), (0, 0)] if vertical else [(0, 1), (0, 1)],
            },
        )
        self.ann, self.hub = ann, hub
        self.setOpacity(ann.opacity)
        label = getattr(self, "label", None)  # only defined when a label text is given
        if label is not None:
            label.setFont(_font(ann))
        self.sigPositionChangeFinished.connect(self._on_moved)

    def _on_moved(self) -> None:
        value = float(self.value())
        if self.ann.kind == "vline":
            self.hub.moved.emit(self.ann.id, value, self.ann.y, self.ann.x2)
        else:
            self.hub.moved.emit(self.ann.id, self.ann.x, value, self.ann.x2)

    def mouseClickEvent(self, ev) -> None:
        if not _handle_click(self, self.ann, self.hub, ev):
            super().mouseClickEvent(ev)


class RegionAnnotationItem(pg.LinearRegionItem):
    """Semi-transparent X region with a label."""

    def __init__(self, ann: Annotation, hub: AnnotationHub) -> None:
        color = QColor(ann.color)
        fill = QColor(color)
        fill.setAlpha(REGION_FILL_ALPHA)
        hover = QColor(color)
        hover.setAlpha(REGION_FILL_ALPHA + 40)
        super().__init__(
            values=(min(ann.x, ann.x2), max(ann.x, ann.x2)),
            orientation="vertical",
            brush=pg.mkBrush(fill),
            hoverBrush=pg.mkBrush(hover),
            pen=pg.mkPen(color),
            movable=not ann.locked,
        )
        self.ann, self.hub = ann, hub
        self.setOpacity(ann.opacity)
        self.label = pg.InfLineLabel(
            self.lines[0],
            text=ann.text,
            position=0.95,
            anchors=[(0, 0), (0, 0)],
            color=ann.color,
            fill=_fill(ann),
        )
        self.label.setFont(_font(ann))
        self.sigRegionChangeFinished.connect(self._on_moved)

    def _on_moved(self) -> None:
        lo, hi = self.getRegion()
        self.hub.moved.emit(self.ann.id, float(lo), self.ann.y, float(hi))

    def mouseClickEvent(self, ev) -> None:
        if not _handle_click(self, self.ann, self.hub, ev):
            super().mouseClickEvent(ev)


ITEM_CLASSES: dict[str, type] = {
    "text": TextAnnotationItem,
    "vline": LineAnnotationItem,
    "hline": LineAnnotationItem,
    "region": RegionAnnotationItem,
}


def _axis_unit(plot: PlotWidget, subplot: int, axis_id: str) -> str:
    """Unit of a Y axis: its configured unit, else the unit of its first curve's series."""
    axis = plot.axis_config(subplot, axis_id)
    if axis is not None and axis.unit:
        return axis.unit
    for curve in plot.config.subplots[subplot].curves:
        if curve.axis_id == axis_id:
            series = plot.session.get_series(curve.series_id)
            if series is not None and series.unit:
                return series.unit
    return ""


def _curve_y(plot: PlotWidget, curve: CurveConfig, x: float) -> float:
    """Displayed value of ``curve`` at ``x`` (NaN outside its data)."""
    series = plot.session.get_series(curve.series_id)
    if series is None or len(series.x) == 0:
        return math.nan
    lo, hi = float(np.nanmin(series.x)), float(np.nanmax(series.x))
    if not lo <= x <= hi:
        return math.nan
    return curve_value(plot, curve, x, "linear")


def _coords_text(
    plot: PlotWidget, subplot: int, axis_id: str, x: float, y: float, series_id: str = ""
) -> str:
    """``x = … s   y = … rpm`` for a point of ``subplot`` (date/time when X is absolute)."""
    x_cfg = plot.config.x_axis
    if x_cfg.x_mode == "absolute" and math.isfinite(x):
        stamp = datetime.fromtimestamp(x, tz=UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        x_text = f"x = {stamp}"
    else:
        x_unit = x_cfg.unit
        if not x_unit and x_cfg.x_mode == "series" and x_cfg.x_series_id:
            series = plot.session.get_series(x_cfg.x_series_id)
            x_unit = series.unit if series is not None else ""
        elif not x_unit and x_cfg.x_mode == "relative":
            x_unit = "s"
        x_text = f"x = {format_number(x)}" + (f" {x_unit}" if x_unit else "")
    series = plot.session.get_series(series_id) if series_id else None
    y_unit = (
        series.unit if series is not None and series.unit else _axis_unit(plot, subplot, axis_id)
    )
    y_text = f"y = {format_number(y)}" + (f" {y_unit}" if y_unit else "")
    return f"{x_text}   {y_text}"


class AnnotationLayer:
    """Annotation items of one graph."""

    def __init__(self, plot: PlotWidget, hub: AnnotationHub) -> None:
        self.plot = plot
        self.hub = hub
        self._shown: dict[tuple[str, int], tuple[Annotation, object, list[pg.GraphicsObject]]] = {}
        """``(id, subplot)`` → (annotation shown, its context, items)."""
        self.selected_id: str | None = None
        hub.selected.connect(self._on_selected)

    def _on_selected(self, ann_id: str) -> None:
        self.selected_id = ann_id
        self.plot.setFocus()

    def delete_selected(self) -> bool:
        if self.selected_id is None:
            return False
        ann_id, self.selected_id = self.selected_id, None
        self.hub.delete_requested.emit(ann_id)
        return True

    def items_for(self, ann_id: str) -> list[pg.GraphicsObject]:
        return [
            i for (aid, _), (_, _ctx, items) in self._shown.items() if aid == ann_id for i in items
        ]

    def _context(self, ann: Annotation, subplot: int) -> object:
        """What else a shown item depends on: for a bubble, its curve (style, gain, data)."""
        if ann.kind != "bubble":
            return None
        curve = self.plot.config.subplots[subplot].curve(ann.series_id)
        series = self.plot.session.get_series(ann.series_id)
        x_cfg = self.plot.config.x_axis
        return (
            copy.deepcopy(curve),
            id(series),
            x_cfg.x_mode,
            x_cfg.x_series_id,
            x_cfg.unit,
        )

    def sync(self, placements: list[tuple[Annotation, int]]) -> None:
        wanted = {(a.id, sub): a for a, sub in placements if sub < len(self.plot.subplots)}
        for key in list(self._shown):
            shown, context, _items = self._shown[key]
            if (
                key not in wanted
                or wanted[key] != shown
                or self._context(wanted[key], key[1]) != context
            ):
                self._remove(key)
        for key, ann in wanted.items():
            if key not in self._shown:
                self._create(ann, key[1])
        if self.selected_id is not None and not any(k[0] == self.selected_id for k in wanted):
            self.selected_id = None

    def _create(self, ann: Annotation, subplot: int) -> None:
        sub = self.plot.subplots[subplot]
        view = sub.view_for_axis(ann.axis_id) if ann.kind in ("text", "hline") else sub.view_box
        item: pg.GraphicsObject
        if ann.kind == "text":
            item = TextAnnotationItem(
                ann, self.hub, partial(_coords_text, self.plot, subplot, ann.axis_id)
            )
        elif ann.kind == "bubble":
            curve = self.plot.config.subplots[subplot].curve(ann.series_id)
            if curve is None:
                return
            data_view = sub.view_for_axis(curve.axis_id)
            item = BubbleAnnotationItem(
                ann,
                self.hub,
                partial(_coords_text, self.plot, subplot, curve.axis_id, series_id=curve.series_id),
                partial(_curve_y, self.plot, curve),
            )
            item.setZValue(ANNOTATION_Z)
            sub.view_box.addItem(item, ignoreBounds=True)
            item.attach(data_view, curve.visible)
            self._shown[(ann.id, subplot)] = (
                copy.deepcopy(ann),
                self._context(ann, subplot),
                [item],
            )
            return
        else:
            item = ITEM_CLASSES[ann.kind](ann, self.hub)
        items: list[pg.GraphicsObject] = [item]
        for it in items:
            it.setZValue(ANNOTATION_Z)
            view.addItem(it, ignoreBounds=True)
        self._shown[(ann.id, subplot)] = (copy.deepcopy(ann), self._context(ann, subplot), items)

    def _remove(self, key: tuple[str, int]) -> None:
        _ann, _context, items = self._shown.pop(key)
        for it in items:
            if isinstance(it, BubbleAnnotationItem):
                it.detach()
            view = it.getViewBox()
            if view is not None:
                view.removeItem(it)
            elif it.scene() is not None:
                it.scene().removeItem(it)

    def clear(self) -> None:
        for key in list(self._shown):
            self._remove(key)


class AnnotationManager(QObject):
    """Places annotations on graphs and turns user interaction into store updates."""

    focus_requested = Signal(str)
    """A dock (id) should be raised to show an annotation."""

    def __init__(
        self,
        session: Session,
        plots: PlotsProvider,
        parent: QObject | None = None,
        edit_dialog: Callable[[Annotation, QWidget | None], Annotation | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.store = session.annotations
        self._plots = plots
        self._layers: dict[int, AnnotationLayer] = {}
        self._edit_dialog = edit_dialog
        self.store.annotations_changed.connect(self.refresh)
        session.series_data_changed.connect(self.refresh)  # bubbles follow their curve

    # -- graphs ---------------------------------------------------------------------------

    def register_plot(self, plot: PlotWidget) -> AnnotationLayer:
        hub = AnnotationHub(plot)
        layer = AnnotationLayer(plot, hub)
        self._layers[id(plot)] = layer
        plot.annotation_layer = layer
        # Queued: these slots change the store, which rebuilds (deletes) the item whose
        # mouse handler emitted the signal. Deleting an item inside its own event handler
        # crashes Qt (« shared QObject was deleted directly »), so wait for it to return.
        queued = Qt.ConnectionType.QueuedConnection
        hub.moved.connect(self.move, queued)
        hub.edit_requested.connect(self.edit, queued)
        hub.menu_requested.connect(self._show_menu, queued)
        hub.delete_requested.connect(self.delete, queued)
        hub.offset_changed.connect(self.set_offset, queued)
        plot.config_changed.connect(self.refresh)
        self.refresh()
        return layer

    def unregister_plot(self, plot: PlotWidget) -> None:
        layer = self._layers.pop(id(plot), None)
        if layer is not None:
            layer.clear()
        self.refresh()

    def layer(self, plot: PlotWidget) -> AnnotationLayer | None:
        return self._layers.get(id(plot))

    # -- placement ------------------------------------------------------------------------

    def targets(self, ann: Annotation) -> list[tuple[str, int]]:
        plots = dict(self._plots())
        owner = plots.get(ann.plot_id)
        if ann.kind == "vline" and ann.link_all and owner is not None:
            group = owner.config.sync_group
            linked = [
                (dock_id, i)
                for dock_id, plot in plots.items()
                if plot is owner or (group and plot.config.sync_group == group)
                for i in range(len(plot.subplots))
            ]
            if linked:
                return linked
        if ann.kind == "bubble":
            return self._bubble_targets(ann, owner)
        if owner is not None and ann.subplot < len(owner.subplots):
            return [(ann.plot_id, ann.subplot)]
        prefix = ann.dataset_alias + "/"
        out: list[tuple[str, int]] = []
        for dock_id, plot in plots.items():
            for i, sub in enumerate(plot.config.subplots):
                if any(c.series_id.startswith(prefix) for c in sub.curves):
                    out.append((dock_id, i))
                    break
        return out

    def _bubble_targets(self, ann: Annotation, owner: PlotWidget | None) -> list[tuple[str, int]]:
        """Its subplot if it still shows the curve, else every graph showing the curve."""
        if (
            owner is not None
            and ann.subplot < len(owner.config.subplots)
            and owner.config.subplots[ann.subplot].curve(ann.series_id) is not None
        ):
            return [(ann.plot_id, ann.subplot)]
        out: list[tuple[str, int]] = []
        for dock_id, plot in self._plots():
            for i, sub in enumerate(plot.config.subplots):
                if sub.curve(ann.series_id) is not None:
                    out.append((dock_id, i))
                    break
        return out

    def refresh(self, *_args: object) -> None:
        by_dock: dict[str, list[tuple[Annotation, int]]] = {}
        for ann in self.store.all():
            for dock_id, subplot in self.targets(ann):
                by_dock.setdefault(dock_id, []).append((ann, subplot))
        for dock_id, plot in self._plots():
            layer = self._layers.get(id(plot))
            if layer is not None:
                layer.sync(by_dock.get(dock_id, []))

    # -- operations -----------------------------------------------------------------------

    def dataset_for(self, plot: PlotWidget, subplot: int) -> tuple[str, str]:
        """``(alias, path)`` of the dataset an annotation created there belongs to."""
        curves = plot.config.subplots[subplot].curves or plot.config.all_curves()
        alias = curves[0].series_id.split("/", 1)[0] if curves else ""
        if not alias and self.session.datasets:
            alias = self.session.datasets[0].alias
        dataset = self.session.dataset(alias)
        path = str(dataset.path) if dataset is not None and dataset.path else ""
        return alias, path

    def create(
        self,
        kind: AnnotationKind,
        dock_id: str,
        plot: PlotWidget,
        subplot: int,
        x: float,
        y: float,
        text: str = "",
    ) -> Annotation:
        lo, hi = plot.x_range()
        alias, path = self.dataset_for(plot, subplot)
        ann = Annotation(
            kind=kind,
            x=x - (hi - lo) * 0.05 if kind == "region" else x,
            x2=x + (hi - lo) * 0.05 if kind == "region" else x,
            y=y,
            text=text,
            axis_id=plot.config.subplots[subplot].y_axes[0].axis_id,
            plot_id=dock_id,
            subplot=subplot,
            dataset_alias=alias,
            dataset_path=path,
            text_background="#ffffff" if kind == "text" else None,
        )
        return self.store.add(ann)

    def create_bubble(
        self, dock_id: str, plot: PlotWidget, subplot: int, series_id: str, x: float
    ) -> Annotation | None:
        """Bubble attached to ``series_id`` at ``x`` (None if the curve is not there)."""
        curve = plot.config.subplots[subplot].curve(series_id)
        if curve is None:
            return None
        alias = series_id.split("/", 1)[0]
        dataset = self.session.dataset(alias)
        ann = Annotation(
            kind="bubble",
            x=x,
            y=_curve_y(plot, curve, x),
            text=plot.series_label(curve),
            color=curve.color,
            series_id=series_id,
            axis_id=curve.axis_id,
            plot_id=dock_id,
            subplot=subplot,
            dataset_alias=alias,
            dataset_path=str(dataset.path) if dataset is not None and dataset.path else "",
        )
        return self.store.add(ann)

    def set_offset(self, ann_id: str, dx: float, dy: float) -> None:
        ann = self.store.get(ann_id)
        if ann is None:
            return
        ann.offset_x, ann.offset_y = dx, dy
        self.store.update(ann)

    def move(self, ann_id: str, x: float, y: float, x2: float) -> None:
        ann = self.store.get(ann_id)
        if ann is None:
            return
        moved = copy.deepcopy(ann)
        if ann.kind == "region":
            moved.x, moved.x2 = min(x, x2), max(x, x2)
        else:
            moved.x, moved.y = x, y
        self.store.update(moved)

    def edit(self, ann_id: str) -> None:
        ann = self.store.get(ann_id)
        if ann is None or self._edit_dialog is None:
            return
        parent = next(iter(self._plots()), (None, None))[1]
        result = self._edit_dialog(copy.deepcopy(ann), parent.window() if parent else None)
        if result is not None:
            self.store.update(result)

    def delete(self, ann_id: str) -> None:
        self.store.remove(ann_id)

    def set_locked(self, ann_id: str, locked: bool) -> None:
        ann = self.store.get(ann_id)
        if ann is not None:
            changed = copy.deepcopy(ann)
            changed.locked = locked
            self.store.update(changed)

    def focus(self, ann_id: str) -> None:
        """Bring the annotation into view (keeps the zoom width when possible)."""
        ann = self.store.get(ann_id)
        targets = self.targets(ann) if ann else []
        if ann is None or not targets:
            return
        dock_id, subplot = targets[0]
        plot = dict(self._plots())[dock_id]
        self.focus_requested.emit(dock_id)
        layer = self._layers.get(id(plot))
        if layer is not None:
            layer.selected_id = ann_id
        if ann.kind == "hline":
            view = plot.subplots[subplot].view_for_axis(ann.axis_id)
            lo, hi = view.viewRange()[1]
            half = (hi - lo) / 2
            view.setYRange(ann.y - half, ann.y + half, padding=0)
            return
        lo, hi = plot.x_range()
        width = hi - lo
        if ann.kind == "region" and abs(ann.x2 - ann.x) > 0.9 * width:
            margin = abs(ann.x2 - ann.x) * 0.1
            plot.subplots[0].view_box.setXRange(ann.x - margin, ann.x2 + margin, padding=0)
        else:
            c = ann.center_x
            plot.subplots[0].view_box.setXRange(c - width / 2, c + width / 2, padding=0)

    # -- menus ----------------------------------------------------------------------------

    def menu_extension(self, dock_id: str) -> Callable[[QMenu, PlotWidget, int, QPointF], None]:
        """Adds « Ajouter une annotation → type » to a graph's context menu."""

        def extend(menu: QMenu, plot: PlotWidget, subplot: int, scene_pos: QPointF) -> None:
            point = plot.subplots[subplot].view_box.mapSceneToView(scene_pos)
            sub_menu = menu.addMenu(tr(Msg.MENU_ADD_ANNOTATION))
            kinds: tuple[tuple[str, AnnotationKind], ...] = (
                (Msg.ANN_TEXT, "text"),
                (Msg.ANN_VLINE, "vline"),
                (Msg.ANN_HLINE, "hline"),
                (Msg.ANN_REGION, "region"),
            )
            for text, kind in kinds:
                sub_menu.addAction(
                    tr(text),
                    partial(
                        self._create_interactive, kind, dock_id, plot, subplot, point.x(), point.y()
                    ),
                )
                if kind == "text":
                    self._add_bubble_actions(sub_menu, dock_id, plot, subplot, scene_pos)

        return extend

    def _add_bubble_actions(
        self, menu: QMenu, dock_id: str, plot: PlotWidget, subplot: int, scene_pos: QPointF
    ) -> None:
        """« Bulle sur « courbe » » for the curve under the mouse, else one per curve."""
        sub_cfg = plot.config.subplots[subplot]
        curves = [c for c in sub_cfg.curves if c.visible]
        x = plot.subplots[subplot].view_box.mapSceneToView(scene_pos).x()
        near = plot.subplots[subplot].curve_near(scene_pos)
        if near is not None:
            curves = [c for c in curves if c.series_id == near]
        if len(curves) == 1:
            name = plot.series_label(curves[0])
            menu.addAction(
                tr(Msg.ANN_BUBBLE_ON).format(name=name),
                partial(
                    self._create_bubble_interactive, dock_id, plot, subplot, curves[0].series_id, x
                ),
            )
            return
        bubble_menu = menu.addMenu(tr(Msg.ANN_BUBBLE))
        bubble_menu.setEnabled(bool(curves))
        for curve in curves:
            bubble_menu.addAction(
                plot.series_label(curve),
                partial(
                    self._create_bubble_interactive, dock_id, plot, subplot, curve.series_id, x
                ),
            )

    def _create_bubble_interactive(
        self, dock_id: str, plot: PlotWidget, subplot: int, series_id: str, x: float
    ) -> None:
        ann = self.create_bubble(dock_id, plot, subplot, series_id, x)
        if ann is not None and self._edit_dialog is not None:
            result = self._edit_dialog(copy.deepcopy(ann), plot.window())
            if result is None:
                self.store.remove(ann.id)
            else:
                self.store.update(result)

    def _create_interactive(
        self, kind: AnnotationKind, dock_id: str, plot: PlotWidget, subplot: int, x: float, y: float
    ) -> None:
        ann = self.create(kind, dock_id, plot, subplot, x, y, tr(Msg.ANN_DEFAULT_TEXT))
        if self._edit_dialog is not None:
            result = self._edit_dialog(copy.deepcopy(ann), plot.window())
            if result is None:
                self.store.remove(ann.id)
            else:
                self.store.update(result)

    def build_annotation_menu(self, ann_id: str) -> QMenu:
        ann = self.store.get(ann_id)
        menu = QMenu()
        if ann is None:
            return menu
        menu.addAction(tr(Msg.ANN_EDIT), lambda: self.edit(ann_id))
        lock = menu.addAction(tr(Msg.ANN_LOCK), lambda: self.set_locked(ann_id, not ann.locked))
        lock.setCheckable(True)
        lock.setChecked(ann.locked)
        menu.addSeparator()
        menu.addAction(tr(Msg.ANN_DELETE), lambda: self.delete(ann_id))
        return menu

    def _show_menu(self, ann_id: str, screen_pos: QPointF) -> None:
        self.build_annotation_menu(ann_id).exec(screen_pos.toPoint())
