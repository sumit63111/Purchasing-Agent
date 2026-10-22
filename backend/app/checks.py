from app import config, db
from app.planning import get_item, get_offer, get_po, open_orders, project, round_to_pack, supplier_options, demand_signals


# ==========================================
# Check one order before it is placed
# ==========================================
def validate_order(node_id, sku, supplier_id, quantity, daily_demand, po_id=None):
    offer = get_offer(supplier_id, sku)
    if offer is None:
        return {"valid": False, "errors": [f"{supplier_id} does not supply {sku}."], "warnings": [],
                "needs_approval": False, "approval_reasons": [], "max_feasible_qty": 0}

    item = get_item(node_id, sku)
    errors, warnings = [], []

    # For a change to an existing PO only the extra units count
    already = 0
    arrival_day = offer["lead_days"]
    if po_id:
        po = get_po(po_id)
        already = po["quantity"]
        arrival_day = max(1, db.days_until(po["expected_day"]))
    added = quantity - already

    value = round(added * offer["unit_cost"], 2)
    budget_left = round(item["budget_limit"] - item["budget_used"], 2)
    space = item["storage_capacity"] - item["storage_other_units"]

    plan = project(node_id, sku, daily_demand, days=arrival_day + 14)
    after_arrival = [d for d in plan["days"] if d["day"] >= arrival_day]
    peak_without = max(d["opening"] for d in after_arrival)
    stock_at_arrival = after_arrival[0]["opening"] + added
    cover_days = stock_at_arrival / daily_demand if daily_demand else 0

    # Hard rules
    if quantity < offer["moq"]:
        errors.append(f"{quantity} is below the supplier minimum order of {offer['moq']}.")
    if quantity % offer["case_pack"]:
        errors.append(f"{quantity} is not a multiple of the case pack ({offer['case_pack']}).")
    if value > budget_left:
        errors.append(f"Order adds ${value:,.2f} but only ${budget_left:,.2f} of the {item['category']} budget is left.")
    if peak_without + added > space:
        errors.append(f"Stock would peak at {peak_without + added:.0f} units; storage holds {space} for this SKU.")
    if cover_days > item["shelf_life_days"]:
        errors.append(f"{cover_days:.0f} days of cover is longer than the {item['shelf_life_days']}-day shelf life.")

    # Soft rules
    if config.MAX_COVER_DAYS < cover_days <= item["shelf_life_days"]:
        warnings.append(f"{cover_days:.0f} days of cover after arrival is above the {config.MAX_COVER_DAYS}-day target.")
    if plan["stockout_day"] and plan["stockout_day"] < arrival_day:
        warnings.append(f"Stock runs out on day {plan['stockout_day']} but this order arrives on day {arrival_day}.")
    if offer["fill_rate"] < config.MIN_FILL_RATE:
        warnings.append(f"{offer['supplier_name']} fills only {offer['fill_rate']:.0%} of orders; expect a partial confirmation.")

    # Approval policy
    approval_reasons = []
    if value > config.AUTO_APPROVE_LIMIT:
        approval_reasons.append(f"Order value ${value:,.2f} is above the ${config.AUTO_APPROVE_LIMIT:,.0f} auto-approval limit.")
    premium = offer["unit_cost"] / item["primary_unit_cost"] - 1
    if premium > config.MAX_PRICE_PREMIUM:
        approval_reasons.append(f"Price is {premium:.0%} above the primary supplier (limit {config.MAX_PRICE_PREMIUM:.0%}).")

    # Largest quantity that passes every hard rule
    room = min(budget_left // offer["unit_cost"], space - peak_without,
               item["shelf_life_days"] * daily_demand - after_arrival[0]["opening"])
    max_feasible = round_to_pack(already + room, offer["moq"], offer["case_pack"], up=False)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "needs_approval": bool(approval_reasons),
        "approval_reasons": approval_reasons,
        "order_value": value,
        "arrival_day": arrival_day,
        "days_of_cover_after_arrival": round(cover_days, 1),
        "budget_left": budget_left,
        "max_feasible_qty": max_feasible,
    }


# ==========================================
# Check the state the agent left behind
# ==========================================
def verify_outcome(case, decision, run_id):
    node_id, sku = case["node_id"], case["sku"]
    item = get_item(node_id, sku)
    signals = demand_signals(node_id, sku)
    issues, warnings = [], []

    run_orders = db.query("SELECT * FROM purchase_orders WHERE run_id = ? AND status NOT IN ('cancelled', 'rejected')",
                          (run_id,))
    escalated = db.query_one("SELECT 1 AS x FROM approvals WHERE run_id = ? AND kind = 'escalation'", (run_id,))
    choice = decision["decision"]

    # Use the agent's demand, but never less than what the data shows
    demand = decision["daily_demand_used"]
    if signals["data_ok"]:
        if demand < 0.75 * signals["reference_daily_demand"]:
            warnings.append(f"Agent planned with {demand}/day but sales show {signals['reference_daily_demand']}/day.")
        demand = max(demand, signals["reference_daily_demand"])

    # 1. Coverage until the next order cycle can land
    plan = project(node_id, sku, demand, days=item["primary_lead_days"] + item["review_days"])
    if plan["stockout_day"]:
        fastest = min(s["lead_days"] for s in supplier_options(sku))
        msg = f"Stock runs out on day {plan['stockout_day']} at {demand}/day with the current orders."
        if plan["stockout_day"] < fastest:
            msg += f" No supplier can deliver before then (fastest is {fastest} days)."
        if escalated:
            warnings.append(msg + " Escalated to the buyer.")
        else:
            issues.append({"code": "coverage_gap", "message": msg})

    # 2. Budget
    budget_left = item["budget_limit"] - item["budget_used"]
    if budget_left < 0:
        issues.append({"code": "budget_exceeded", "message": f"{item['category']} budget is over by ${-budget_left:,.2f}."})

    # 3. Storage
    month = project(node_id, sku, max(demand, 0.1), days=30)
    space = item["storage_capacity"] - item["storage_other_units"]
    if month["peak_stock"] > space:
        issues.append({"code": "storage_exceeded",
                       "message": f"Stock peaks at {month['peak_stock']:.0f} units; storage holds {space}."})

    # 4. Supplier replies that were never dealt with
    for po in open_orders(node_id, sku):
        if po["status"] == "partially_confirmed":
            issues.append({"code": "unresolved_partial",
                           "message": f"{po['po_id']} is only partly confirmed ({po['confirmed_qty']} of {po['quantity']}). "
                                      f"Accept the partial quantity and cover the gap."})

    # 5. Decision has to match what was done
    if choice in ("reject", "investigate") and run_orders:
        issues.append({"code": "decision_mismatch", "message": f"Decision is '{choice}' but orders were placed."})
    if choice in ("investigate", "escalate") and not escalated:
        issues.append({"code": "missing_escalation", "message": f"'{choice}' needs a buyer task. Call escalate_to_buyer."})
    if not signals["data_ok"] and run_orders and not escalated:
        issues.append({"code": "acted_on_bad_data", "message": "Orders were placed on demand data that failed quality checks."})

    pending = [po["po_id"] for po in run_orders if po["status"] == "pending_approval"]
    if pending:
        warnings.append(f"Waiting for approval: {', '.join(pending)}. Coverage assumes they are approved.")

    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "checked_daily_demand": demand,
        "stockout_day": plan["stockout_day"],
        "budget_left": round(budget_left, 2),
        "peak_stock": month["peak_stock"],
        "storage_space": space,
    }
