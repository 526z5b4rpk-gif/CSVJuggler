"""CSV → Dataset.

The file is analysed line by line (header block, units, data start), then the numeric block
is read by pandas in chunks so that progress can be reported and the import cancelled.

Supported layouts:

- one header row (or none) and one time column, or the row index as time;
- a metadata block before the data (TwinCAT Scope: Name, SymbolName, DataType, Unit…);
  the user chooses which line gives the column names and which one gives the units;
- time/value pairs (one time column per channel), each series keeping its own X vector.

The resulting :class:`ImportSettings` is stored with the dataset (and in the layout) so the
file can be re-read identically.
"""

from __future__ import annotations

import csv
import logging
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from csvjuggler.data import scope_importer
from csvjuggler.data.dataset import Dataset
from csvjuggler.data.series import Series

log = logging.getLogger(__name__)

TimeMode = Literal["column", "pairs", "index"]
TimeUnit = Literal["s", "ms", "us", "datetime"]
ProgressCallback = Callable[[float], bool]
"""Receives the progress in [0, 1]; returns ``False`` to cancel."""

SNIFF_BYTES = 64 * 1024
SNIFF_LINES = 200
CHUNK_ROWS = 200_000
DELIMITER_CANDIDATES = ("\t", ";", ",")  # order = preference when several are consistent
TIME_NAME_HINTS = ("time", "temps", "t", "timestamp", "zeit", "seconds", "s", "horodatage")
TIME_SCALE: dict[str, float] = {"s": 1.0, "ms": 1e-3, "us": 1e-6}

_DECIMAL_COMMA_RE = re.compile(r"^\s*[+-]?\d+,\d+(?:[eE][+-]?\d+)?\s*$")
_DATETIME_RE = re.compile(
    r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2}([.,]\d+)?)?)?"
)
_UNIT_IN_NAME_RE = re.compile(r"^(.*?)\s*[\[(]([^\])]+)[\])]\s*$")


class CsvImportError(Exception):
    """Raised when a file cannot be turned into a dataset."""


class CsvImportCancelled(CsvImportError):
    """The user cancelled the import."""


@dataclass
class ImportSettings:
    encoding: str = "utf-8"
    delimiter: str = ","
    decimal: str = "."
    header_row: int | None = 0
    """Line (0-based, physical) giving the column names. ``None`` → col1, col2…"""
    unit_row: int | None = None
    """Line giving the units, if any."""
    data_start: int = 1
    """First line of numeric data."""
    time_mode: TimeMode = "column"
    time_column: str | None = None
    """Column used as x when ``time_mode == "column"``."""
    time_unit: TimeUnit = "s"
    datetime_format: str = ""
    """``strptime`` format when ``time_unit == "datetime"``; empty → automatic."""
    renames: dict[str, str] = field(default_factory=dict)
    """Column name → display alias."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportSettings:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class ImportPreview:
    """What the import dialog needs to show."""

    settings: ImportSettings
    lines: list[str]
    """First physical lines of the file (empty lines included)."""
    columns: list[str]
    """Resolved column names, in file order."""
    units: dict[str, str]
    series_names: list[str]
    """Names of the series that will be created."""
    time_candidates: list[str]
    is_scope: bool = False


# --------------------------------------------------------------------------- low level


def detect_encoding(raw: bytes) -> str:
    """UTF-8 (with or without BOM), falling back to cp1252."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # A multi-byte character cut by the sample boundary is not an error.
        if exc.start < len(raw) - 3:
            return "cp1252"
    return "utf-8"


def read_head_lines(path: Path, encoding: str, count: int = SNIFF_LINES) -> list[str]:
    """First ``count`` physical lines, without line terminators (empty lines kept)."""
    lines: list[str] = []
    with path.open("r", encoding=encoding, errors="replace", newline="") as fh:
        for line in fh:
            lines.append(line.rstrip("\r\n"))
            if len(lines) >= count:
                break
    return lines


def split_line(line: str, delimiter: str) -> list[str]:
    try:
        return [f.strip() for f in next(csv.reader([line], delimiter=delimiter))]
    except (StopIteration, csv.Error):
        return []


def detect_delimiter(lines: list[str]) -> str:
    """Pick the first candidate whose count is identical and non-zero on most lines.

    Only the second half of the sample is used: it is data, not the metadata block.
    """
    lines = [ln for ln in lines if ln.strip()]
    lines = lines[len(lines) // 2 :] if len(lines) > 4 else lines
    if not lines:
        return ","
    for cand in DELIMITER_CANDIDATES:
        counts = [line.count(cand) for line in lines]
        mode = max(set(counts), key=counts.count)
        if mode > 0 and counts.count(mode) >= 0.9 * len(counts):
            return cand
    return ","


def detect_decimal(lines: list[str], delimiter: str) -> str:
    """Comma decimals are only possible when the column separator is not a comma."""
    if delimiter == ",":
        return "."
    comma = dot = 0
    for line in lines:
        for field_ in split_line(line, delimiter):
            if _DECIMAL_COMMA_RE.match(field_):
                comma += 1
            elif "." in field_ and _to_float(field_, ".") is not None:
                dot += 1
    return "," if comma > dot else "."


def _to_float(text: str, decimal: str) -> float | None:
    text = text.strip()
    if decimal == ",":
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _is_data_line(fields_: list[str], decimal: str) -> bool:
    """A data line has at least one number and only numbers, dates or empty fields."""
    has_number = False
    for f in fields_:
        if not f:
            continue
        if _to_float(f, decimal) is not None:
            has_number = True
        elif not _DATETIME_RE.match(f):
            return False
    return has_number


def detect_data_start(lines: list[str], delimiter: str, decimal: str) -> int:
    """First line from which the next (up to 5) non-empty lines are all data lines."""
    flags = [
        (i, _is_data_line(split_line(ln, delimiter), decimal))
        for i, ln in enumerate(lines)
        if ln.strip()
    ]
    for k, (i, is_data) in enumerate(flags):
        if is_data and all(d for _, d in flags[k : k + 5]):
            return i
    return len(lines)


def _first_field_matches(line: str, delimiter: str, pattern: str) -> bool:
    fields_ = split_line(line, delimiter)
    return bool(fields_) and re.match(pattern, fields_[0], re.IGNORECASE) is not None


def detect_header_rows(
    lines: list[str], delimiter: str, data_start: int
) -> tuple[int | None, int | None]:
    """``(header_row, unit_row)`` among the lines before ``data_start``."""
    before = [i for i in range(data_start) if lines[i].strip() and split_line(lines[i], delimiter)]
    if not before:
        return None, None
    named = [i for i in before if _first_field_matches(lines[i], delimiter, r"^name$")]
    header = named[-1] if named else before[-1]
    units = [
        i for i in before if _first_field_matches(lines[i], delimiter, r"^(unit|unité|einheit)")
    ]
    unit = units[-1] if units and units[-1] != header else None
    return header, unit


def _unique_names(raw: list[str]) -> list[str]:
    names: list[str] = []
    for i, name in enumerate(raw):
        base = name or f"col{i + 1}"
        candidate, n = base, 2
        while candidate in names:
            candidate = f"{base}_{n}"
            n += 1
        names.append(candidate)
    return names


def _raw_row(lines: list[str], row: int | None, delimiter: str, width: int) -> list[str]:
    fields_ = split_line(lines[row], delimiter) if row is not None and row < len(lines) else []
    return (fields_ + [""] * width)[:width]


def _data_width(lines: list[str], settings: ImportSettings) -> int:
    widths = [
        len(split_line(ln, settings.delimiter)) for ln in lines[settings.data_start :] if ln.strip()
    ]
    return max(widths, default=0)


def _column_layout(
    lines: list[str], settings: ImportSettings
) -> tuple[list[str], list[str], dict[str, str]]:
    """``(raw header fields, unique column names, units by column)``."""
    width = _data_width(lines, settings)
    raw = _raw_row(lines, settings.header_row, settings.delimiter, width)
    names = _unique_names(raw)
    unit_fields = _raw_row(lines, settings.unit_row, settings.delimiter, width)
    units: dict[str, str] = {}
    for name, unit in zip(names, unit_fields, strict=True):
        if settings.unit_row is not None and unit:
            units[name] = unit
        elif m := _UNIT_IN_NAME_RE.match(name):
            units[name] = m.group(2).strip()
    return raw, names, units


def _pairs(names: list[str], raw: list[str]) -> list[tuple[str, str, str]]:
    """``(time column, value column, series name)`` for time/value pairs."""
    out = []
    for k in range(0, len(names) - 1, 2):
        series_name = raw[k + 1] or names[k + 1]
        out.append((names[k], names[k + 1], series_name))
    return out


def _series_names(settings: ImportSettings, names: list[str], raw: list[str]) -> list[str]:
    if settings.time_mode == "pairs":
        return _unique_names([s for _, _, s in _pairs(names, raw)])
    return [n for n in names if n != settings.time_column or settings.time_mode == "index"]


# --------------------------------------------------------------------------- reading


def _read_frame(
    path: Path,
    settings: ImportSettings,
    names: list[str],
    nrows: int | None = None,
    progress: ProgressCallback | None = None,
    avg_line_bytes: float = 0.0,
) -> pd.DataFrame:
    """Read the data block (no header) with columns named ``names``."""
    kwargs: dict[str, Any] = {
        "sep": settings.delimiter,
        "decimal": settings.decimal,
        "encoding": settings.encoding,
        "header": None,
        "names": names,
        "skiprows": settings.data_start,
        "skip_blank_lines": True,
        "skipinitialspace": True,
        "index_col": False,
    }
    if nrows is not None:
        return pd.read_csv(path, nrows=nrows, **kwargs)

    total_bytes = max(1, path.stat().st_size)
    chunks: list[pd.DataFrame] = []
    rows = 0
    with pd.read_csv(path, chunksize=CHUNK_ROWS, **kwargs) as reader:
        for chunk in reader:
            chunks.append(chunk)
            rows += len(chunk)
            if progress is not None and not progress(
                min(0.99, rows * avg_line_bytes / total_bytes)
            ):
                raise CsvImportCancelled("Import annulé.")
    if not chunks:
        return pd.DataFrame(columns=names)
    return pd.concat(chunks, ignore_index=True)


def _numeric(values: pd.Series) -> np.ndarray:
    if not pd.api.types.is_numeric_dtype(values):
        values = pd.to_numeric(values, errors="coerce")
    return values.to_numpy(dtype=np.float64)


def _time_values(values: pd.Series, settings: ImportSettings) -> np.ndarray:
    if settings.time_unit == "datetime":
        stamps = pd.to_datetime(values, format=settings.datetime_format or None, errors="coerce")
        seconds = (stamps - pd.Timestamp("1970-01-01")).dt.total_seconds()
        return seconds.to_numpy(dtype=np.float64)
    return _numeric(values) * TIME_SCALE.get(settings.time_unit, 1.0)


def time_column_candidates(df: pd.DataFrame) -> list[str]:
    """Numeric, non-constant, monotonically increasing columns, best guesses first."""
    candidates: list[str] = []
    for col in df.columns:
        values = df[col]
        if not pd.api.types.is_numeric_dtype(values):
            continue
        values = values.dropna()
        if len(values) < 2 or not values.is_monotonic_increasing:
            continue
        if values.iloc[0] == values.iloc[-1]:
            continue
        candidates.append(str(col))

    def rank(name: str) -> tuple[int, int]:
        base = re.split(r"[\s\[(_]", name.strip().lower(), maxsplit=1)[0]
        return (0 if base in TIME_NAME_HINTS else 1, candidates.index(name))

    return sorted(candidates, key=rank)


def _datetime_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        values = df[col].dropna()
        if values.empty or pd.api.types.is_numeric_dtype(values):
            continue
        if values.astype(str).str.match(_DATETIME_RE).mean() > 0.9:
            return str(col)
    return None


def _looks_like_pairs(df: pd.DataFrame, raw: list[str], is_scope: bool) -> bool:
    n = len(df.columns)
    if n < 4 or n % 2:
        return False
    for k in range(0, n, 2):
        col = pd.to_numeric(df.iloc[:, k], errors="coerce").dropna()
        if len(col) < 2 or not col.is_monotonic_increasing:
            return False
    if is_scope:
        return True
    even = [raw[k].lower() for k in range(0, n, 2)]
    return (
        all(not h for h in even)
        or len(set(even)) == 1
        or all(re.split(r"[\s\[(_]", h, maxsplit=1)[0] in TIME_NAME_HINTS for h in even)
    )


# --------------------------------------------------------------------------- public API


def detect_settings(path: str | Path) -> ImportSettings:
    """Guess the import settings of a CSV file."""
    return analyze(path).settings


def analyze(path: str | Path, settings: ImportSettings | None = None) -> ImportPreview:
    """Analyse ``path``. Missing ``settings`` are detected; given ones are only resolved."""
    path = Path(path)
    if not path.is_file():
        raise CsvImportError(f"Fichier introuvable : {path}")
    detect = settings is None
    if settings is None:
        with path.open("rb") as fh:
            raw_bytes = fh.read(SNIFF_BYTES)
        settings = ImportSettings(encoding=detect_encoding(raw_bytes))
    lines = read_head_lines(path, settings.encoding)
    is_scope = scope_importer.is_scope_export(lines)

    if detect:
        settings.delimiter = detect_delimiter(lines)
        # First pass with "," accepts both decimal separators (see _to_float).
        start = detect_data_start(lines, settings.delimiter, ",")
        settings.decimal = detect_decimal(lines[start:], settings.delimiter)
        settings.data_start = detect_data_start(lines, settings.delimiter, settings.decimal)
        settings.header_row, settings.unit_row = detect_header_rows(
            lines, settings.delimiter, settings.data_start
        )

    raw, names, units = _column_layout(lines, settings)
    try:
        sample = _read_frame(path, settings, names, nrows=SNIFF_LINES) if names else None
    except (ValueError, pd.errors.ParserError) as exc:
        raise CsvImportError(str(exc)) from exc
    candidates = time_column_candidates(sample) if sample is not None else []
    dt_col = _datetime_column(sample) if sample is not None else None
    if dt_col is not None:
        candidates.insert(0, dt_col)

    if detect and sample is not None:
        if _looks_like_pairs(sample, raw, is_scope):
            settings.time_mode = "pairs"
        elif dt_col is not None:
            settings.time_mode, settings.time_column, settings.time_unit = (
                "column",
                dt_col,
                "datetime",
            )
        elif candidates:
            settings.time_mode, settings.time_column = "column", candidates[0]
        else:
            settings.time_mode = "index"
        if is_scope:
            scope_importer.apply_defaults(settings)
        log.debug("Detected settings for %s: %s", path, settings)

    if settings.time_mode == "pairs":
        units = {s: units.get(v, "") for (_, v, s) in _pairs(names, raw)} | units
    return ImportPreview(
        settings=settings,
        lines=lines,
        columns=names,
        units=units,
        series_names=_series_names(settings, names, raw),
        time_candidates=candidates,
        is_scope=is_scope,
    )


def default_alias(path: str | Path) -> str:
    """Default dataset alias: the file name without extension, without ``/``."""
    return Path(path).stem.replace("/", "_") or "dataset"


def load_csv(
    path: str | Path,
    settings: ImportSettings | None = None,
    alias: str | None = None,
    progress: ProgressCallback | None = None,
) -> Dataset:
    """Read ``path`` into a :class:`Dataset`. Settings are detected when not given."""
    path = Path(path)
    preview = analyze(path, settings)
    settings = preview.settings
    lines = preview.lines
    raw, names, units = _column_layout(lines, settings)
    if not names:
        raise CsvImportError("Aucune donnée numérique trouvée.")
    data_lines = [ln for ln in lines[settings.data_start :] if ln.strip()]
    avg = (sum(len(ln.encode()) + 1 for ln in data_lines) / len(data_lines)) if data_lines else 1
    try:
        df = _read_frame(path, settings, names, progress=progress, avg_line_bytes=avg)
    except CsvImportCancelled:
        raise
    except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise CsvImportError(str(exc)) from exc

    alias = alias or default_alias(path)
    dataset = Dataset(alias=alias, path=path.resolve(), import_settings=settings)

    def add(name: str, x: np.ndarray, y: np.ndarray, unit: str) -> None:
        mask = np.isfinite(x) & np.isfinite(y)
        if not mask.all():
            x, y = x[mask], y[mask]
        if len(y) == 0:
            return
        x.flags.writeable = False
        dataset.series[name] = Series(
            name=name,
            x=x,
            y=y,
            source=alias,
            unit=unit,
            display_name=settings.renames.get(name),
        )

    if settings.time_mode == "pairs":
        pairs = _pairs(names, raw)
        series_names = _unique_names([s for _, _, s in pairs])
        for (t_col, v_col, _), name in zip(pairs, series_names, strict=True):
            x = _time_values(df[t_col], settings)
            add(name, x, _numeric(df[v_col]), units.get(v_col, ""))
        dataset.time_label = "pairs"
    else:
        time_col = settings.time_column if settings.time_mode == "column" else None
        if time_col is not None and time_col not in df.columns:
            log.warning("Time column %r missing in %s, using row index", time_col, path)
            time_col = None
        if time_col is None:
            x = np.arange(len(df), dtype=np.float64)
        else:
            x = _time_values(df[time_col], settings)
        for col in names:
            if col == time_col:
                continue
            add(col, x, _numeric(df[col]), units.get(col, ""))
        dataset.time_label = time_col or ""

    if not dataset.series:
        raise CsvImportError("Aucune donnée numérique trouvée.")
    if progress is not None:
        progress(1.0)
    log.info("Loaded %s as %r: %d series, %d rows", path, alias, len(dataset.series), len(df))
    return dataset
