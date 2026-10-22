import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from app import config

DB_PATH = config.DATABASE_PATH
SCENARIO_FILE = config.BASE_DIR / "mock_data" / "scenarios.json"

SCHEMA = """
CREATE TABLE nodes (node_id TEXT PRIMARY KEY, name TEXT, city TEXT, review_days INTEGER);
CREATE TABLE suppliers (supplier_id TEXT PRIMARY KEY, name TEXT, on_time_rate REAL, fill_rate REAL);
CREATE TABLE products (sku TEXT PRIMARY KEY, name TEXT, category TEXT, shelf_life_days INTEGER,
                       safety_days INTEGER, primary_supplier_id TEXT);
CREATE TABLE supplier_items (supplier_id TEXT, sku TEXT, unit_cost REAL, moq INTEGER, case_pack INTEGER,
                             lead_days INTEGER, capacity INTEGER);
CREATE TABLE inventory (node_id TEXT, sku TEXT, on_hand INTEGER, reserved INTEGER, last_counted TEXT,
                        forecast_daily REAL);
CREATE TABLE sales (node_id TEXT, sku TEXT, day TEXT, units INTEGER, orders INTEGER);
CREATE TABLE limits (node_id TEXT, category TEXT, budget_limit REAL, budget_used REAL,
                     storage_capacity INTEGER, storage_other_units INTEGER);
CREATE TABLE purchase_orders (po_id TEXT PRIMARY KEY, node_id TEXT, sku TEXT, supplier_id TEXT,
                              quantity INTEGER, confirmed_qty INTEGER, unit_cost REAL, status TEXT,
                              expected_day TEXT, created_by TEXT, run_id TEXT, note TEXT, created_at TEXT);
CREATE TABLE cases (case_id TEXT PRIMARY KEY, case_type TEXT, title TEXT, description TEXT, node_id TEXT,
                    sku TEXT, ref_po_id TEXT, recommended_qty INTEGER, recommended_supplier_id TEXT,
                    status TEXT, created_at TEXT);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, case_id TEXT, mode TEXT, status TEXT, decision TEXT,
                   quantity INTEGER, summary TEXT, decision_json TEXT, verification_json TEXT,
                   error TEXT, started_at TEXT, finished_at TEXT);
CREATE TABLE run_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, name TEXT,
                        payload_json TEXT, created_at TEXT);
CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, run_id TEXT, case_id TEXT, kind TEXT, po_id TEXT,
                        title TEXT, details TEXT, status TEXT, created_at TEXT, decided_at TEXT, note TEXT);
"""


# ==========================================
# Query helpers
# ==========================================
def connect():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def query(sql, args=()):
    conn = connect()
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    conn.close()
    return rows


def query_one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql, args=()):
    conn = connect()
    conn.execute(sql, args)
    conn.commit()
    conn.close()


# ==========================================
# Simulated clock
# ==========================================
def today():
    return date.fromisoformat(config.SIMULATION_DATE)


def day(offset):
    return (today() + timedelta(days=offset)).isoformat()


def days_until(iso_day):
    return (date.fromisoformat(iso_day[:10]) - today()).days


def now():
    return datetime.now().isoformat(timespec="seconds")


# ==========================================
# Reset + seed from mock_data/scenarios.json
# ==========================================
def reset():
    data = json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))
    conn = connect()
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchall()
    for (table,) in tables:
        conn.execute(f"DROP TABLE {table}")
    conn.executescript(SCHEMA)

    for n in data["nodes"]:
        conn.execute("INSERT INTO nodes VALUES (?, ?, ?, ?)",
                     (n["node_id"], n["name"], n["city"], n["review_period_days"]))
    for s in data["suppliers"]:
        conn.execute("INSERT INTO suppliers VALUES (?, ?, ?, ?)",
                     (s["supplier_id"], s["name"], s["on_time_rate"], s["fill_rate"]))
    for sc in data["scenarios"]:
        seed_scenario(conn, sc)

    conn.commit()
    conn.close()


def seed_scenario(conn, sc):
    node, p, case = sc["node_id"], sc["product"], sc["case"]
    sku = p["sku"]

    conn.execute("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?)",
                 (sku, p["name"], p["category"], p["shelf_life_days"], p["safety_days"], p["primary_supplier_id"]))

    costs = {}
    for i in sc["supplier_items"]:
        costs[i["supplier_id"]] = i["unit_cost"]
        conn.execute("INSERT INTO supplier_items VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (i["supplier_id"], sku, i["unit_cost"], i["moq"], i["case_pack"], i["lead_time_days"],
                      i["available_qty"]))

    inv = sc["inventory"]
    conn.execute("INSERT INTO inventory VALUES (?, ?, ?, ?, ?, ?)",
                 (node, sku, inv["on_hand"], inv["reserved"], day(-inv["last_counted_days_ago"]), sc["forecast"]))

    for offset, units, orders in make_sales(sku, sc["sales"]):
        conn.execute("INSERT INTO sales VALUES (?, ?, ?, ?, ?)", (node, sku, day(offset), units, orders))

    conn.execute("INSERT INTO limits VALUES (?, ?, ?, ?, ?, ?)",
                 (node, p["category"], sc["budget"]["limit"], sc["budget"]["committed"],
                  sc["storage"]["capacity"], sc["storage"]["other_units"]))

    for po in sc["open_pos"]:
        conn.execute("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (po["po_id"], node, sku, po["supplier_id"], po["quantity"], po["confirmed_qty"],
                      costs[po["supplier_id"]], po["status"], day(po["arrives_in_days"]),
                      "replenishment-engine", None, "seeded", day(-3)))

    conn.execute("INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)",
                 (case["case_id"], case["case_type"], case["title"], case["description"], node, sku,
                  case.get("ref_po_id"), case.get("recommended_qty"), case.get("recommended_supplier_id"), now()))


def make_sales(sku, spec):
    """28 days of sales, oldest first. The last days can be pinned with `recent`."""
    rng = random.Random(sku)
    recent = spec.get("recent", [])
    recent_orders = spec.get("recent_orders", [])
    rows = []
    for i in range(28):
        j = i - (28 - len(recent))
        if j >= 0:
            units = recent[j]
            orders = recent_orders[j] if recent_orders else round(units / spec["units_per_order"])
        else:
            units = spec["base"] + rng.randint(-spec["noise"], spec["noise"])
            orders = round(units / spec["units_per_order"])
        rows.append((i - 28, units, orders))
    return rows


def ensure_db():
    if not Path(DB_PATH).exists():
        reset()
