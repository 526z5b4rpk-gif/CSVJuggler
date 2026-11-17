"""Current application state: loaded datasets (and later the layout)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.importer import ImportSettings, default_alias, load_csv
from csvjuggler.data.series import Series, split_series_id

log = logging.getLogger(__name__)


class Session(QObject):
    """Owns the datasets. Passed explicitly to whoever needs it (no global state)."""

    datasets_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._datasets: dict[str, Dataset] = {}

    # -- datasets -------------------------------------------------------------------------

    @property
    def datasets(self) -> list[Dataset]:
        return list(self._datasets.values())

    def dataset(self, alias: str) -> Dataset | None:
        return self._datasets.get(alias)

    def unique_alias(self, base: str) -> str:
        base = base.replace("/", "_") or "dataset"
        alias, n = base, 2
        while alias in self._datasets:
            alias = f"{base}_{n}"
            n += 1
        return alias

    def add_dataset(self, dataset: Dataset) -> Dataset:
        if dataset.alias in self._datasets:
            dataset.rename(self.unique_alias(dataset.alias))
        self._datasets[dataset.alias] = dataset
        self.datasets_changed.emit()
        return dataset

    def load_csv(
        self, path: str | Path, settings: ImportSettings | None = None, alias: str | None = None
    ) -> Dataset:
        """Import a CSV file and register it. Raises ``CsvImportError`` on failure."""
        alias = self.unique_alias(alias or default_alias(path))
        return self.add_dataset(load_csv(path, settings, alias))

    def remove_dataset(self, alias: str) -> None:
        if self._datasets.pop(alias, None) is not None:
            self.datasets_changed.emit()

    # -- series ---------------------------------------------------------------------------

    def get_series(self, series_id: str) -> Series | None:
        try:
            alias, name = split_series_id(series_id)
        except ValueError:
            return None
        dataset = self._datasets.get(alias)
        return dataset.get(name) if dataset else None
