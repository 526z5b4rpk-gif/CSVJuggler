"""Pure measurement functions: value at a given x, statistics over an X interval, TSV."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

Interpolation = Literal["linear", "nearest"]


def value_at(x: np.ndarray, y: np.ndarray, x0: float, mode: Interpolation = "linear") -> float:
    """y at ``x0`` for increasing ``x``; NaN outside the data range."""
    n = len(x)
    if n == 0 or not math.isfinite(x0) or x0 < x[0] or x0 > x[-1]:
        return math.nan
    i = int(np.searchsorted(x, x0))
    if i == 0:
        return float(y[0])
    if i >= n:
        return float(y[-1])
    x_lo, x_hi = x[i - 1], x[i]
    if mode == "nearest":
        return float(y[i - 1] if x0 - x_lo <= x_hi - x0 else y[i])
    if x_hi == x_lo:
        return float(y[i])
    t = (x0 - x_lo) / (x_hi - x_lo)
    return float(y[i - 1] + t * (y[i] - y[i - 1]))


def nearest_value(x: np.ndarray, y: np.ndarray, x0: float) -> float:
    """Value of the sample whose x is closest to ``x0`` (any x order, e.g. XY mode)."""
    finite = np.isfinite(x)
    if not finite.any():
        return math.nan
    idx = int(np.nanargmin(np.abs(np.where(finite, x, np.nan) - x0)))
    return float(y[idx])


@dataclass(frozen=True)
class Stats:
    count: int
    min: float
    max: float
    mean: float
    std: float
    rms: float

    @property
    def peak_to_peak(self) -> float:
        return self.max - self.min


EMPTY_STATS = Stats(0, math.nan, math.nan, math.nan, math.nan, math.nan)


def interval_stats(x: np.ndarray, y: np.ndarray, x0: float, x1: float) -> Stats:
    """Statistics of the samples with ``x0 <= x <= x1`` (bounds in any order)."""
    lo, hi = min(x0, x1), max(x0, x1)
    if len(x) and np.all(np.diff(x[: min(len(x), 1000)]) >= 0):
        i0, i1 = np.searchsorted(x, lo, "left"), np.searchsorted(x, hi, "right")
        values = y[i0:i1]
    else:
        values = y[(x >= lo) & (x <= hi)]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return EMPTY_STATS
    return Stats(
        count=int(values.size),
        min=float(values.min()),
        max=float(values.max()),
        mean=float(values.mean()),
        std=float(values.std()),
        rms=float(np.sqrt(np.mean(np.square(values)))),
    )


def format_number(value: float, digits: int = 6) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.{digits}g}"


def to_tsv(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    """Tab-separated text (pastes into spreadsheets)."""
    lines = ["\t".join(headers)]
    for row in rows:
        lines.append("\t".join(format_number(v) if isinstance(v, float) else str(v) for v in row))
    return "\n".join(lines) + "\n"
