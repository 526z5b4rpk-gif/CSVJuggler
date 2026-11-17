"""CSV → Dataset.

Phase 1 scope: a single header row and at most one time column. Detection of the encoding,
column separator, decimal separator and time column is automatic; the result is an
:class:`ImportSettings` that is stored with the dataset so the file can be re-read identically.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from csvjuggler.data.dataset import Dataset
from csvjuggler.data.series import Series

log = logging.getLogger(__name__)

TimeUnit = Literal["s", "ms", "index"]

SNIFF_BYTES = 64 * 1024
SNIFF_LINES = 50
DELIMITER_CANDIDATES = ("\t", ";", ",")  # order = preference when several are consistent
TIME_NAME_HINTS = ("time", "temps", "t", "timestamp", "zeit", "seconds", "s")

_DECIMAL_COMMA_RE = re.compile(r"^\s*[+-]?\d+,\d+(?:[eE][+-]?\d+)?\s*$")

_TIME_SCALE: dict[str, float] = {"s": 1.0, "ms": 1e-3}


class CsvImportError(Exception):
    """Raised when a file cannot be turned into a dataset."""


@dataclass
class ImportSettings:
    encoding: str = "utf-8"
    delimiter: str = ","
    decimal: str = "."
    header_row: int = 0
    time_column: str | None = None
    """Column used as x. ``None`` → row index."""
    time_unit: TimeUnit = "s"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportSettings:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------- detection


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


def detect_delimiter(lines: list[str]) -> str:
    """Pick the first candidate whose count is identical and non-zero on most lines."""
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
        for field_ in line.split(delimiter):
            if _DECIMAL_COMMA_RE.match(field_):
                comma += 1
            elif "." in field_:
                try:
                    float(field_)
                    dot += 1
                except ValueError:
                    pass
    return "," if comma > dot else "."


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


def _read_sample_lines(path: Path, encoding: str) -> list[str]:
    with path.open("r", encoding=encoding, errors="replace", newline="") as fh:
        lines: list[str] = []
        for line in fh:
            line = line.rstrip("\r\n")
            if line.strip():
                lines.append(line)
            if len(lines) >= SNIFF_LINES:
                break
    return lines


def detect_settings(path: str | Path) -> ImportSettings:
    """Guess the import settings of a CSV file."""
    path = Path(path)
    with path.open("rb") as fh:
        raw = fh.read(SNIFF_BYTES)
    encoding = detect_encoding(raw)
    lines = _read_sample_lines(path, encoding)
    delimiter = detect_delimiter(lines)
    decimal = detect_decimal(lines[1:], delimiter)
    settings = ImportSettings(encoding=encoding, delimiter=delimiter, decimal=decimal)

    sample = _read_frame(path, settings, nrows=500)
    candidates = time_column_candidates(sample)
    if candidates:
        settings.time_column = candidates[0]
    else:
        settings.time_unit = "index"
    log.debug("Detected settings for %s: %s", path, settings)
    return settings


# --------------------------------------------------------------------------- loading


def _read_frame(path: Path, settings: ImportSettings, nrows: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        sep=settings.delimiter,
        decimal=settings.decimal,
        encoding=settings.encoding,
        header=settings.header_row,
        nrows=nrows,
        skipinitialspace=True,
    )
    df.columns = [str(c).strip() for c in df.columns]
    # Coerce text columns that are actually numeric (e.g. stray spaces); drop the rest.
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(axis="columns", how="all")


def default_alias(path: str | Path) -> str:
    """Default dataset alias: the file name without extension, without ``/``."""
    return Path(path).stem.replace("/", "_") or "dataset"


def load_csv(
    path: str | Path, settings: ImportSettings | None = None, alias: str | None = None
) -> Dataset:
    """Read ``path`` into a :class:`Dataset`. Settings are detected when not given."""
    path = Path(path)
    if not path.is_file():
        raise CsvImportError(f"Fichier introuvable : {path}")
    try:
        if settings is None:
            settings = detect_settings(path)
        df = _read_frame(path, settings)
    except (OSError, ValueError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise CsvImportError(str(exc)) from exc

    if df.empty or len(df.columns) == 0:
        raise CsvImportError("Aucune donnée numérique trouvée.")

    alias = alias or default_alias(path)
    time_col = settings.time_column if settings.time_unit != "index" else None
    if time_col is not None and time_col not in df.columns:
        log.warning("Time column %r missing in %s, using row index", time_col, path)
        time_col = None

    if time_col is None:
        x = np.arange(len(df), dtype=np.float64)
    else:
        x = df[time_col].to_numpy(dtype=np.float64) * _TIME_SCALE.get(settings.time_unit, 1.0)
    x.flags.writeable = False

    dataset = Dataset(
        alias=alias, path=path.resolve(), import_settings=settings, time_label=time_col or ""
    )
    for col in df.columns:
        if col == time_col:
            continue
        y = df[col].to_numpy(dtype=np.float64)
        dataset.series[col] = Series(name=col, x=x, y=y, source=alias)
    log.info("Loaded %s as %r: %d series, %d rows", path, alias, len(dataset.series), len(df))
    return dataset
