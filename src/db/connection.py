from pathlib import Path
import duckdb

def get_warehouse(db_path: Path | str = "data/warehouse.db") -> duckdb.DuckDBPyConnection:
    """Return a strictly READ-ONLY DuckDB connection to prevent any accidental mutations."""
    return duckdb.connect(str(db_path), read_only=True)
