"""A single time series: an x vector, a y vector and some metadata."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def make_series_id(dataset_alias: str, name: str) -> str:
    """Build the stable identifier ``"<alias_dataset>/<nom_colonne>"``."""
    return f"{dataset_alias}/{name}"


def split_series_id(series_id: str) -> tuple[str, str]:
    """Split an identifier into ``(dataset_alias, column_name)``.

    Dataset aliases never contain ``/`` so the first separator is the right one;
    column names may contain ``/``.
    """
    alias, sep, name = series_id.partition("/")
    if not sep:
        raise ValueError(f"Invalid series id: {series_id!r}")
    return alias, name


@dataclass(eq=False)
class Series:
    """A numeric series. ``x`` and ``y`` have the same length.

    Several series of a dataset may share the same ``x`` array (no copy).
    """

    name: str
    x: np.ndarray
    y: np.ndarray
    source: str
    """Alias of the dataset the series comes from."""
    unit: str = ""
    display_name: str | None = None
    """Display alias; ``None`` means use :attr:`name`."""

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y):
            raise ValueError(
                f"Series {self.name!r}: x and y lengths differ ({len(self.x)} != {len(self.y)})"
            )

    @property
    def id(self) -> str:
        return make_series_id(self.source, self.name)

    @property
    def label(self) -> str:
        return self.display_name or self.name

    def __len__(self) -> int:
        return len(self.y)
