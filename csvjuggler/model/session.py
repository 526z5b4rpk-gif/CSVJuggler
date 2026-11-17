"""Current application state: loaded datasets (and later the layout)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.importer import (
    ImportSettings,
    ProgressCallback,
    default_alias,
    load_csv,
)
from csvjuggler.data.series import Series, split_series_id

log = logging.getLogger(__name__)


class Session(QObject):
    """Owns the datasets. Passed explicitly to whoever needs it (no global state)."""

    datasets_changed = Signal()
    """A dataset was added or removed, or its series list changed."""
    series_data_changed = Signal(str)
    """The data of a dataset (alias) was reloaded."""
    series_names_changed = Signal()
    """The display name of a series changed."""

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
        self,
        path: str | Path,
        settings: ImportSettings | None = None,
        alias: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> Dataset:
        """Import a CSV file and register it. Raises ``CsvImportError`` on failure."""
        alias = self.unique_alias(alias or default_alias(path))
        return self.add_dataset(load_csv(path, settings, alias, progress))

    def reload_dataset(self, alias: str, progress: ProgressCallback | None = None) -> Dataset:
        """Read the file of ``alias`` again with the same settings (see :meth:`replace_data`)."""
        dataset = self._datasets[alias]
        if dataset.path is None:
            raise ValueError(f"Dataset {alias!r} has no file")
        fresh = load_csv(dataset.path, dataset.import_settings, alias, progress)
        self.replace_data(alias, fresh)
        return dataset

    def replace_data(self, alias: str, fresh: Dataset) -> None:
        """Replace the series of ``alias`` by those of ``fresh`` (same alias, same graphs)."""
        dataset = self._datasets[alias]
        names_before = list(dataset.series)
        dataset.series = fresh.series
        dataset.import_settings = fresh.import_settings
        dataset.time_label = fresh.time_label
        for s in dataset.series.values():
            s.source = alias
        if list(dataset.series) != names_before:
            self.datasets_changed.emit()
        self.series_data_changed.emit(alias)

    def remove_dataset(self, alias: str) -> None:
        if self._datasets.pop(alias, None) is not None:
            self.datasets_changed.emit()

    # -- series ---------------------------------------------------------------------------

    def rename_series(self, series_id: str, display_name: str | None) -> None:
        """Set the display alias of a series (the CSV is not modified)."""
        series = self.get_series(series_id)
        if series is None:
            return
        display_name = (display_name or "").strip() or None
        if display_name == series.name:
            display_name = None
        if display_name == series.display_name:
            return
        series.display_name = display_name
        dataset = self._datasets[series.source]
        if dataset.import_settings is not None:
            if display_name is None:
                dataset.import_settings.renames.pop(series.name, None)
            else:
                dataset.import_settings.renames[series.name] = display_name
        self.series_names_changed.emit()

    def get_series(self, series_id: str) -> Series | None:
        try:
            alias, name = split_series_id(series_id)
        except ValueError:
            return None
        dataset = self._datasets.get(alias)
        return dataset.get(name) if dataset else None
