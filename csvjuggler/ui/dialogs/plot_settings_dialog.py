"""Plot settings dialog (general + X axis + Y axes) and stand-alone axis dialog."""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from csvjuggler.i18n import Msg, tr
from csvjuggler.model.plot_config import X_AXIS_ID, AxisConfig, PlotConfig
from csvjuggler.ui.widgets import ColorButton, DisposableDialog

LEGEND_CHOICES = (
    (Msg.LEGEND_TOP_LEFT, "top-left"),
    (Msg.LEGEND_TOP_RIGHT, "top-right"),
    (Msg.LEGEND_BOTTOM_LEFT, "bottom-left"),
    (Msg.LEGEND_BOTTOM_RIGHT, "bottom-right"),
    (Msg.LEGEND_HIDDEN, "hidden"),
)
X_MODE_CHOICES = (
    (Msg.X_MODE_RELATIVE, "relative"),
    (Msg.X_MODE_ABSOLUTE, "absolute"),
    (Msg.X_MODE_SERIES, "series"),
)


def _combo(choices: Sequence[tuple[str, object]], value: object) -> QComboBox:
    combo = QComboBox()
    for text, data in choices:
        combo.addItem(tr(text), data)
    index = combo.findData(value)
    combo.setCurrentIndex(max(0, index))
    return combo


def _spin(lo: float, hi: float, value: float, decimals: int = 6) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setValue(value)
    return spin


class AxisSettingsWidget(QWidget):
    """Edits one :class:`AxisConfig`. ``series_choices`` are ``(label, id)`` for XY mode."""

    def __init__(
        self,
        axis: AxisConfig,
        series_choices: Sequence[tuple[str, str]] = (),
        auto_once: Callable[[], tuple[float, float] | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._axis = copy.deepcopy(axis)
        self._auto_once = auto_once
        is_x = axis.axis_id == X_AXIS_ID
        form = QFormLayout(self)

        self.label_edit = QLineEdit(axis.label)
        self.unit_edit = QLineEdit(axis.unit)
        form.addRow(tr(Msg.LBL_LABEL), self.label_edit)
        form.addRow(tr(Msg.LBL_UNIT), self.unit_edit)

        if is_x:
            self.x_mode_combo = _combo(X_MODE_CHOICES, axis.x_mode)
            self.x_series_combo = QComboBox()
            self.x_series_combo.addItem("", None)
            for label, series_id in series_choices:
                self.x_series_combo.addItem(label, series_id)
            self.x_series_combo.setCurrentIndex(
                max(0, self.x_series_combo.findData(axis.x_series_id))
            )
            form.addRow(tr(Msg.LBL_X_MODE), self.x_mode_combo)
            form.addRow(tr(Msg.LBL_X_SERIES), self.x_series_combo)

        self.auto_check = QCheckBox(tr(Msg.LBL_AUTO_RANGE))
        self.auto_check.setChecked(axis.auto_range)
        self.min_spin = _spin(-1e300, 1e300, axis.min)
        self.max_spin = _spin(-1e300, 1e300, axis.max)
        auto_once_button = QPushButton(tr(Msg.LBL_AUTO_ONCE), self)
        auto_once_button.clicked.connect(self._on_auto_once)
        auto_once_button.setEnabled(auto_once is not None)
        range_row = QHBoxLayout()
        range_row.addWidget(self.min_spin)
        range_row.addWidget(self.max_spin)
        range_row.addWidget(auto_once_button)
        form.addRow(self.auto_check)
        form.addRow(f"{tr(Msg.LBL_MIN)} / {tr(Msg.LBL_MAX)}", range_row)
        self.auto_check.toggled.connect(self._update_enabled)

        self.log_check = QCheckBox(tr(Msg.LBL_LOG))
        self.log_check.setChecked(axis.log)
        self.inverted_check = QCheckBox(tr(Msg.LBL_INVERTED))
        self.inverted_check.setChecked(axis.inverted)
        form.addRow(self.log_check)
        form.addRow(self.inverted_check)

        self.decimals_spin = QSpinBox()
        self.decimals_spin.setRange(-1, 12)
        self.decimals_spin.setSpecialValueText(tr(Msg.AUTO))
        self.decimals_spin.setValue(-1 if axis.decimals is None else axis.decimals)
        self.scientific_check = QCheckBox(tr(Msg.LBL_SCIENTIFIC))
        self.scientific_check.setChecked(axis.scientific)
        self.si_check = QCheckBox(tr(Msg.LBL_SI_PREFIX))
        self.si_check.setChecked(axis.si_prefix)
        form.addRow(tr(Msg.LBL_DECIMALS), self.decimals_spin)
        form.addRow(self.scientific_check)
        form.addRow(self.si_check)

        self.color_button = ColorButton(axis.color, allow_none=True)
        reset = QPushButton(tr(Msg.AUTO), self)
        reset.clicked.connect(lambda: self.color_button.set_color(None))
        color_row = QHBoxLayout()
        color_row.addWidget(self.color_button)
        color_row.addWidget(reset)
        form.addRow(tr(Msg.LBL_COLOR), color_row)
        self._update_enabled()

    def _update_enabled(self) -> None:
        manual = not self.auto_check.isChecked()
        self.min_spin.setEnabled(manual)
        self.max_spin.setEnabled(manual)

    def _on_auto_once(self) -> None:
        if self._auto_once is None:
            return
        rng = self._auto_once()
        if rng is not None:
            self.auto_check.setChecked(False)
            self.min_spin.setValue(rng[0])
            self.max_spin.setValue(rng[1])

    def axis(self) -> AxisConfig:
        a = copy.deepcopy(self._axis)
        a.label = self.label_edit.text().strip()
        a.unit = self.unit_edit.text().strip()
        a.auto_range = self.auto_check.isChecked()
        a.min, a.max = self.min_spin.value(), self.max_spin.value()
        a.log = self.log_check.isChecked()
        a.inverted = self.inverted_check.isChecked()
        a.decimals = None if self.decimals_spin.value() < 0 else self.decimals_spin.value()
        a.scientific = self.scientific_check.isChecked()
        a.si_prefix = self.si_check.isChecked()
        a.color = self.color_button.color
        if a.axis_id == X_AXIS_ID:
            a.x_mode = self.x_mode_combo.currentData()
            a.x_series_id = self.x_series_combo.currentData()
        return a


def _buttons(dialog: QDialog) -> QDialogButtonBox:
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


class AxisSettingsDialog(DisposableDialog):
    def __init__(
        self,
        axis: AxisConfig,
        axis_name: str,
        series_choices: Sequence[tuple[str, str]] = (),
        auto_once: Callable[[], tuple[float, float] | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(Msg.AXIS_SETTINGS_TITLE).format(axis=axis_name))
        self.editor = AxisSettingsWidget(axis, series_choices, auto_once)
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor)
        layout.addWidget(_buttons(self))

    def axis(self) -> AxisConfig:
        return self.editor.axis()


class PlotGeneralWidget(QWidget):
    """Graph-level settings (title, background, grid, legend, sync group, subplot ratios).

    Used by the settings dialog and the toolbox: :attr:`changed` is emitted on each user
    edit (text fields when editing is finished); :meth:`set_config` does not emit it.
    """

    changed = Signal()

    def __init__(self, config: PlotConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        self.title_edit = QLineEdit(self)
        self.title_size_spin = QSpinBox(self)
        self.title_size_spin.setRange(6, 48)
        self.show_title_check = QCheckBox(tr(Msg.LBL_SHOW_TITLE), self)
        self.background_button = ColorButton(parent=self)
        self.grid_x_check = QCheckBox(tr(Msg.LBL_GRID_X), self)
        self.grid_y_check = QCheckBox(tr(Msg.LBL_GRID_Y), self)
        self.grid_alpha_spin = _spin(0.0, 1.0, 0.3, decimals=2)
        self.grid_alpha_spin.setSingleStep(0.05)
        self.legend_combo = _combo(LEGEND_CHOICES, "top-left")
        self.sync_edit = QLineEdit(self)
        self.sync_edit.setPlaceholderText(tr(Msg.LBL_SYNC_HINT))
        self.ratios_edit = QLineEdit(self)
        form.addRow(tr(Msg.LBL_TITLE), self.title_edit)
        form.addRow(tr(Msg.LBL_TITLE_SIZE), self.title_size_spin)
        form.addRow(self.show_title_check)
        form.addRow(tr(Msg.LBL_BACKGROUND), self.background_button)
        grid_row = QHBoxLayout()
        grid_row.addWidget(self.grid_x_check)
        grid_row.addWidget(self.grid_y_check)
        form.addRow(grid_row)
        form.addRow(tr(Msg.LBL_GRID_ALPHA), self.grid_alpha_spin)
        form.addRow(tr(Msg.LBL_LEGEND), self.legend_combo)
        form.addRow(tr(Msg.LBL_SYNC_GROUP), self.sync_edit)
        form.addRow(tr(Msg.LBL_RATIOS), self.ratios_edit)
        self.set_config(config)
        for edit in (self.title_edit, self.sync_edit, self.ratios_edit):
            edit.editingFinished.connect(self.changed)
        for check in (self.show_title_check, self.grid_x_check, self.grid_y_check):
            check.toggled.connect(self.changed)
        self.title_size_spin.valueChanged.connect(self.changed)
        self.grid_alpha_spin.valueChanged.connect(self.changed)
        self.legend_combo.currentIndexChanged.connect(self.changed)
        self.background_button.color_changed.connect(self.changed)

    def _widgets(self) -> tuple[QWidget, ...]:
        return (
            self.title_edit,
            self.title_size_spin,
            self.show_title_check,
            self.background_button,
            self.grid_x_check,
            self.grid_y_check,
            self.grid_alpha_spin,
            self.legend_combo,
            self.sync_edit,
            self.ratios_edit,
        )

    def set_config(self, config: PlotConfig) -> None:
        blockers = [QSignalBlocker(w) for w in self._widgets()]
        if not self.title_edit.hasFocus():
            self.title_edit.setText(config.title)
        self.title_size_spin.setValue(config.title_size)
        self.show_title_check.setChecked(config.show_title)
        self.background_button.set_color(config.background)
        self.grid_x_check.setChecked(config.show_grid_x)
        self.grid_y_check.setChecked(config.show_grid_y)
        self.grid_alpha_spin.setValue(config.grid_alpha)
        self.legend_combo.setCurrentIndex(
            max(0, self.legend_combo.findData(config.legend_position))
        )
        if not self.sync_edit.hasFocus():
            self.sync_edit.setText(config.sync_group)
        if not self.ratios_edit.hasFocus():
            self.ratios_edit.setText(", ".join(f"{sp.ratio:g}" for sp in config.subplots))
        del blockers

    def _ratios(self) -> list[float]:
        values: list[float] = []
        for part in self.ratios_edit.text().replace(";", ",").split(","):
            try:
                values.append(max(0.05, float(part.strip().replace(" ", ""))))
            except ValueError:
                values.append(1.0)
        return values

    def apply_to(self, c: PlotConfig) -> None:
        """Write the edited values into ``c`` (in place)."""
        c.title = self.title_edit.text()
        c.title_size = self.title_size_spin.value()
        c.show_title = self.show_title_check.isChecked()
        c.background = self.background_button.color or "#ffffff"
        c.show_grid_x = self.grid_x_check.isChecked()
        c.show_grid_y = self.grid_y_check.isChecked()
        c.grid_alpha = self.grid_alpha_spin.value()
        c.legend_position = self.legend_combo.currentData()
        c.sync_group = self.sync_edit.text().strip()
        for sub, ratio in zip(c.subplots, self._ratios(), strict=False):
            sub.ratio = ratio


class PlotSettingsDialog(DisposableDialog):
    """Edits a copy of a :class:`PlotConfig`; :meth:`config` returns the result."""

    def __init__(
        self,
        config: PlotConfig,
        series_choices: Sequence[tuple[str, str]] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr(Msg.PLOT_SETTINGS_TITLE))
        self._config = copy.deepcopy(config)
        tabs = QTabWidget()

        self.general = PlotGeneralWidget(config, self)
        general = self.general
        tabs.addTab(general, tr(Msg.TAB_GENERAL))

        self.x_editor = AxisSettingsWidget(config.x_axis, series_choices)
        tabs.addTab(self.x_editor, tr(Msg.TAB_X_AXIS))

        y_tab = QWidget()
        y_layout = QVBoxLayout(y_tab)
        self.y_combo = QComboBox()
        self.y_stack = QStackedWidget()
        self.y_editors: list[tuple[int, AxisSettingsWidget]] = []
        for s, sub in enumerate(config.subplots):
            for k, axis in enumerate(sub.y_axes):
                editor = AxisSettingsWidget(axis)
                self.y_editors.append((s, editor))
                self.y_stack.addWidget(editor)
                self.y_combo.addItem(tr(Msg.AXIS_Y_NAME).format(index=k + 1, subplot=s + 1))
        self.y_combo.currentIndexChanged.connect(self.y_stack.setCurrentIndex)
        y_form = QFormLayout()
        y_form.addRow(tr(Msg.LBL_AXIS), self.y_combo)
        y_layout.addLayout(y_form)
        y_layout.addWidget(self.y_stack)
        tabs.addTab(y_tab, tr(Msg.TAB_Y_AXES))

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(_buttons(self))

    def config(self) -> PlotConfig:
        c = copy.deepcopy(self._config)
        self.general.apply_to(c)
        c.x_axis = self.x_editor.axis()
        for s, editor in self.y_editors:
            axis = editor.axis()
            axes = c.subplots[s].y_axes
            for i, existing in enumerate(axes):
                if existing.axis_id == axis.axis_id:
                    axes[i] = axis
        return c
