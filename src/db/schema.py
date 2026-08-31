from pathlib import Path
import duckdb

def load_schema_description(db_path: Path | str = "data/warehouse.db") -> str:
    """Introspect schema from warehouse.db and generate markdown definition for LLM prompts."""
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = conn.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main'"
        ).fetchall()
        
        schema = "# Database Schema (warehouse.db — READ ONLY)\n\n"
        for table in sorted(list(set(t[0] for t in tables))):
            schema += f"### {table}\n"
            cols = [t for t in tables if t[0] == table]
            for _, col_name, col_type in sorted(cols, key=lambda x: x[1]):
                schema += f"- {col_name}: {col_type}\n"
            schema += "\n"
        
        schema += "## Business Rules\n"
        schema += "- Margin %% = (sell_price1 - cost_price) / sell_price1 * 100\n"
        schema += "- Slow mover = No sale in 90+ days in DocketLine\n"
        return schema
    finally:
        conn.close()
