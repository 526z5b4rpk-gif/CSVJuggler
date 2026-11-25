"""Current application state: loaded datasets (and later the layout)."""

from __future__ import annotations

import logging
import math
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.derived import (
    DERIVED_ALIAS,
    DerivedSeriesConfig,
    FormulaError,
    evaluate,
)
from csvjuggler.data.importer import (
    ImportSettings,
    ProgressCallback,
    default_alias,
    load_csv,
)
from csvjuggler.data.series import Series, split_series_id
from csvjuggler.model.annotation import (
    AnnotationStore,
    companion_path,
    load_companion,
    save_companion,
)

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
        self.annotations = AnnotationStore(self)
        self._derived: list[DerivedSeriesConfig] = []
        self.derived_errors: dict[str, str] = {}
        """Derived series name → error message of its last evaluation."""

    # -- datasets -------------------------------------------------------------------------

    @property
    def datasets(self) -> list[Dataset]:
        """File datasets, then the derived series dataset (if any)."""
        files = [d for a, d in self._datasets.items() if a != DERIVED_ALIAS]
        derived = self._datasets.get(DERIVED_ALIAS)
        return files + ([derived] if derived is not None else [])

    @property
    def file_datasets(self) -> list[Dataset]:
        return [d for a, d in self._datasets.items() if a != DERIVED_ALIAS]

    def dataset(self, alias: str) -> Dataset | None:
        return self._datasets.get(alias)

    def unique_alias(self, base: str) -> str:
        base = base.replace("/", "_") or "dataset"
        alias, n = base, 2
        while alias in self._datasets or alias == DERIVED_ALIAS:
            alias = f"{base}_{n}"
            n += 1
        return alias

    def add_dataset(self, dataset: Dataset) -> Dataset:
        if dataset.alias in self._datasets:
            dataset.rename(self.unique_alias(dataset.alias))
        self._datasets[dataset.alias] = dataset
        self._recompute_derived(emit=False)
        self.datasets_changed.emit()
        self._load_companion(dataset)
        return dataset

    # -- annotation companion files -------------------------------------------------------

    def _load_companion(self, dataset: Dataset) -> None:
        if dataset.path is None:
            return
        annotations = load_companion(dataset.path)
        for a in annotations:
            a.dataset_alias, a.dataset_path = dataset.alias, str(dataset.path)
        if annotations:
            log.info("Loaded %d annotation(s) for %s", len(annotations), dataset.alias)
        self.annotations.merge(annotations)

    def reload_companions(self) -> None:
        """Forget all annotations and read the companion files of the loaded datasets."""
        self.annotations.clear()
        for dataset in self._datasets.values():
            self._load_companion(dataset)

    def missing_series(self, series_ids: set[str]) -> list[str]:
        return sorted(sid for sid in series_ids if self.get_series(sid) is None)

    def save_companions(self) -> None:
        """Write ``<csv>.annotations.json`` for every dataset that has (or had) annotations."""
        for dataset in self._datasets.values():
            if dataset.path is None:
                continue
            annotations = self.annotations.for_dataset(dataset.alias)
            if not annotations and not companion_path(dataset.path).exists():
                continue
            try:
                save_companion(dataset.path, annotations)
            except OSError as exc:
                log.warning("Cannot write annotations next to %s: %s", dataset.path, exc)

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
        dataset.path = fresh.path
        dataset.import_settings = fresh.import_settings
        dataset.time_label = fresh.time_label
        for s in dataset.series.values():
            s.source = alias
        derived_before = self._derived_names()
        self._recompute_derived(emit=False)
        if list(dataset.series) != names_before or self._derived_names() != derived_before:
            self.datasets_changed.emit()
        self.series_data_changed.emit(alias)
        if self._derived:
            self.series_data_changed.emit(DERIVED_ALIAS)

    def remove_dataset(self, alias: str) -> None:
        if alias != DERIVED_ALIAS and self._datasets.pop(alias, None) is not None:
            self._recompute_derived(emit=False)
            self.datasets_changed.emit()

    # -- derived series -------------------------------------------------------------------

    @property
    def derived(self) -> list[DerivedSeriesConfig]:
        return list(self._derived)

    def _derived_names(self) -> list[str]:
        ds = self._datasets.get(DERIVED_ALIAS)
        return list(ds.series) if ds else []

    def check_derived(self, config: DerivedSeriesConfig) -> None:
        """Raise :class:`FormulaError` if ``config`` cannot be computed now."""
        evaluate(config, self.get_series)

    def set_derived(self, configs: list[DerivedSeriesConfig]) -> None:
        """Replace all derived series definitions (layout loading)."""
        self._derived = list(configs)
        self._recompute_derived()

    def add_derived(self, config: DerivedSeriesConfig) -> None:
        """Add or replace (same name) a derived series. Raises :class:`FormulaError`."""
        if not config.name or "/" in config.name:
            raise FormulaError("Nom de série invalide.")
        self.check_derived(config)
        self._derived = [c for c in self._derived if c.name != config.name] + [config]
        self._recompute_derived()

    def remove_derived(self, name: str) -> None:
        self._derived = [c for c in self._derived if c.name != name]
        self._recompute_derived()

    def derived_config(self, name: str) -> DerivedSeriesConfig | None:
        return next((c for c in self._derived if c.name == name), None)

    def _recompute_derived(self, emit: bool = True) -> None:
        """Evaluate every derived series (in order: one may use a previous one)."""
        dataset = self._datasets.get(DERIVED_ALIAS) or Dataset(alias=DERIVED_ALIAS)
        renames = {s.name: s.display_name for s in dataset.series.values() if s.display_name}
        dataset.series = {}
        self._datasets[DERIVED_ALIAS] = dataset
        self.derived_errors = {}
        for config in self._derived:
            try:
                series = evaluate(config, self.get_series)
            except FormulaError as exc:
                self.derived_errors[config.name] = str(exc)
                log.warning("Derived series %r: %s", config.name, exc)
                continue
            series.display_name = renames.get(config.name)
            dataset.series[config.name] = series
        if not self._derived:
            del self._datasets[DERIVED_ALIAS]
        if emit:
            self.datasets_changed.emit()
            self.series_data_changed.emit(DERIVED_ALIAS)

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

    def x_extent(self) -> tuple[float, float] | None:
        """Smallest and largest X over every series (``None`` when nothing is loaded)."""
        lo, hi = math.inf, -math.inf
        for dataset in self._datasets.values():
            for series in dataset.series.values():
                if len(series.x):
                    lo = min(lo, float(np.nanmin(series.x)))
                    hi = max(hi, float(np.nanmax(series.x)))
        return (lo, hi) if lo < hi else None

    def dataset_extents(self) -> list[tuple[str, float, float]]:
        """``(alias, first X, last X)`` of every file dataset, in loading order."""
        out: list[tuple[str, float, float]] = []
        for dataset in self.file_datasets:
            xs = [series.x for series in dataset.series.values() if len(series.x)]
            if xs:
                lo = min(float(np.nanmin(x)) for x in xs)
                hi = max(float(np.nanmax(x)) for x in xs)
                if math.isfinite(lo) and math.isfinite(hi):
                    out.append((dataset.alias, lo, hi))
        return out

    def absolute_time(self) -> bool:
        """True when every file dataset has a date/time X (epoch seconds)."""
        datasets = self.file_datasets
        return bool(datasets) and all(
            d.import_settings is not None
            and d.import_settings.time_mode == "column"
            and d.import_settings.time_unit == "datetime"
            for d in datasets
        )

    def get_series(self, series_id: str) -> Series | None:
        try:
            alias, name = split_series_id(series_id)
        except ValueError:
            return None
        dataset = self._datasets.get(alias)
        return dataset.get(name) if dataset else None
