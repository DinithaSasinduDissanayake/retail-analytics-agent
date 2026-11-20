"""Schema description for injection into agent prompts."""
from __future__ import annotations

from pathlib import Path

import duckdb

SCHEMA_MARKDOWN = """\
## Database Schema (warehouse.db — READ ONLY)

### Stock (6,858 rows — products)
- stock_id: VARCHAR — Product ID/SKU
- description: VARCHAR — Product name
- dept_id: VARCHAR → Departments.dept_no
- cost: VARCHAR — Latest purchase cost (numeric, cast with CAST(x AS DECIMAL))
- sell: VARCHAR — Current retail price (numeric, cast with CAST(x AS DECIMAL))
- quantity: VARCHAR — Current stock level (numeric, cast with CAST(x AS INTEGER))
- supplier_id: VARCHAR → Supplier.supp_no
- Barcode: VARCHAR
- inactive: VARCHAR — '1' if inactive, empty or NULL if active
- cat1, cat2: VARCHAR — Category references
- date_created, date_modified: VARCHAR

### Docket (10,759 rows — sales transactions)
- docket_no: VARCHAR (primary key, numeric)
- docket_date: VARCHAR — Transaction date (YYYY-MM-DD format)
- debtors_no: VARCHAR → Customer.cust_no
- total_amount: VARCHAR — Docket total
- tax_amount: VARCHAR — Tax
- cashier_id: VARCHAR → Staff.staff_id
- register_id: VARCHAR

### DocketLine (19,061 rows — line items per docket)
- docket_no: VARCHAR → Docket.docket_no
- stock_no: VARCHAR → Stock.stock_id
- qty: VARCHAR — Quantity sold
- price: VARCHAR — Unit price at time of sale
- discount: VARCHAR — Discount applied
- tax_code: VARCHAR

### Customer (704 rows)
- cust_no: VARCHAR (primary key, numeric)
- name: VARCHAR
- address: VARCHAR
- phone: VARCHAR

### Supplier (498 rows)
- supp_no: VARCHAR (primary key, numeric)
- name: VARCHAR
- contact: VARCHAR
- phone: VARCHAR

### Departments (25 rows)
- dept_no: VARCHAR (primary key)
- name: VARCHAR
- description: VARCHAR

### CategoryValues (3,224 rows)
- cat_val: VARCHAR (primary key)
- dept_no: VARCHAR → Departments
- description: VARCHAR

### Payments (17,835 rows)
- docket_no: VARCHAR → Docket.docket_no
- pay_type: VARCHAR
- amount: VARCHAR
- tender_amount: VARCHAR

## Business Rules
- Columns with numeric values are stored as VARCHAR — use CAST() in SQL
- Margin %% = (CAST(sell AS DECIMAL) - CAST(cost AS DECIMAL)) / CAST(sell AS DECIMAL) * 100
- **CRITICAL — Historical margin analysis:** `DocketLine.price` is the price at time of sale.
  `Stock.sell` is the current price. Historical cost is NOT stored at transaction level.
  Use `Stock.cost` as a proxy and ALWAYS note this limitation.
- A stock item is ACTIVE if `inactive` is NULL or empty. "1" means inactive.
- A "slow mover" = no sale in 90+ days (check DocketLine for stock_no)
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
