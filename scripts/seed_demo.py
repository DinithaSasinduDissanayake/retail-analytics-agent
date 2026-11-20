"""Generate a completely sanitized, deterministic synthetic retail DuckDB warehouse for demos and tests."""

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

import duckdb

DEPARTMENTS = [
    ("D01", "Fasteners & Hardware"),
    ("D02", "Paint & Coatings"),
    ("D03", "Plumbing Supplies"),
    ("D04", "Electrical & Lighting"),
    ("D05", "Hand Tools"),
    ("D06", "Garden & Outdoor"),
]

# (stock_id, description, dept_id, cost_price, sell_price1, quantity, inactive)
STOCK_ITEMS = [
    # Community 1: Paint job cluster
    ("SKU-101", "Interior Matte Wall Paint 4L", "D02", 18.50, 32.00, 45, "N"),
    ("SKU-102", "9-Inch Microfiber Paint Roller", "D02", 4.20, 9.50, 80, "N"),
    ("SKU-103", "Painter's Masking Tape 48mm", "D02", 1.80, 4.90, 140, "N"),
    ("SKU-104", "Heavy-Duty Plastic Drop Sheet", "D02", 2.10, 5.50, 95, "N"),
    # Community 2: Plumbing repair cluster
    ("SKU-201", "PVC Pressure Pipe 20mm x 3m", "D03", 3.40, 7.80, 110, "N"),
    ("SKU-202", "PVC Elbow Joint 20mm", "D03", 0.45, 1.40, 320, "N"),
    ("SKU-203", "PVC Solvent Cement 250ml", "D03", 2.90, 6.80, 75, "N"),
    ("SKU-204", "PTFE Thread Seal Tape", "D03", 0.40, 1.50, 260, "N"),
    # Community 3: Electrical installation cluster
    ("SKU-301", "LED Downlight 10W Warm White", "D04", 4.80, 11.90, 130, "N"),
    ("SKU-302", "Twin & Earth Cable 1.5mm 10m", "D04", 7.50, 16.00, 60, "N"),
    ("SKU-303", "Insulated Electrical Tape Roll", "D04", 0.65, 2.20, 210, "N"),
    ("SKU-304", "Flush Wall Switch Single Gang", "D04", 1.90, 5.40, 150, "N"),
    # Community 4: Fasteners & woodworking cluster
    ("SKU-401", "Wood Screws 8G x 40mm (Box 100)", "D01", 3.10, 7.50, 190, "N"),
    ("SKU-402", "Claw Hammer 16oz Fiberglass", "D05", 8.20, 18.90, 40, "N"),
    ("SKU-403", "Tape Measure 5m Metric", "D05", 3.60, 8.90, 65, "N"),
    # Slow mover (no sales in last 120 days)
    ("SKU-501", "Brass Garden Hose Nozzle Pro", "D06", 9.00, 21.50, 28, "N"),
    # Inactive SKU
    ("SKU-502", "Legacy Halogen Floodlight 500W", "D04", 11.00, 24.00, 5, "Y"),
]

TRADE_BASKETS = [
    ["SKU-101", "SKU-102", "SKU-103", "SKU-104"],
    ["SKU-201", "SKU-202", "SKU-203", "SKU-204"],
    ["SKU-301", "SKU-302", "SKU-303", "SKU-304"],
    ["SKU-401", "SKU-402", "SKU-403"],
]


def seed_warehouse(output_path: Path | str = "data/demo_warehouse.db", num_dockets: int = 240, seed: int = 42) -> Path:
    """Create a synthetic DuckDB retail warehouse with realistic trade baskets and slow movers."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    rng = random.Random(seed)
    price_map = {item[0]: item[4] for item in STOCK_ITEMS}
    today = date(2026, 11, 1)

    conn = duckdb.connect(str(out))
    try:
        conn.execute("""
            CREATE TABLE Departments (
                dept_id VARCHAR,
                dept_name VARCHAR
            );
            CREATE TABLE Stock (
                stock_id VARCHAR,
                description VARCHAR,
                dept_id VARCHAR,
                cost_price DOUBLE,
                sell_price1 DOUBLE,
                quantity INTEGER,
                inactive VARCHAR
            );
            CREATE TABLE Docket (
                docket_id VARCHAR,
                docket_date VARCHAR,
                total_amount DOUBLE
            );
            CREATE TABLE DocketLine (
                line_id VARCHAR,
                docket_id VARCHAR,
                stock_id VARCHAR,
                qty INTEGER,
                price DOUBLE
            );
        """)

        conn.executemany("INSERT INTO Departments VALUES (?, ?)", DEPARTMENTS)
        conn.executemany("INSERT INTO Stock VALUES (?, ?, ?, ?, ?, ?, ?)", STOCK_ITEMS)

        dockets = []
        lines = []
        line_counter = 1

        for idx in range(1, num_dockets + 1):
            docket_id = f"DOC-{idx:05d}"
            days_ago = rng.randint(1, 75)
            docket_date = (today - timedelta(days=days_ago)).isoformat()

            cluster = rng.choice(TRADE_BASKETS)
            basket_size = rng.randint(2, len(cluster))
            chosen = rng.sample(cluster, k=basket_size)

            # Occasional cross-department add-on
            if rng.random() < 0.12:
                chosen.append(rng.choice(["SKU-401", "SKU-403"]))
                chosen = list(dict.fromkeys(chosen))

            total = 0.0
            for sku in chosen:
                qty = rng.randint(1, 4)
                unit_price = price_map[sku]
                total += qty * unit_price
                lines.append((f"LINE-{line_counter:06d}", docket_id, sku, qty, unit_price))
                line_counter += 1

            dockets.append((docket_id, docket_date, round(total, 2)))

        # Add one old sale (>120 days ago) for SKU-501 so it qualifies as a slow mover
        old_date = (today - timedelta(days=135)).isoformat()
        dockets.append(("DOC-00999", old_date, price_map["SKU-501"]))
        lines.append((f"LINE-{line_counter:06d}", "DOC-00999", "SKU-501", 1, price_map["SKU-501"]))

        conn.executemany("INSERT INTO Docket VALUES (?, ?, ?)", dockets)
        conn.executemany("INSERT INTO DocketLine VALUES (?, ?, ?, ?, ?)", lines)
    finally:
        conn.close()

    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed a synthetic retail DuckDB warehouse.")
    parser.add_argument("--output", default="data/demo_warehouse.db", help="Output DuckDB file path")
    parser.add_argument("--dockets", type=int, default=240, help="Number of synthetic sales dockets")
    args = parser.parse_args()
    created = seed_warehouse(args.output, num_dockets=args.dockets)
    print(f"Seeded synthetic retail warehouse at {created}")
