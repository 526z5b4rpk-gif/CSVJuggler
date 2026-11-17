"""« Lecture X » bar: a slider (and play button) driving a cursor shown on every graph."""

from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QToolButton,
    QWidget,
)

from csvjuggler.i18n import Msg, tr

SLIDER_STEPS = 10_000
PLAY_INTERVAL_MS = 30
SPEEDS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0)


class TimeSliderBar(QWidget):
    position_changed = Signal(float)
    visibility_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.lo, self.hi = 0.0, 1.0
        self.position = 0.0
        self._updating = False

        self.show_check = QCheckBox(tr(Msg.SLIDER_SHOW))
        self.show_check.setToolTip(tr(Msg.SLIDER_SHOW_TIP))
        self.play_button = QToolButton()
        self.play_button.setCheckable(True)
        self.play_button.setText("▶")
        self.play_button.setToolTip(tr(Msg.SLIDER_PLAY_TIP))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setMinimumWidth(300)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(6)
        self.spin.setMinimumWidth(110)
        self.spin.setKeyboardTracking(False)
        self.speed_combo = QComboBox()
        for speed in SPEEDS:
            self.speed_combo.addItem(f"x{speed:g}", speed)
        self.speed_combo.setCurrentIndex(SPEEDS.index(1.0))
        self.speed_combo.setToolTip(tr(Msg.SLIDER_SPEED_TIP))
        self.follow_check = QCheckBox(tr(Msg.SLIDER_FOLLOW))
        self.follow_check.setToolTip(tr(Msg.SLIDER_FOLLOW_TIP))
        self.follow_check.setChecked(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.addWidget(QLabel(tr(Msg.SLIDER_LABEL)))
        layout.addWidget(self.show_check)
        layout.addWidget(self.play_button)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.spin)
        layout.addWidget(self.speed_combo)
        layout.addWidget(self.follow_check)

        self._timer = QTimer(self)
        self._timer.setInterval(PLAY_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()

        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)
        self.show_check.toggled.connect(self.visibility_changed)
        self.play_button.toggled.connect(self._on_play_toggled)
        self.set_range(None)

    # -- range / position -----------------------------------------------------------------

    def set_range(self, extent: tuple[float, float] | None) -> None:
        """X extent of the data (``None``: nothing loaded)."""
        has_data = extent is not None and math.isfinite(extent[0]) and extent[1] > extent[0]
        for widget in (self.slider, self.spin, self.play_button, self.show_check):
            widget.setEnabled(has_data)
        if not has_data:
            self.set_playing(False)
            return
        assert extent is not None
        self.lo, self.hi = extent
        self._updating = True
        try:
            self.spin.setRange(self.lo, self.hi)
            self.spin.setSingleStep((self.hi - self.lo) / 1000)
        finally:
            self._updating = False
        self.set_position(min(max(self.position, self.lo), self.hi), emit=False)

    def set_position(self, x: float, emit: bool = True) -> None:
        self.position = x
        self._updating = True
        try:
            frac = (x - self.lo) / (self.hi - self.lo) if self.hi > self.lo else 0.0
            self.slider.setValue(round(frac * SLIDER_STEPS))
            self.spin.setValue(x)
        finally:
            self._updating = False
        if emit:
            if not self.show_check.isChecked():
                self.show_check.setChecked(True)  # moving the bar shows the cursor
            self.position_changed.emit(x)

    @property
    def cursor_visible(self) -> bool:
        return self.show_check.isChecked()

    @property
    def follow(self) -> bool:
        return self.follow_check.isChecked()

    def _on_slider(self, value: int) -> None:
        if not self._updating:
            self.set_position(self.lo + (self.hi - self.lo) * value / SLIDER_STEPS)

    def _on_spin(self, value: float) -> None:
        if not self._updating:
            self.set_position(value)

    # -- playback -------------------------------------------------------------------------

    @property
    def speed(self) -> float:
        return float(self.speed_combo.currentData())

    @property
    def playing(self) -> bool:
        return self._timer.isActive()

    def set_playing(self, playing: bool) -> None:
        if self.play_button.isChecked() != playing:
            self.play_button.setChecked(playing)

    def _on_play_toggled(self, playing: bool) -> None:
        self.play_button.setText("⏸" if playing else "▶")
        if playing:
            if self.position >= self.hi:
                self.set_position(self.lo, emit=False)
            self._clock.start()
            self._timer.start()
        else:
            self._timer.stop()

    def advance(self, seconds: float) -> None:
        """Move forward by ``seconds`` of real time at the current speed."""
        x = self.position + seconds * self.speed
        if x >= self.hi:
            x = self.hi
            self.set_playing(False)
        self.set_position(x)

    def _tick(self) -> None:
        self.advance(self._clock.restart() / 1000.0)
