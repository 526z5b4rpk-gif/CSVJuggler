"""Graphic items of annotations, their per-graph layer and the session-wide manager.

- :class:`AnnotationManager` decides where each annotation is shown (its graph/subplot,
  every graph of the sync group for linked vertical lines, or — when its graph does not
  exist, e.g. after opening a companion file — every graph showing its dataset).
- :class:`AnnotationLayer` (one per graph) owns the pyqtgraph items and reports user
  interaction (move, double-click, right click, selection) through an :class:`AnnotationHub`.
- Items are rebuilt when their annotation changes; the store is the single source of truth.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from functools import partial

import pyqtgraph as pg
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.annotation import Annotation, AnnotationKind
from csvjuggler.model.session import Session
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


class TextAnnotationItem(pg.GraphicsObject):
    """Text in a rounded bubble anchored at (x, y), draggable unless locked.

    With ``ann.arrow`` the bubble sits above-right of the point and a tail points to it
    (a small dot marks the point); otherwise the bubble's bottom-left corner is the point.
    Drawn in pixels (ignores the view scale), so it keeps its size when zooming.
    """

    PADDING = (8.0, 5.0)
    RADIUS = 6.0
    TAIL_OFFSET = QPointF(14.0, -22.0)
    """Bubble bottom-left corner relative to the point, when it has a tail."""
    TAIL_BASE = (8.0, 20.0)
    """Tail base along the bubble's bottom edge, from its left side."""
    SHADOW = QPointF(2.0, 2.0)

    def __init__(self, ann: Annotation, hub: AnnotationHub) -> None:
        super().__init__()
        self.ann, self.hub = ann, hub
        self.setFlag(self.GraphicsItemFlag.ItemIgnoresTransformations)
        self.setPos(ann.x, ann.y)
        self.setOpacity(ann.opacity)
        self.font = _font(ann)
        self.text = ann.text or " "
        metrics = QFontMetricsF(self.font)
        text_rect = metrics.boundingRect(
            QRectF(0, 0, 10000, 10000), int(Qt.AlignmentFlag.AlignLeft), self.text
        )
        pad_x, pad_y = self.PADDING
        width, height = text_rect.width() + 2 * pad_x, text_rect.height() + 2 * pad_y
        origin = self.TAIL_OFFSET if ann.arrow else QPointF(0.0, 0.0)
        self.box = QRectF(origin.x(), origin.y() - height, width, height)
        self.text_rect = self.box.adjusted(pad_x, pad_y, -pad_x, -pad_y)
        path = QPainterPath()
        path.addRoundedRect(self.box, self.RADIUS, self.RADIUS)
        if ann.arrow:
            base0, base1 = self.TAIL_BASE
            tail = QPainterPath(QPointF(0.0, 0.0))
            tail.lineTo(self.box.left() + base0, self.box.bottom() - 1)
            tail.lineTo(self.box.left() + base1, self.box.bottom() - 1)
            tail.closeSubpath()
            path = path.united(tail)
        self.path = path.simplified()
        self._bounds = self.path.boundingRect().adjusted(
            -3, -3, 3 + self.SHADOW.x(), 3 + self.SHADOW.y()
        )
        self._drag_offset = QPointF()

    def boundingRect(self) -> QRectF:
        return self._bounds

    def shape(self) -> QPainterPath:
        return self.path

    def paint(self, painter: QPainter, *_args: object) -> None:
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
        if self.ann.arrow:
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(0.0, 0.0), 3.0, 3.0)
        painter.setFont(self.font)
        painter.setPen(color)
        painter.drawText(self.text_rect, int(Qt.AlignmentFlag.AlignLeft), self.text)

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
        if ev.isFinish():
            self.hub.moved.emit(self.ann.id, pos.x(), pos.y(), self.ann.x2)

    def mouseClickEvent(self, ev) -> None:
        if not _handle_click(self, self.ann, self.hub, ev):
            ev.accept()


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


class AnnotationLayer:
    """Annotation items of one graph."""

    def __init__(self, plot: PlotWidget, hub: AnnotationHub) -> None:
        self.plot = plot
        self.hub = hub
        self._shown: dict[tuple[str, int], tuple[Annotation, list[pg.GraphicsObject]]] = {}
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
        return [i for (aid, _), (_, items) in self._shown.items() if aid == ann_id for i in items]

    def sync(self, placements: list[tuple[Annotation, int]]) -> None:
        wanted = {(a.id, sub): a for a, sub in placements if sub < len(self.plot.subplots)}
        for key in list(self._shown):
            shown, _items = self._shown[key]
            if key not in wanted or wanted[key] != shown:
                self._remove(key)
        for key, ann in wanted.items():
            if key not in self._shown:
                self._create(ann, key[1])
        if self.selected_id is not None and not any(k[0] == self.selected_id for k in wanted):
            self.selected_id = None

    def _create(self, ann: Annotation, subplot: int) -> None:
        sub = self.plot.subplots[subplot]
        view = sub.view_for_axis(ann.axis_id) if ann.kind in ("text", "hline") else sub.view_box
        item = ITEM_CLASSES[ann.kind](ann, self.hub)
        items: list[pg.GraphicsObject] = [item]
        for it in items:
            it.setZValue(ANNOTATION_Z)
            view.addItem(it, ignoreBounds=True)
        self._shown[(ann.id, subplot)] = (copy.deepcopy(ann), items)

    def _remove(self, key: tuple[str, int]) -> None:
        _ann, items = self._shown.pop(key)
        for it in items:
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

    # -- graphs ---------------------------------------------------------------------------

    def register_plot(self, plot: PlotWidget) -> AnnotationLayer:
        hub = AnnotationHub(plot)
        layer = AnnotationLayer(plot, hub)
        self._layers[id(plot)] = layer
        plot.annotation_layer = layer
        hub.moved.connect(self.move)
        hub.edit_requested.connect(self.edit)
        hub.menu_requested.connect(self._show_menu)
        hub.delete_requested.connect(self.delete)
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

    def refresh(self) -> None:
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

        return extend

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
