"""Serialisable configuration of plots, subplots, axes and curves.

Widgets apply these objects (``apply_config``) and report every change through
``config_changed``, so what is displayed is always what gets saved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

GLOBAL_SYNC_GROUP = "global"
X_AXIS_ID = "x"
PRIMARY_Y_AXIS_ID = "y0"

LineStyle = Literal["solid", "dash", "dot"]
Marker = Literal["none", "o", "s", "x"]
CurveMode = Literal["line", "step", "points"]
LegendPosition = Literal["top-left", "top-right", "bottom-left", "bottom-right", "hidden"]
XMode = Literal["relative", "absolute", "series"]
AxisSide = Literal["left", "right"]


def _known_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys that are dataclass fields (forward compatibility)."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


@dataclass
class AxisConfig:
    axis_id: str = PRIMARY_Y_AXIS_ID
    label: str = ""
    unit: str = ""
    auto_range: bool = True
    min: float = 0.0
    max: float = 1.0
    log: bool = False
    inverted: bool = False
    decimals: int | None = None
    """Fixed number of decimals for tick labels; ``None`` → automatic."""
    scientific: bool = False
    si_prefix: bool = False
    color: str | None = None
    """``None`` → default (foreground, or the first curve's colour for secondary axes)."""
    side: AxisSide = "left"
    x_mode: XMode = "relative"
    """X axis only: relative time (s), absolute date/time, or a series (XY mode)."""
    x_series_id: str | None = None

    @property
    def title(self) -> str:
        """``Libellé [unité]``."""
        if self.label and self.unit:
            return f"{self.label} [{self.unit}]"
        return self.label or (f"[{self.unit}]" if self.unit else "")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AxisConfig:
        return cls(**_known_fields(cls, data))


@dataclass
class CurveConfig:
    series_id: str
    color: str
    width: float = 1.0
    alias: str | None = None
    """Display name; ``None`` → the series label."""
    visible: bool = True
    style: LineStyle = "solid"
    marker: Marker = "none"
    marker_size: float = 6.0
    mode: CurveMode = "line"
    gain: float = 1.0
    offset: float = 0.0
    """Displayed y = gain * y + offset (the data is not modified)."""
    axis_id: str = PRIMARY_Y_AXIS_ID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurveConfig:
        return cls(**_known_fields(cls, data))


@dataclass
class SubplotConfig:
    """One of the vertically stacked plots of a graph (they share the X axis)."""

    ratio: float = 1.0
    y_axes: list[AxisConfig] = field(default_factory=lambda: [AxisConfig()])
    """First = primary axis (left); the others are secondary axes."""
    curves: list[CurveConfig] = field(default_factory=list)

    def curve(self, series_id: str) -> CurveConfig | None:
        return next((c for c in self.curves if c.series_id == series_id), None)

    def axis(self, axis_id: str) -> AxisConfig | None:
        return next((a for a in self.y_axes if a.axis_id == axis_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ratio": self.ratio,
            "y_axes": [a.to_dict() for a in self.y_axes],
            "curves": [c.to_dict() for c in self.curves],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubplotConfig:
        return cls(
            ratio=float(data.get("ratio", 1.0)),
            y_axes=[AxisConfig.from_dict(a) for a in data.get("y_axes", [])] or [AxisConfig()],
            curves=[CurveConfig.from_dict(c) for c in data.get("curves", [])],
        )


@dataclass
class PlotConfig:
    title: str = ""
    title_size: int = 12
    show_title: bool = True
    background: str = "#ffffff"
    show_grid_x: bool = True
    show_grid_y: bool = True
    grid_alpha: float = 0.3
    legend_position: LegendPosition = "top-left"
    sync_group: str = GLOBAL_SYNC_GROUP
    """Plots sharing a non-empty group name have synchronised X ranges."""
    x_axis: AxisConfig = field(default_factory=lambda: AxisConfig(axis_id=X_AXIS_ID))
    subplots: list[SubplotConfig] = field(default_factory=lambda: [SubplotConfig()])

    def all_curves(self) -> list[CurveConfig]:
        return [c for sp in self.subplots for c in sp.curves]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["x_axis"] = self.x_axis.to_dict()
        data["subplots"] = [sp.to_dict() for sp in self.subplots]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlotConfig:
        kwargs = _known_fields(cls, data)
        kwargs["x_axis"] = AxisConfig.from_dict(data.get("x_axis") or {"axis_id": X_AXIS_ID})
        kwargs["subplots"] = [SubplotConfig.from_dict(s) for s in data.get("subplots", [])] or [
            SubplotConfig()
        ]
        return cls(**kwargs)
