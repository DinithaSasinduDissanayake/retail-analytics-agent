"""DuckDB connection management."""
from __future__ import annotations

from pathlib import Path

import duckdb


def get_warehouse(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Get read-only warehouse connection. Every write attempt will fail at driver level."""
    return duckdb.connect(str(db_path), read_only=True)


def get_auxiliary(db_path: Path | str) -> duckdb.DuckDBPyConnection:
    """Get read-write auxiliary connection. Only used for logs, competitor pricing, cache."""
    return duckdb.connect(str(db_path))
