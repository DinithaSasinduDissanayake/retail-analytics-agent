"""Schema description for injection into agent prompts."""
from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_MARKDOWN = """\
## Database Schema (READ ONLY)

### Stock (products)
- stock_id: VARCHAR — Product ID/SKU
- description: VARCHAR — Product name
- dept_id: VARCHAR → Departments.dept_id
- cost_price: DOUBLE — Latest purchase cost
- sell_price: DOUBLE — Current retail price
- quantity: INTEGER — Current stock level
- inactive: BOOLEAN — True if inactive, False if active

### Departments (product categories)
- dept_id: VARCHAR (primary key)
- dept_name: VARCHAR — Department name

### Docket (sales transactions)
- docket_id: VARCHAR (primary key)
- docket_date: TIMESTAMP — Transaction timestamp
- total_amount: DOUBLE — Docket total

### DocketLine (line items per docket)
- line_id: INTEGER (primary key)
- docket_id: VARCHAR → Docket.docket_id
- stock_id: VARCHAR → Stock.stock_id
- quantity: INTEGER — Quantity sold
- unit_price: DOUBLE — Unit price at time of sale
- line_total: DOUBLE — Line total

## Business Rules
- Margin % = (sell_price - cost_price) / sell_price * 100
- **CRITICAL — Historical margin analysis:** `DocketLine.unit_price` is the price at time of sale.
  `Stock.sell_price` is the current price. Historical cost is NOT stored at transaction level.
  Use `Stock.cost_price` as a proxy and ALWAYS note this limitation.
- A stock item is ACTIVE if `inactive` is FALSE (or NULL).
- A "slow mover" = no sale in 90+ days (check `DocketLine` + `Docket.docket_date` for `stock_id`).
"""


def load_schema_description(db_path: Path) -> str:
    """Load schema from warehouse.db."""
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = conn.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name NOT IN ('_etl_meta', 'stage_%')"
        ).fetchall()
        
        # Build schema markdown from actual DB
        schema = "# Database Schema (warehouse.db — READ ONLY)\n\n"
        for table in set(t[0] for t in tables):
            schema += f"### {table}\n"
            cols = [t for t in tables if t[0] == table]
            for _, col_name, col_type in sorted(cols, key=lambda x: x[1]):
                schema += f"- {col_name}: {col_type}\n"
            schema += "\n"
        
        # Append business rules
        schema += "## Business Rules\n"
        schema += "- Margin %% = (sell_price1 - cost_price) / sell_price1 * 100\n"
        schema += "- **CRITICAL — Historical margin analysis:** Use `DocketLine.price` as historical selling price. "
        schema += "Historical cost is NOT stored at transaction level — use `Stock.cost_price` as proxy.\n"
        schema += "- A 'slow mover' = no sale in 90+ days\n"
        schema += "- warehouse.db is READ ONLY. You cannot modify it.\n"
        
        return schema
    finally:
        conn.close()
