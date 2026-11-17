"""Context menus and settings dialogs of a graph.

:class:`PlotController` listens to the requests emitted by a :class:`PlotWidget` (right
clicks, double clicks) and turns them into menus and dialogs. Every action ends in a
:class:`PlotWidget` method that mutates the configuration.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QObject, QPointF
from PySide6.QtWidgets import QInputDialog, QMenu, QWidget

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import GLOBAL_SYNC_GROUP, X_AXIS_ID, CurveConfig
from csvjuggler.ui.dialogs.curve_settings_dialog import CurveSettingsDialog
from csvjuggler.ui.dialogs.plot_settings_dialog import AxisSettingsDialog, PlotSettingsDialog
from csvjuggler.ui.plot_widget import PlotWidget

MenuExtension = Callable[[QMenu, PlotWidget, int, QPointF], None]
"""Adds entries to the plot context menu: ``(menu, plot, subplot, scene_pos)``."""


class PlotController(QObject):
    def __init__(self, plot: PlotWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.plot = plot
        self.menu_extensions: list[MenuExtension] = []
        self.curve_menu_extensions: list[Callable[[QMenu, PlotWidget, int, CurveConfig], None]] = []
        plot.plot_menu_requested.connect(self._on_plot_menu)
        plot.axis_menu_requested.connect(self._on_axis_menu)
        plot.plot_settings_requested.connect(self.edit_plot_settings)
        plot.axis_settings_requested.connect(self.edit_axis)

    @property
    def _parent_widget(self) -> QWidget:
        return self.plot.window()

    # -- menus ----------------------------------------------------------------------------

    def build_plot_menu(self, subplot: int, scene_pos: QPointF) -> QMenu:
        plot = self.plot
        menu = QMenu(plot)
        sub_cfg = plot.config.subplots[subplot]

        near = plot.subplots[subplot].curve_near(scene_pos)
        if near is not None and (curve := sub_cfg.curve(near)) is not None:
            menu.addSection(tr(Msg.MENU_CURVE).format(name=plot.series_label(curve)))
            self._fill_curve_menu(menu, subplot, curve)
            menu.addSeparator()

        if sub_cfg.curves:
            curves_menu = menu.addMenu(tr(Msg.MENU_CURVES))
            for curve in sub_cfg.curves:
                self._fill_curve_menu(curves_menu.addMenu(plot.series_label(curve)), subplot, curve)

        for extension in self.menu_extensions:
            extension(menu, plot, subplot, scene_pos)

        menu.addSeparator()
        menu.addAction(tr(Msg.ACTION_AUTO_RANGE), plot.auto_range)
        menu.addAction(tr(Msg.MENU_PLOT_SETTINGS), self.edit_plot_settings)
        menu.addAction(tr(Msg.MENU_X_AXIS), lambda: self.edit_axis(subplot, X_AXIS_ID))
        menu.addAction(
            tr(Msg.MENU_Y_AXIS), lambda: self.edit_axis(subplot, sub_cfg.y_axes[0].axis_id)
        )
        self._fill_sync_menu(menu.addMenu(tr(Msg.MENU_SYNC)))
        menu.addSeparator()
        menu.addAction(tr(Msg.ACTION_SPLIT), plot.split)
        remove = menu.addAction(tr(Msg.MENU_REMOVE_SUBPLOT), lambda: plot.remove_subplot(subplot))
        remove.setEnabled(len(plot.config.subplots) > 1)
        return menu

    def _fill_curve_menu(self, menu: QMenu, subplot: int, curve: CurveConfig) -> None:
        plot = self.plot
        menu.addAction(
            tr(Msg.MENU_CURVE_SETTINGS), lambda: self.edit_curve(subplot, curve.series_id)
        )
        menu.addAction(
            tr(Msg.MENU_HIDE if curve.visible else Msg.MENU_SHOW),
            lambda: plot.set_curve_visible(curve.series_id, not curve.visible),
        )
        for extension in self.curve_menu_extensions:
            extension(menu, plot, subplot, curve)
        menu.addAction(
            tr(Msg.MENU_REMOVE_CURVE), lambda: plot.remove_curve(curve.series_id, subplot)
        )

    def _fill_sync_menu(self, menu: QMenu) -> None:
        plot = self.plot
        current = plot.config.sync_group
        for text, group in ((Msg.MENU_SYNC_GLOBAL, GLOBAL_SYNC_GROUP), (Msg.MENU_SYNC_NONE, "")):
            action = menu.addAction(tr(text), partial(plot.set_sync_group, group))
            action.setCheckable(True)
            action.setChecked(current == group)
        if current not in (GLOBAL_SYNC_GROUP, ""):
            action = menu.addAction(current)
            action.setCheckable(True)
            action.setChecked(True)
        menu.addAction(tr(Msg.MENU_SYNC_NEW), self._ask_sync_group)

    def _ask_sync_group(self) -> None:
        name, ok = QInputDialog.getText(
            self._parent_widget, tr(Msg.MENU_SYNC), tr(Msg.MENU_SYNC_NEW_LABEL)
        )
        if ok and name.strip():
            self.plot.set_sync_group(name.strip())

    def build_axis_menu(self, subplot: int, axis_id: str) -> QMenu:
        plot = self.plot
        menu = QMenu(plot)
        menu.addAction(tr(Msg.MENU_AXIS_SETTINGS), lambda: self.edit_axis(subplot, axis_id))
        menu.addAction(tr(Msg.MENU_AUTO_ONCE), lambda: plot.auto_range_once(subplot, axis_id))
        menu.addAction(tr(Msg.MENU_AUTO), lambda: self._set_auto(subplot, axis_id))
        return menu

    def _set_auto(self, subplot: int, axis_id: str) -> None:
        cfg = self.plot.axis_config(subplot, axis_id)
        if cfg is not None:
            cfg.auto_range = True
            self.plot.set_axis_config(subplot, cfg)

    def _on_plot_menu(self, subplot: int, scene_pos: QPointF, screen_pos: QPointF) -> None:
        self.build_plot_menu(subplot, scene_pos).exec(screen_pos.toPoint())

    def _on_axis_menu(self, subplot: int, axis_id: str, screen_pos: QPointF) -> None:
        self.build_axis_menu(subplot, axis_id).exec(screen_pos.toPoint())

    # -- dialogs --------------------------------------------------------------------------

    def series_choices(self) -> list[tuple[str, str]]:
        return [
            (f"{ds.alias} / {s.label}", s.id)
            for ds in self.plot.session.datasets
            for s in ds.series.values()
        ]

    def edit_plot_settings(self) -> None:
        dialog = PlotSettingsDialog(self.plot.config, self.series_choices(), self._parent_widget)
        if dialog.exec() == PlotSettingsDialog.DialogCode.Accepted:
            self.plot.update_config(dialog.config())

    def edit_axis(self, subplot: int, axis_id: str) -> None:
        cfg = self.plot.axis_config(subplot, axis_id)
        if cfg is None:
            return
        name = tr(Msg.AXIS_X) if axis_id == X_AXIS_ID else cfg.title or axis_id
        dialog = AxisSettingsDialog(
            cfg,
            name,
            self.series_choices(),
            auto_once=lambda: self.plot.data_range(subplot, axis_id),
            parent=self._parent_widget,
        )
        if dialog.exec() == AxisSettingsDialog.DialogCode.Accepted:
            self.plot.set_axis_config(subplot, dialog.axis())

    def edit_curve(self, subplot: int, series_id: str) -> None:
        curve = self.plot.curve_config(subplot, series_id)
        if curve is None:
            return
        dialog = CurveSettingsDialog(
            curve, self.plot.series_label(curve), parent=self._parent_widget
        )
        if dialog.exec() == CurveSettingsDialog.DialogCode.Accepted:
            self.plot.set_curve_config(subplot, dialog.curve())
