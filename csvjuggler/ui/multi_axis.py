"""Secondary Y axes of a PlotItem.

Each secondary axis is an extra :class:`pg.ViewBox` with its own :class:`FormattedAxis`:

- the ViewBox is X-linked to the main one (``setXLink``) and its geometry follows the main
  ViewBox (``sigResized``);
- it is a top-level scene item placed *below* the PlotItem, so mouse drags and wheel events
  in the plotting area reach the main ViewBox (X + primary axis only);
- its AxisItem is added to the PlotItem's layout, on the right (after the main view) or on
  the left (before the primary axis: the whole grid is shifted right, see
  :meth:`MultiAxis.relayout`), and linked to the ViewBox: wheel/drag on that axis only act
  on that axis;
- the main ViewBox includes the secondary curves when computing its automatic X range.
"""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QRectF

from csvjuggler.ui.plot_items import FormattedAxis, PlotViewBox

AXIS_ROW = 2
FIRST_RIGHT_COLUMN = 3
"""First column of the right secondary axes when there is no left secondary axis."""
CORE_POSITIONS = {"title": (0, 1), "top": (1, 1), "left": (2, 0), "view": (2, 1), "right": (2, 2),
                  "bottom": (3, 1)}  # fmt: skip
"""Cells of the PlotItem's own items (pyqtgraph), before shifting for left secondary axes."""


class SecondaryViewBox(pg.ViewBox):
    """Only reacts to events forwarded by its axis (``axis`` argument set)."""

    def __init__(self) -> None:
        super().__init__(enableMenu=False)

    def wheelEvent(self, ev, axis=None) -> None:
        if axis is None:
            ev.ignore()
            return
        super().wheelEvent(ev, axis=axis)

    def mouseDragEvent(self, ev, axis=None) -> None:
        if axis is None:
            ev.ignore()
            return
        super().mouseDragEvent(ev, axis=axis)


class MultiAxis:
    def __init__(
        self,
        plot_item: pg.PlotItem,
        main_view: PlotViewBox,
        on_axis_created: Callable[[FormattedAxis], None] | None = None,
    ) -> None:
        self.plot_item = plot_item
        self.main_view = main_view
        self._on_axis_created = on_axis_created
        self.axes: dict[str, tuple[SecondaryViewBox, FormattedAxis]] = {}
        self.sides: dict[str, str] = {}
        main_view.sigResized.connect(self.update_geometry)

    def __contains__(self, axis_id: str) -> bool:
        return axis_id in self.axes

    def view(self, axis_id: str) -> SecondaryViewBox:
        return self.axes[axis_id][0]

    def axis(self, axis_id: str) -> FormattedAxis:
        return self.axes[axis_id][1]

    def ensure(self, axes: list[tuple[str, str]]) -> None:
        """Create missing axes ``(axis_id, side)``, move axes to their side, keep the order."""
        for axis_id, side in axes:
            side = "left" if side == "left" else "right"
            if axis_id not in self.axes:
                self._create(axis_id, side)
            elif self.sides.get(axis_id) != side:
                self._replace_axis_item(axis_id, side)
        ids = [axis_id for axis_id, _side in axes]
        order = ids + [a for a in self.axes if a not in ids]
        self.axes = {a: self.axes[a] for a in order}
        self.relayout()

    def remove_unused(self, keep: set[str]) -> None:
        for axis_id in [a for a in self.axes if a not in keep]:
            self._remove(axis_id)
        self.relayout()

    def _new_axis_item(self, axis_id: str, side: str, view: SecondaryViewBox) -> FormattedAxis:
        axis = FormattedAxis(side, axis_id)
        axis.setZValue(-1000)
        axis.linkToView(view)
        if self._on_axis_created is not None:
            self._on_axis_created(axis)
        return axis

    def _replace_axis_item(self, axis_id: str, side: str) -> None:
        """An AxisItem's orientation is fixed: a new one for the other side."""
        view, old = self.axes[axis_id]
        self._take_out(old)
        old.unlinkFromView()
        if old.scene() is not None:
            old.scene().removeItem(old)
        self.axes[axis_id] = (view, self._new_axis_item(axis_id, side, view))
        self.sides[axis_id] = side

    def _create(self, axis_id: str, side: str = "right") -> None:
        view = SecondaryViewBox()
        scene = self.plot_item.scene()
        if scene is not None:
            scene.addItem(view)
        view.setZValue(self.plot_item.zValue() - 1)
        view.setXLink(self.main_view)
        view.enableAutoRange(x=False, y=True)
        self.axes[axis_id] = (view, self._new_axis_item(axis_id, side, view))
        self.sides[axis_id] = side
        self.main_view.secondary_views.append(view)
        self.update_geometry()

    def _remove(self, axis_id: str) -> None:
        view, axis = self.axes.pop(axis_id)
        for item in list(view.addedItems):
            clip = getattr(item, "opts", {}).get("clipToView", False)
            if clip:
                item.setClipToView(False)  # see SubPlot._move_to_view
            view.removeItem(item)
            self.main_view.addItem(item)
            if clip:
                item.setClipToView(True)
        self.main_view.secondary_views.remove(view)
        self.sides.pop(axis_id, None)
        self._take_out(axis)
        for obj in (axis, view):
            if obj.scene() is not None:
                obj.scene().removeItem(obj)
        axis.unlinkFromView()

    def _in_layout(self, item: object) -> bool:
        layout = self.plot_item.layout
        return any(layout.itemAt(i) is item for i in range(layout.count()))

    def _take_out(self, item: object) -> None:
        if self._in_layout(item):
            self.plot_item.layout.removeItem(item)

    def relayout(self) -> None:
        """Place every item of the PlotItem's grid.

        Left secondary axes take columns 0…k-1 (the first one next to the primary axis), so
        pyqtgraph's own items (title, axes, view) are shifted right by k; right secondary
        axes follow the view. Called after any change, including when pyqtgraph re-adds an
        item at its default cell (``setAxisItems``).
        """
        layout = self.plot_item.layout
        left = [a for a in self.axes if self.sides.get(a) == "left"]
        right = [a for a in self.axes if self.sides.get(a) != "left"]
        shift = len(left)
        core = {
            "title": self.plot_item.titleLabel,
            "view": self.main_view,
            **{name: self.plot_item.getAxis(name) for name in ("top", "bottom", "left", "right")},
        }
        for item in [*core.values(), *(axis for _view, axis in self.axes.values())]:
            self._take_out(item)
        for name, item in core.items():
            row, col = CORE_POSITIONS[name]
            layout.addItem(item, row, col + shift)
        for i, axis_id in enumerate(left):
            layout.addItem(self.axes[axis_id][1], AXIS_ROW, shift - 1 - i)
        for i, axis_id in enumerate(right):
            layout.addItem(self.axes[axis_id][1], AXIS_ROW, shift + FIRST_RIGHT_COLUMN + i)
        for col in range(shift + FIRST_RIGHT_COLUMN + len(right)):
            layout.setColumnStretchFactor(col, 100 if col == shift + 1 else 1)
            layout.setColumnSpacing(col, 0)
        self.update_geometry()

    def update_geometry(self) -> None:
        # Not sceneBoundingRect(): GraphicsWidget.boundingRect() adds 0.5 px, which would make
        # the X-linked views differ slightly in width (hence in X range).
        rect = QRectF(self.main_view.sceneBoundingRect().topLeft(), self.main_view.size())
        for view, _axis in self.axes.values():
            view.setGeometry(rect)
            view.linkedViewChanged(self.main_view, view.XAxis)
