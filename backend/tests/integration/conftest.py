"""Fixtures for integration tests."""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest


_HERE = Path(__file__).resolve().parent  # tests/integration/
# Project root is backend/tests/integration/../../.. (warehouse-prototype/)
TEST_DATA = _HERE.parent.parent.parent / "data"


@pytest.fixture
def mdb_path(tmp_path) -> str:
    """Copy the .mdb file to a temp location so ETL tests don't clobber production data."""
    src = TEST_DATA / "recent.mdb"
    if not src.exists():
        pytest.skip(f"Source .mdb file not found: {src}")
    dest = tmp_path / "recent.mdb"
    shutil.copy2(src, dest)
    return str(dest)


@pytest.fixture
def db_path(tmp_path) -> str:
    """Temp path for the DuckDB warehouse file."""
    return str(tmp_path / "warehouse.db")
