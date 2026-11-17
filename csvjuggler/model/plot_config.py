"""Serialisable configuration of plots and curves.

Widgets apply these objects (``apply_config``) and report every change through
``config_changed``, so what is displayed is always what gets saved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, TypeVar

T = TypeVar("T")


def _known_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys that are dataclass fields (forward compatibility)."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in names}


@dataclass
class CurveConfig:
    series_id: str
    color: str
    width: float = 1.0
    alias: str | None = None
    """Display name; ``None`` → the series label."""
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurveConfig:
        return cls(**_known_fields(cls, data))


@dataclass
class PlotConfig:
    title: str = ""
    show_grid_x: bool = True
    show_grid_y: bool = True
    grid_alpha: float = 0.3
    show_legend: bool = True
    curves: list[CurveConfig] = field(default_factory=list)

    def curve(self, series_id: str) -> CurveConfig | None:
        return next((c for c in self.curves if c.series_id == series_id), None)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["curves"] = [c.to_dict() for c in self.curves]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlotConfig:
        kwargs = _known_fields(cls, data)
        kwargs["curves"] = [CurveConfig.from_dict(c) for c in data.get("curves", [])]
        return cls(**kwargs)
