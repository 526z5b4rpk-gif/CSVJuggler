from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from csvjuggler.data.importer import (
    CsvImportError,
    ImportSettings,
    detect_settings,
    load_csv,
)


def test_comma_file(data_dir: Path) -> None:
    s = detect_settings(data_dir / "simple_comma.csv")
    assert (s.delimiter, s.decimal, s.time_column) == (",", ".", "time")
    ds = load_csv(data_dir / "simple_comma.csv", s)
    assert ds.alias == "simple_comma"
    assert list(ds.series) == ["speed", "torque", "status"]
    speed = ds.series["speed"]
    assert speed.id == "simple_comma/speed"
    np.testing.assert_allclose(speed.x, [0.0, 0.1, 0.2, 0.3, 0.4])
    np.testing.assert_allclose(speed.y, [0.0, 10.2, 20.5, 30.1, 40.0])


def test_semicolon_with_decimal_comma(data_dir: Path) -> None:
    s = detect_settings(data_dir / "semicolon_decimal_comma.csv")
    assert (s.delimiter, s.decimal) == (";", ",")
    assert s.time_column == "Temps (ms)"
    ds = load_csv(data_dir / "semicolon_decimal_comma.csv", s)
    np.testing.assert_allclose(ds.series["Courant"].y, [0.5, 0.6, 0.55, 0.7])
    np.testing.assert_allclose(ds.series["Tension"].y[0], 230.1)


def test_time_unit_ms(data_dir: Path) -> None:
    s = detect_settings(data_dir / "semicolon_decimal_comma.csv")
    s.time_unit = "ms"
    ds = load_csv(data_dir / "semicolon_decimal_comma.csv", s)
    np.testing.assert_allclose(ds.series["Courant"].x, [0.0, 0.01, 0.02, 0.03])


def test_tab_without_time_column_uses_index(data_dir: Path) -> None:
    s = detect_settings(data_dir / "tab_no_time.tsv")
    assert s.delimiter == "\t"
    assert s.time_column is None and s.time_unit == "index"
    ds = load_csv(data_dir / "tab_no_time.tsv", s)
    assert list(ds.series) == ["index", "A", "B"]
    np.testing.assert_allclose(ds.series["A"].x, [0, 1, 2])


def test_cp1252_fallback(data_dir: Path) -> None:
    s = detect_settings(data_dir / "cp1252.csv")
    assert s.encoding == "cp1252"
    ds = load_csv(data_dir / "cp1252.csv", s)
    assert "Température °C" in ds.series


def test_explicit_alias_and_detection_when_settings_missing(data_dir: Path) -> None:
    ds = load_csv(data_dir / "simple_comma.csv", alias="run1")
    assert ds.series["torque"].id == "run1/torque"
    assert ds.import_settings is not None


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CsvImportError):
        load_csv(tmp_path / "nope.csv")


def test_import_settings_json_roundtrip() -> None:
    s = ImportSettings(encoding="cp1252", delimiter=";", decimal=",", time_column="t")
    assert ImportSettings.from_dict(s.to_dict()) == s
