"""A Dataset groups the series read from one source (a CSV file for now).

The class is source-agnostic so that live sources (ADS, MQTT…) can be added later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from csvjuggler.data.series import Series, make_series_id

if TYPE_CHECKING:
    from csvjuggler.data.importer import ImportSettings


@dataclass(eq=False)
class Dataset:
    alias: str
    series: dict[str, Series] = field(default_factory=dict)
    """Series keyed by column name, in file order."""
    path: Path | None = None
    import_settings: ImportSettings | None = None
    time_label: str = ""
    """Name of the column used as x (or empty when the row index is used)."""

    def series_id(self, name: str) -> str:
        return make_series_id(self.alias, name)

    def get(self, name: str) -> Series | None:
        return self.series.get(name)

    def rename(self, alias: str) -> None:
        """Change the alias of the dataset and of its series."""
        self.alias = alias
        for s in self.series.values():
            s.source = alias

    @property
    def point_count(self) -> int:
        return sum(len(s) for s in self.series.values())
