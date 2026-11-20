"""ETL: Extract legacy POS .mdb → DuckDB warehouse.db."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

import duckdb
import structlog

logger = structlog.get_logger()

# Tables to extract — key ones first, rest are secondary
PRIMARY_TABLES = [
    "Stock", "Docket", "DocketLine", "Customer", "Supplier",
    "Departments", "Categories", "CategoryValues",
    "Payments", "Returns", "ReturnsLine",
]

SECONDARY_TABLES = [
    "TaxCodes", "Staff", "Groups", "Pricing_Global", "Pricing_Categories",
    "Pricing_Stock", "Promotions",
]


def extract_mdb(mdb_path: Path, table: str) -> str | None:
    """Export a table from .mdb to CSV string. Returns None on error."""
    try:
        result = subprocess.run(
            ["mdb-export", str(mdb_path), table],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.warning("mdb-export failed", table=table, stderr=result.stderr[:200])
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.warning("mdb-export timeout", table=table)
        return None
    except FileNotFoundError:
        logger.error("mdbtools not installed — install with: apt install mdbtools")
        return None


def load_csv_to_duckdb(conn: duckdb.DuckDBPyConnection, table: str, csv_data: str):
    """Load CSV string into DuckDB table (staging)."""
    # Create staging table (DROP first for full reload)
    conn.execute(f"DROP TABLE IF EXISTS stage_{table}")
    
    # DuckDB can read CSV directly from a string via read_csv_auto
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_data)
        tmp_path = f.name
    
    try:
        conn.execute(f"""
            CREATE TABLE stage_{table} AS
            SELECT * FROM read_csv_auto('{tmp_path}', all_varchar=true)
        """)
        count = conn.execute(f"SELECT count(*) FROM stage_{table}").fetchone()[0]
        logger.info("Loaded", table=table, rows=count)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def swap_staging(conn: duckdb.DuckDBPyConnection, table: str):
    """Swap staging table into production."""
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(f"ALTER TABLE stage_{table} RENAME TO {table}")


def run_etl(mdb_path: Path, db_path: Path):
    """Full ETL: extract .mdb → load DuckDB staging → swap into production."""
    logger.info("ETL start", mdb=str(mdb_path))
    
    # Connect DuckDB (read-write for loading)
    conn = duckdb.connect(str(db_path))
    
    try:
        # Extract + load primary tables
        for table in PRIMARY_TABLES:
            csv_data = extract_mdb(mdb_path, table)
            if csv_data and len(csv_data) > 100:  # at least header + 1 row
                load_csv_to_duckdb(conn, table, csv_data)
                swap_staging(conn, table)
            else:
                logger.warning("Table empty or failed", table=table)
        
        # Extract + load secondary tables
        for table in SECONDARY_TABLES:
            csv_data = extract_mdb(mdb_path, table)
            if csv_data and len(csv_data) > 100:
                load_csv_to_duckdb(conn, table, csv_data)
                swap_staging(conn, table)
        
        # Compute schema hash for drift detection
        schema_hash = compute_schema_hash(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS _etl_meta (key VARCHAR, value VARCHAR)")
        conn.execute("DELETE FROM _etl_meta WHERE key = 'schema_hash'")
        conn.execute(
            "INSERT INTO _etl_meta VALUES ('schema_hash', ?)",
            [schema_hash],
        )
        conn.execute("DELETE FROM _etl_meta WHERE key = 'etl_timestamp'")
        conn.execute(
            "INSERT INTO _etl_meta VALUES ('etl_timestamp', ?)",
            [str(Path(mdb_path).stat().st_mtime)],
        )
        
        # Summary
        summary = {}
        for table in PRIMARY_TABLES:
            try:
                count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                summary[table] = count
            except Exception:
                pass
        
        logger.info("ETL complete", summary=summary)
        return summary
    
    finally:
        conn.close()


def compute_schema_hash(conn: duckdb.DuckDBPyConnection) -> str:
    """Hash all column names + types for schema drift detection."""
    tables = conn.execute(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'main' AND table_name NOT LIKE 'stage_%' AND table_name != '_etl_meta'"
    ).fetchall()
    raw = "\n".join(f"{t}.{c}:{d}" for t, c, d in sorted(tables))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


if __name__ == "__main__":
    import sys
    mdb = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/pos_export.mdb")
    db = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/warehouse.db")
    summary = run_etl(mdb.resolve(), db.resolve())
    print(summary)
