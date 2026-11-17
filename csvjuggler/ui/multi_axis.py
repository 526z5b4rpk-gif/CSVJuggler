"""Secondary Y axes of a PlotItem.

Each secondary axis is an extra :class:`pg.ViewBox` with its own :class:`FormattedAxis`:

- the ViewBox is X-linked to the main one (``setXLink``) and its geometry follows the main
  ViewBox (``sigResized``);
- it is a top-level scene item placed *below* the PlotItem, so mouse drags and wheel events
  in the plotting area reach the main ViewBox (X + primary axis only);
- its AxisItem is added to the PlotItem's layout on the right (columns 3, 4, …) and linked
  to the ViewBox: wheel/drag on that axis only act on that axis;
- the main ViewBox includes the secondary curves when computing its automatic X range.
"""

from __future__ import annotations

from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import QRectF

from csvjuggler.ui.plot_items import FormattedAxis, PlotViewBox

FIRST_RIGHT_COLUMN = 3
"""PlotItem layout: left axis = column 0, view = 1, right axis = 2 (hidden)."""
AXIS_ROW = 2


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
        self._placed: set[str] = set()
        main_view.sigResized.connect(self.update_geometry)

    def __contains__(self, axis_id: str) -> bool:
        return axis_id in self.axes

    def view(self, axis_id: str) -> SecondaryViewBox:
        return self.axes[axis_id][0]

    def axis(self, axis_id: str) -> FormattedAxis:
        return self.axes[axis_id][1]

    def ensure(self, axis_ids: list[str]) -> None:
        """Create missing axes; order the axes like ``axis_ids``."""
        for axis_id in axis_ids:
            if axis_id not in self.axes:
                self._create(axis_id)
        order = axis_ids + [a for a in self.axes if a not in axis_ids]
        self.axes = {a: self.axes[a] for a in order}
        self._layout_axes()

    def remove_unused(self, keep: set[str]) -> None:
        for axis_id in [a for a in self.axes if a not in keep]:
            self._remove(axis_id)
        self._layout_axes()

    def _create(self, axis_id: str) -> None:
        view = SecondaryViewBox()
        axis = FormattedAxis("right", axis_id)
        axis.setZValue(-1000)
        scene = self.plot_item.scene()
        if scene is not None:
            scene.addItem(view)
        view.setZValue(self.plot_item.zValue() - 1)
        view.setXLink(self.main_view)
        view.enableAutoRange(x=False, y=True)
        axis.linkToView(view)
        self.axes[axis_id] = (view, axis)
        self.main_view.secondary_views.append(view)
        if self._on_axis_created is not None:
            self._on_axis_created(axis)
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
        if axis_id in self._placed:
            self.plot_item.layout.removeItem(axis)
            self._placed.discard(axis_id)
        for obj in (axis, view):
            if obj.scene() is not None:
                obj.scene().removeItem(obj)
        axis.unlinkFromView()

    def _layout_axes(self) -> None:
        layout = self.plot_item.layout
        for axis_id in self._placed:
            layout.removeItem(self.axes[axis_id][1])
        for i, (_view, axis) in enumerate(self.axes.values()):
            layout.addItem(axis, AXIS_ROW, FIRST_RIGHT_COLUMN + i)
        self._placed = set(self.axes)
        self.update_geometry()

    def update_geometry(self) -> None:
        # Not sceneBoundingRect(): GraphicsWidget.boundingRect() adds 0.5 px, which would make
        # the X-linked views differ slightly in width (hence in X range).
        rect = QRectF(self.main_view.sceneBoundingRect().topLeft(), self.main_view.size())
        for view, _axis in self.axes.values():
            view.setGeometry(rect)
            view.linkedViewChanged(self.main_view, view.XAxis)
