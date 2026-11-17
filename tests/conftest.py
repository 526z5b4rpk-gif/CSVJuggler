from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def data_dir() -> Path:
    return DATA_DIR


@pytest.fixture(autouse=True)
def _no_companion_files_in_test_data():
    """Tests must not write annotation companion files next to the shared sample CSVs."""
    yield
    leaked = sorted(DATA_DIR.glob("*.annotations.json"))
    for path in leaked:
        path.unlink()
    assert not leaked, f"companion files written in tests/data: {leaked}"
