"""CSV export of series over an X interval.

Series sharing the same X vector are written as one time column plus one column per
series; otherwise every series gets its own time/value pair of columns (like Scope).
The exported values are the series data (display gain/offset are not applied).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from csvjuggler.data.series import Series


@dataclass
class CsvExportOptions:
    delimiter: str = ","
    decimal: str = "."
    time_label: str = "time"


def _slice(series: Series, x0: float, x1: float) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = min(x0, x1), max(x0, x1)
    mask = (series.x >= lo) & (series.x <= hi)
    return series.x[mask], series.y[mask]


def _same_x(series: list[Series]) -> bool:
    first = series[0].x
    return all(s.x is first or np.array_equal(s.x, first) for s in series[1:])


def export_csv(
    path: str | Path,
    series: list[Series],
    x0: float,
    x1: float,
    options: CsvExportOptions | None = None,
) -> int:
    """Write ``series`` restricted to ``[x0, x1]``. Returns the number of data rows."""
    options = options or CsvExportOptions()
    if not series:
        raise ValueError("Aucune série à exporter.")
    labels = _unique([s.label for s in series])
    if _same_x(series):
        x, _ = _slice(series[0], x0, x1)
        columns = {options.time_label: x}
        for label, s in zip(labels, series, strict=True):
            columns[label] = _slice(s, x0, x1)[1]
        frame = pd.DataFrame(columns)
    else:
        parts = []
        for label, s in zip(labels, series, strict=True):
            x, y = _slice(s, x0, x1)
            parts.append(pd.DataFrame({f"{options.time_label} ({label})": x, label: y}))
        frame = pd.concat(parts, axis=1)
    frame.to_csv(
        path,
        sep=options.delimiter,
        decimal=options.decimal,
        index=False,
        float_format="%.10g",
        encoding="utf-8",
    )
    return len(frame)


def _unique(labels: list[str]) -> list[str]:
    out: list[str] = []
    for label in labels:
        candidate, n = label, 2
        while candidate in out:
            candidate = f"{label}_{n}"
            n += 1
        out.append(candidate)
    return out
