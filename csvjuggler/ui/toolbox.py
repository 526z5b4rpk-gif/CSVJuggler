"""« Boîte à outils » panel: live settings of the current graph and its curves, annotations.

It follows the current graph (like the measure panel). Every edit is applied immediately
through the same API as the dialogs (``update_config``, ``set_curve_config``), so what is on
screen is still what gets saved; the panel refreshes itself on ``config_changed``.
"""

from __future__ import annotations

import contextlib
import copy
from functools import partial

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QToolBox,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.annotation import AnnotationKind
from csvjuggler.model.plot_config import X_AXIS_ID, CurveConfig, PlotConfig
from csvjuggler.ui.annotation_items import AnnotationManager
from csvjuggler.ui.dialogs.annotation_dialog import KIND_NAMES
from csvjuggler.ui.dialogs.curve_settings_dialog import CurveSettingsWidget
from csvjuggler.ui.dialogs.plot_settings_dialog import PlotGeneralWidget
from csvjuggler.ui.plot_dock import PlotDock

ADD_KINDS: tuple[tuple[str, AnnotationKind], ...] = (
    (Msg.ANN_TEXT, "text"),
    (Msg.ANN_BUBBLE, "bubble"),
    (Msg.ANN_DELTA_KIND, "delta"),
    (Msg.ANN_VLINE, "vline"),
    (Msg.ANN_HLINE, "hline"),
    (Msg.ANN_REGION, "region"),
)
CURVE_KINDS = ("bubble", "delta")


def _swatch(color: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


class ToolboxPanel(QWidget):
    def __init__(self, annotations: AnnotationManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.annotations = annotations
        self.dock: PlotDock | None = None
        self._connections: list[tuple[object, object]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.empty_label = QLabel(tr(Msg.TOOLBOX_NO_GRAPH), self)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)
        self.sections = QToolBox(self)
        layout.addWidget(self.sections)

        # -- graph
        graph_page = QWidget(self)
        graph_layout = QVBoxLayout(graph_page)
        self.general = PlotGeneralWidget(PlotConfig(), graph_page)
        self.general.changed.connect(self._on_general_changed)
        graph_layout.addWidget(self.general)
        buttons = QHBoxLayout()
        self.x_axis_button = QPushButton(tr(Msg.MENU_X_AXIS), graph_page)
        self.x_axis_button.clicked.connect(self._edit_x_axis)
        self.y_axis_button = QPushButton(tr(Msg.MENU_Y_AXIS), graph_page)
        self.y_axis_button.clicked.connect(self._edit_main_y_axis)
        self.all_settings_button = QPushButton(tr(Msg.TOOLBOX_ALL_SETTINGS), graph_page)
        self.all_settings_button.clicked.connect(self._edit_all)
        for button in (self.x_axis_button, self.y_axis_button, self.all_settings_button):
            buttons.addWidget(button)
        graph_layout.addLayout(buttons)
        graph_layout.addStretch(1)
        self.sections.addItem(_scrolled(graph_page, self.sections), tr(Msg.TOOLBOX_GRAPH))

        # -- curves
        curves_page = QWidget(self)
        curves_layout = QVBoxLayout(curves_page)
        self.curve_list = QListWidget(curves_page)
        self.curve_list.setMaximumHeight(140)
        self.curve_list.currentRowChanged.connect(self._on_curve_selected)
        curves_layout.addWidget(self.curve_list)
        self.no_curve_label = QLabel(tr(Msg.TOOLBOX_NO_CURVE), curves_page)
        self.no_curve_label.setWordWrap(True)
        curves_layout.addWidget(self.no_curve_label)
        self.curve_editor = CurveSettingsWidget(
            CurveConfig(series_id="", color="#000000"), "", curves_page
        )
        self.curve_editor.changed.connect(self._on_curve_edited)
        curves_layout.addWidget(self.curve_editor)
        curve_buttons = QHBoxLayout()
        self.curve_axis_button = QPushButton(tr(Msg.TOOLBOX_CURVE_AXIS), curves_page)
        self.curve_axis_button.clicked.connect(self._edit_curve_axis)
        self.remove_curve_button = QPushButton(tr(Msg.MENU_REMOVE_CURVE), curves_page)
        self.remove_curve_button.clicked.connect(self._remove_curve)
        curve_buttons.addWidget(self.curve_axis_button)
        curve_buttons.addWidget(self.remove_curve_button)
        curves_layout.addLayout(curve_buttons)
        curves_layout.addStretch(1)
        self.sections.addItem(_scrolled(curves_page, self.sections), tr(Msg.TOOLBOX_CURVES))
        self._curve_keys: list[tuple[int, str]] = []

        # -- annotations
        ann_page = QWidget(self)
        ann_layout = QVBoxLayout(ann_page)
        add_box = QGroupBox(tr(Msg.TOOLBOX_ADD), ann_page)
        grid = QGridLayout(add_box)
        self.add_buttons: dict[str, QPushButton] = {}
        for index, (text, kind) in enumerate(ADD_KINDS):
            button = QPushButton(tr(text), add_box)
            button.clicked.connect(partial(self.add_annotation, kind))
            grid.addWidget(button, index // 2, index % 2)
            self.add_buttons[kind] = button
        ann_layout.addWidget(add_box)
        hint = QLabel(tr(Msg.TOOLBOX_ADD_HINT), ann_page)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        ann_layout.addWidget(hint)
        selection_box = QGroupBox(tr(Msg.TOOLBOX_SELECTION), ann_page)
        selection_layout = QVBoxLayout(selection_box)
        self.selection_label = QLabel(tr(Msg.TOOLBOX_NO_SELECTION), selection_box)
        self.selection_label.setWordWrap(True)
        selection_layout.addWidget(self.selection_label)
        selection_buttons = QHBoxLayout()
        self.edit_selection_button = QPushButton(tr(Msg.ANN_EDIT), selection_box)
        self.edit_selection_button.clicked.connect(self._edit_selection)
        self.delete_selection_button = QPushButton(tr(Msg.ANN_DELETE), selection_box)
        self.delete_selection_button.clicked.connect(self._delete_selection)
        selection_buttons.addWidget(self.edit_selection_button)
        selection_buttons.addWidget(self.delete_selection_button)
        selection_layout.addLayout(selection_buttons)
        ann_layout.addWidget(selection_box)
        ann_layout.addStretch(1)
        self.sections.addItem(_scrolled(ann_page, self.sections), tr(Msg.TOOLBOX_ANNOTATIONS))

        annotations.store.annotations_changed.connect(self._refresh_selection)
        self.set_dock(None)

    # -- current graph --------------------------------------------------------------------

    def set_dock(self, dock: PlotDock | None) -> None:
        for signal, slot in self._connections:
            with contextlib.suppress(RuntimeError, TypeError):
                signal.disconnect(slot)  # type: ignore[attr-defined]
        self._connections = []
        self.dock = dock
        if dock is not None:
            pairs: list[tuple[object, object]] = [(dock.plot.config_changed, self.refresh)]
            layer = dock.plot.annotation_layer
            if layer is not None:
                pairs.append((layer.hub.selected, self._refresh_selection))
            for signal, slot in pairs:
                signal.connect(slot)  # type: ignore[attr-defined]
            self._connections = pairs
        self.refresh()

    def refresh(self) -> None:
        has_dock = self.dock is not None
        self.empty_label.setVisible(not has_dock)
        self.sections.setEnabled(has_dock)
        if self.dock is None:
            self._fill_curves(None)
            self._refresh_selection()
            return
        self.general.set_config(self.dock.plot.config)
        self._fill_curves(self.dock.plot.config)
        self._refresh_selection()

    # -- graph section --------------------------------------------------------------------

    def _on_general_changed(self) -> None:
        if self.dock is None:
            return
        config = copy.deepcopy(self.dock.plot.config)
        self.general.apply_to(config)
        if config != self.dock.plot.config:
            self.dock.plot.update_config(config)

    def _edit_x_axis(self) -> None:
        if self.dock is not None:
            self.dock.controller.edit_axis(0, X_AXIS_ID)

    def _edit_main_y_axis(self) -> None:
        if self.dock is not None:
            subplot = self._selected_subplot()
            axis = self.dock.plot.config.subplots[subplot].y_axes[0]
            self.dock.controller.edit_axis(subplot, axis.axis_id)

    def _edit_all(self) -> None:
        if self.dock is not None:
            self.dock.controller.edit_plot_settings()

    # -- curves section -------------------------------------------------------------------

    def _fill_curves(self, config: PlotConfig | None) -> None:
        previous = self.selected_curve_key()
        keys = [
            (s, curve.series_id)
            for s, sub in enumerate(config.subplots if config else [])
            for curve in sub.curves
        ]
        blocker = QSignalBlocker(self.curve_list)
        self.curve_list.clear()
        self._curve_keys = keys
        for subplot, series_id in keys:
            assert config is not None and self.dock is not None
            curve = config.subplots[subplot].curve(series_id)
            assert curve is not None
            text = self.dock.plot.series_label(curve)
            if len(config.subplots) > 1:
                text = tr(Msg.TOOLBOX_CURVE_ITEM).format(name=text, subplot=subplot + 1)
            item = QListWidgetItem(_swatch(curve.color), text)
            if not curve.visible:
                item.setForeground(QColor("gray"))
            self.curve_list.addItem(item)
        row = keys.index(previous) if previous in keys else (0 if keys else -1)
        self.curve_list.setCurrentRow(row)
        del blocker
        self._show_curve(row)

    def selected_curve_key(self) -> tuple[int, str] | None:
        row = self.curve_list.currentRow()
        return self._curve_keys[row] if 0 <= row < len(self._curve_keys) else None

    def _selected_subplot(self) -> int:
        key = self.selected_curve_key()
        return key[0] if key is not None else 0

    def _on_curve_selected(self, row: int) -> None:
        self._show_curve(row)

    def _show_curve(self, row: int) -> None:
        key = self._curve_keys[row] if 0 <= row < len(self._curve_keys) else None
        curve = self._curve(key)
        has_curve = curve is not None
        self.curve_editor.setVisible(has_curve)
        self.no_curve_label.setVisible(not has_curve and self.dock is not None)
        self.curve_axis_button.setEnabled(has_curve)
        self.remove_curve_button.setEnabled(has_curve)
        if curve is not None and self.dock is not None:
            self.curve_editor.set_curve(curve, self.dock.plot.series_label(curve))

    def _curve(self, key: tuple[int, str] | None) -> CurveConfig | None:
        if key is None or self.dock is None:
            return None
        subplots = self.dock.plot.config.subplots
        return subplots[key[0]].curve(key[1]) if key[0] < len(subplots) else None

    def _on_curve_edited(self) -> None:
        key = self.selected_curve_key()
        if key is None or self.dock is None:
            return
        self.dock.plot.set_curve_config(key[0], self.curve_editor.curve())

    def _edit_curve_axis(self) -> None:
        key = self.selected_curve_key()
        curve = self._curve(key)
        if key is not None and curve is not None and self.dock is not None:
            self.dock.controller.edit_axis(key[0], curve.axis_id)

    def _remove_curve(self) -> None:
        key = self.selected_curve_key()
        if key is not None and self.dock is not None:
            self.dock.plot.remove_curve(key[1], key[0])

    # -- annotations section --------------------------------------------------------------

    def add_annotation(self, kind: AnnotationKind) -> None:
        """Add ``kind`` at the centre of the view of the selected curve's subplot."""
        if self.dock is None:
            return
        plot = self.dock.plot
        subplot = self._selected_subplot()
        series_id = ""
        if kind in CURVE_KINDS:
            key = self.selected_curve_key()
            curves = plot.config.subplots[subplot].curves
            visible = [c for c in curves if c.visible]
            if key is not None and (curve := self._curve(key)) is not None and curve.visible:
                series_id = curve.series_id
            elif visible:
                series_id = visible[0].series_id
            else:
                return
        lo, hi = plot.x_range()
        y_lo, y_hi = plot.subplots[subplot].view_box.viewRange()[1]
        self.annotations.add_interactive(
            kind,
            self.dock.dock_id,
            plot,
            subplot,
            (lo + hi) / 2,
            (y_lo + y_hi) / 2,
            series_id,
        )

    def _selected_annotation_id(self) -> str | None:
        if self.dock is None or self.dock.plot.annotation_layer is None:
            return None
        ann_id = self.dock.plot.annotation_layer.selected_id
        return ann_id if ann_id and self.annotations.store.get(ann_id) else None

    def _refresh_selection(self, *_args: object) -> None:
        ann_id = self._selected_annotation_id()
        ann = self.annotations.store.get(ann_id) if ann_id else None
        if ann is None:
            self.selection_label.setText(tr(Msg.TOOLBOX_NO_SELECTION))
        else:
            self.selection_label.setText(f"{tr(KIND_NAMES[ann.kind])} — {ann.text or '—'}")
        self.edit_selection_button.setEnabled(ann is not None)
        self.delete_selection_button.setEnabled(ann is not None)

    def _edit_selection(self) -> None:
        ann_id = self._selected_annotation_id()
        if ann_id:
            self.annotations.edit(ann_id)

    def _delete_selection(self) -> None:
        ann_id = self._selected_annotation_id()
        if ann_id:
            self.annotations.delete(ann_id)


def _scrolled(page: QWidget, parent: QWidget) -> QScrollArea:
    area = QScrollArea(parent)
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return area
