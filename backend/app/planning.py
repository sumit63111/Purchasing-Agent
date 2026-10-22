import math
from datetime import date
from statistics import mean, median

from app import db

OPEN_STATUSES = ("pending_approval", "submitted", "confirmed", "partially_confirmed")


# ==========================================
# Data reads
# ==========================================
def get_item(node_id, sku):
    """Product, stock, node settings and category limits for one SKU at one node."""
    return db.query_one(
        """SELECT p.*, i.node_id, i.on_hand, i.reserved, i.last_counted, i.forecast_daily, n.review_days,
                  l.budget_limit, l.budget_used, l.storage_capacity, l.storage_other_units,
                  si.lead_days AS primary_lead_days, si.unit_cost AS primary_unit_cost
           FROM products p
           JOIN inventory i ON i.sku = p.sku
           JOIN nodes n ON n.node_id = i.node_id
           JOIN limits l ON l.node_id = i.node_id AND l.category = p.category
           JOIN supplier_items si ON si.sku = p.sku AND si.supplier_id = p.primary_supplier_id
           WHERE i.node_id = ? AND p.sku = ?""",
        (node_id, sku),
    )


def get_offer(supplier_id, sku):
    return db.query_one(
        """SELECT si.*, s.name AS supplier_name, s.fill_rate, s.on_time_rate
           FROM supplier_items si JOIN suppliers s ON s.supplier_id = si.supplier_id
           WHERE si.supplier_id = ? AND si.sku = ?""",
        (supplier_id, sku),
    )


def supplier_options(sku):
    """What the buyer can see about each supplier. Real capacity stays hidden."""
    rows = db.query(
        """SELECT si.supplier_id, s.name AS supplier_name, si.unit_cost, si.moq, si.case_pack,
                  si.lead_days, s.fill_rate, s.on_time_rate, p.primary_supplier_id
           FROM supplier_items si
           JOIN suppliers s ON s.supplier_id = si.supplier_id
           JOIN products p ON p.sku = si.sku
           WHERE si.sku = ? ORDER BY si.unit_cost""",
        (sku,),
    )
    primary_cost = next(r["unit_cost"] for r in rows if r["supplier_id"] == r["primary_supplier_id"])
    for r in rows:
        r["is_primary"] = r.pop("primary_supplier_id") == r["supplier_id"]
        r["price_premium_pct"] = round((r["unit_cost"] / primary_cost - 1) * 100, 1)
    return rows


def get_po(po_id):
    return db.query_one("SELECT * FROM purchase_orders WHERE po_id = ?", (po_id,))


def open_orders(node_id, sku):
    rows = db.query(
        "SELECT * FROM purchase_orders WHERE node_id = ? AND sku = ? AND status IN (?, ?, ?, ?) ORDER BY expected_day",
        (node_id, sku, *OPEN_STATUSES),
    )
    for po in rows:
        po["arrives_in_days"] = db.days_until(po["expected_day"])
        po["incoming_qty"] = incoming(po)
    return rows


def incoming(po):
    if po["status"] in ("confirmed", "partially_confirmed"):
        return po["confirmed_qty"]
    return po["quantity"]


def round_to_pack(qty, moq, case_pack, up=True):
    if qty <= 0:
        return 0
    if up:
        return max(math.ceil(qty / case_pack) * case_pack, math.ceil(moq / case_pack) * case_pack)
    units = math.floor(qty / case_pack) * case_pack
    return units if units >= moq else 0


# ==========================================
# Demand signals
# ==========================================
def demand_signals(node_id, sku):
    item = get_item(node_id, sku)
    sales = db.query("SELECT day, units, orders FROM sales WHERE node_id = ? AND sku = ? ORDER BY day",
                     (node_id, sku))
    units = [s["units"] for s in sales]
    baseline = median(units[:-7])
    last_7 = sales[-7:]

    outliers = [s for s in sales if s["units"] > 3 * baseline]
    outlier_days = {s["day"] for s in outliers}
    clean_7 = [s["units"] for s in last_7 if s["day"] not in outlier_days]
    zero_days = sum(1 for s in last_7 if s["units"] == 0)

    flags = []
    data_ok = not (zero_days >= 3 and item["on_hand"] > 0)
    if not data_ok:
        flags.append(f"{zero_days} of the last 7 days show zero sales while {item['on_hand']} units are on hand. "
                     f"The sales feed is broken or the stock is not really there. Demand cannot be trusted.")

    count_age = (db.today() - date.fromisoformat(item["last_counted"])).days
    if count_age > 21:
        flags.append(f"Stock was last physically counted {count_age} days ago.")

    for s in outliers:
        flags.append(f"{s['day']}: {s['units']} units from only {s['orders']} orders looks like a one-off "
                     f"bulk purchase. Excluded from the demand estimate.")

    shift_up = data_ok and median(clean_7) > 1.3 * baseline
    if shift_up:
        reference = mean(clean_7)
        flags.append(f"Sales have been above baseline on {sum(u > 1.2 * baseline for u in clean_7)} of the last "
                     f"7 days ({mean(clean_7):.1f}/day vs {baseline:g}/day). The increase looks sustained.")
    else:
        reference = mean(s["units"] for s in sales if s["day"] not in outlier_days and s["units"] > 0)

    if data_ok and abs(item["forecast_daily"] - reference) / reference > 0.3:
        flags.append(f"Forecast ({item['forecast_daily']:g}/day) is more than 30% off actual demand.")

    return {
        "forecast_daily": item["forecast_daily"],
        "baseline_daily": baseline,
        "avg_last_7": round(mean(units[-7:]), 1),
        "avg_last_7_clean": round(mean(clean_7), 1) if clean_7 else 0,
        "avg_last_28": round(mean(units), 1),
        "reference_daily_demand": round(reference, 1),
        "reference_basis": "last 7 days (sustained shift)" if shift_up else "last 28 days without outliers",
        "data_ok": data_ok,
        "flags": flags,
        "last_7_days": last_7,
        "daily_units_28d": units,
    }


# ==========================================
# Stock projection
# ==========================================
def project(node_id, sku, daily_demand, extra_orders=None, days=None):
    item = get_item(node_id, sku)
    cycle_days = item["primary_lead_days"] + item["review_days"]
    days = days or cycle_days + item["safety_days"]

    arrivals = {}
    for po in open_orders(node_id, sku):
        d = max(1, po["arrives_in_days"])
        arrivals[d] = arrivals.get(d, 0) + po["incoming_qty"]
    for order in extra_orders or []:
        d = get_offer(order["supplier_id"], sku)["lead_days"]
        arrivals[d] = arrivals.get(d, 0) + order["quantity"]
        days = max(days, d + 1)

    stock = item["on_hand"] - item["reserved"]
    start = stock
    timeline = []
    stockout_day = None
    for d in range(1, days + 1):
        stock += arrivals.get(d, 0)
        opening = stock
        stock -= daily_demand
        timeline.append({"day": d, "arrivals": arrivals.get(d, 0), "opening": round(opening, 1),
                         "closing": round(stock, 1)})
        if stock < 0 and stockout_day is None:
            stockout_day = d

    return {
        "daily_demand": daily_demand,
        "start_stock": start,
        "stockout_day": stockout_day,
        "peak_stock": max(start, max(t["opening"] for t in timeline)),
        "cycle_days": cycle_days,
        "closing_at_cycle_end": timeline[min(cycle_days, days) - 1]["closing"],
        "days": timeline,
    }


# ==========================================
# Requirement
# ==========================================
def requirement(node_id, sku, daily_demand):
    item = get_item(node_id, sku)
    cover_days = item["primary_lead_days"] + item["review_days"] + item["safety_days"]
    target = math.ceil(daily_demand * cover_days)
    on_order = sum(po["incoming_qty"] for po in open_orders(node_id, sku))
    position = item["on_hand"] - item["reserved"] + on_order
    return {
        "daily_demand": daily_demand,
        "cover_days": cover_days,
        "cover_breakdown": f"{item['primary_lead_days']} lead + {item['review_days']} review + {item['safety_days']} safety",
        "target_stock": target,
        "available_now": item["on_hand"] - item["reserved"],
        "on_order": on_order,
        "inventory_position": position,
        "net_requirement": max(0, target - position),
        "days_of_cover": round(position / daily_demand, 1) if daily_demand else None,
    }
