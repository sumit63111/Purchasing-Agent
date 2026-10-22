"""Fixed buyer playbook. Uses the same tools as the LLM agent, runs without an API key
and gives the evals a baseline to compare against."""

from app.agent.tools import run_tool
from app.planning import round_to_pack


def run_rule_agent(run):
    def call(name, **args):
        return run_tool(run, name, args)

    case = call("get_case")["case"]
    call("get_inventory")
    demand_info = call("get_demand")
    call("get_open_orders")
    suppliers = call("get_suppliers")["suppliers"]
    budget = call("get_budget")

    factors = list(demand_info["flags"])
    risks = []
    state = {"ordered": 0, "escalated": False}

    def submit(decision, demand, summary):
        for _ in range(3):
            result = call("submit_decision", decision=decision, quantity=state["ordered"], daily_demand_used=demand,
                          summary=summary, key_factors=factors, risks=risks)
            if "error" not in result:
                return
            if not state["escalated"]:
                call("escalate_to_buyer", subject=f"Verification flagged {case['sku']}",
                     details=" ".join(i["message"] for i in result["issues"]),
                     recommendation="Review the gap and decide on extra sourcing.")
                state["escalated"] = True

    def place(supplier, qty, demand, reason):
        result = call("create_purchase_order", supplier_id=supplier["supplier_id"], quantity=qty,
                      daily_demand=demand, reason=reason)
        if "error" in result:
            factors.append(result["error"])
            return 0
        if result["status"] == "pending_approval":
            factors.append(f"{result['po_id']}: {qty} units from {supplier['supplier_name']} waiting for approval.")
            state["ordered"] += qty
            return qty
        reply = result["supplier_response"]
        factors.append(f"{result['po_id']}: {reply['message']}")
        if reply["status"] == "partially_confirmed":
            call("accept_partial_confirmation", po_id=result["po_id"], note="Taking what the supplier can ship.")
        state["ordered"] += reply["confirmed_qty"]
        return reply["confirmed_qty"]

    # ==========================================
    # 1. Bad data: do not buy, escalate
    # ==========================================
    if not demand_info["data_ok"]:
        call("escalate_to_buyer", subject=f"Check data before buying {case['sku']} at {case['node_id']}",
             details=" ".join(demand_info["flags"]),
             recommendation="Count the stock and check the sales feed, then re-run the case.")
        state["escalated"] = True
        risks.append("If demand is real, stock may run short while the data is checked.")
        submit("investigate", demand_info["reference_daily_demand"],
               "Sales and stock data failed quality checks, so nothing was ordered. Escalated for a stock count.")
        return

    demand = demand_info["reference_daily_demand"]
    factors.insert(0, f"Planning with {demand}/day ({demand_info['reference_basis']}), "
                      f"forecast says {demand_info['forecast_daily']}/day.")

    # ==========================================
    # 2. Supplier shortfall: accept what is confirmed, avoid that supplier
    # ==========================================
    skip = set()
    if case["case_type"] == "supplier_shortfall":
        po = call("get_case")["referenced_po"]
        skip.add(po["supplier_id"])
        if po["status"] == "partially_confirmed":
            call("accept_partial_confirmation", po_id=po["po_id"],
                 note=f"Supplier can ship {po['confirmed_qty']} of {po['quantity']}.")
            factors.append(f"{po['po_id']}: accepted {po['confirmed_qty']} of {po['quantity']} units.")

    # ==========================================
    # 3. How much is needed
    # ==========================================
    need_info = call("calculate_need", daily_demand=demand)
    plan = call("project_stock", daily_demand=demand, proposed_orders=[])
    need = need_info["net_requirement"]
    factors.append(f"Target {need_info['target_stock']} units ({need_info['cover_breakdown']} days) vs position "
                   f"{need_info['inventory_position']}: need {need}.")

    if need == 0 and not plan["stockout_day"]:
        if case["recommended_qty"]:
            submit("reject", demand, f"No purchase needed. Position {need_info['inventory_position']} covers the "
                                     f"target of {need_info['target_stock']}. Recommendation of {case['recommended_qty']} rejected.")
        else:
            submit("accept", demand, f"Current plan is enough. Position {need_info['inventory_position']} covers the "
                                     f"target of {need_info['target_stock']}. No extra order.")
        return

    remaining = need
    primary = next(s for s in suppliers if s["is_primary"])

    # ==========================================
    # 4. Bridge order if stock runs out before the primary supplier can deliver
    # ==========================================
    stockout = plan["stockout_day"]
    if stockout and stockout < primary["lead_days"]:
        fast = sorted([s for s in suppliers if s["lead_days"] < stockout], key=lambda s: s["lead_days"])
        if fast:
            gap = -min(d["closing"] for d in plan["days"] if d["day"] < primary["lead_days"]) + demand
            qty = round_to_pack(gap, fast[0]["moq"], fast[0]["case_pack"])
            factors.append(f"Stock runs out on day {stockout}, before the primary supplier can deliver.")
            remaining -= place(fast[0], qty, demand, f"Bridge order to avoid a stockout on day {stockout}.")
        else:
            risks.append(f"Stockout on day {stockout} cannot be avoided with any supplier lead time.")

    # ==========================================
    # 5. Accept the recommendation if it matches the need and passes the checks
    # ==========================================
    rec_qty = case["recommended_qty"]
    accepted = False
    if rec_qty and remaining > 0:
        rec_supplier = next(s for s in suppliers if s["supplier_id"] == case["recommended_supplier_id"])
        ideal = round_to_pack(remaining, rec_supplier["moq"], rec_supplier["case_pack"])
        check = call("check_order", supplier_id=rec_supplier["supplier_id"], quantity=rec_qty, daily_demand=demand)
        if abs(rec_qty - ideal) <= 0.1 * ideal and check["valid"]:
            factors.append(f"Recommendation of {rec_qty} matches the computed need of {ideal}.")
            accepted = place(rec_supplier, rec_qty, demand, "Recommended quantity checked against need.") > 0
            remaining = 0
        else:
            factors.append(f"Recommendation of {rec_qty} does not fit: need is {ideal}. " + " ".join(check["errors"]))

    # ==========================================
    # 6. Demand spike: top up the open primary order first
    # ==========================================
    if case["case_type"] == "demand_change" and remaining > 0:
        open_po = next((p for p in call("get_open_orders")["open_orders"]
                        if p["supplier_id"] == primary["supplier_id"] and p["status"] == "confirmed"
                        and p["arrives_in_days"] >= 2), None)
        if open_po:
            extra = round_to_pack(remaining, 0, primary["case_pack"])
            result = call("increase_order_quantity", po_id=open_po["po_id"], new_quantity=open_po["quantity"] + extra,
                          daily_demand=demand, reason=f"Demand is now {demand}/day.")
            if "error" not in result:
                reply = result["supplier_response"]
                added = reply["confirmed_qty"] - open_po["confirmed_qty"]
                if reply["status"] == "partially_confirmed":
                    call("accept_partial_confirmation", po_id=open_po["po_id"], note="Supplier capped the increase.")
                factors.append(f"{open_po['po_id']} increased by {added} units.")
                state["ordered"] += added
                remaining -= added

    # ==========================================
    # 7. Source the rest: primary first, then cheapest. Shrink to fit limits.
    # ==========================================
    ranked = sorted([s for s in suppliers if s["supplier_id"] not in skip],
                    key=lambda s: (not s["is_primary"], s["unit_cost"]))
    for supplier in ranked:
        if remaining <= 0:
            break
        qty = round_to_pack(remaining, supplier["moq"], supplier["case_pack"])
        check = call("check_order", supplier_id=supplier["supplier_id"], quantity=qty, daily_demand=demand)
        if not check["valid"]:
            factors.append(f"{supplier['supplier_name']} x {qty}: " + " ".join(check["errors"]))
            qty = check["max_feasible_qty"]
            if qty <= 0:
                continue
            factors.append(f"Reduced to {qty} units, the most that fits.")
        remaining -= place(supplier, qty, demand, f"Cover {remaining} units still needed.")

    # ==========================================
    # 8. Escalate what is left, then submit
    # ==========================================
    if remaining > 0:
        call("escalate_to_buyer", subject=f"{remaining} units of {case['sku']} could not be sourced",
             details=f"Ordered {state['ordered']} units; {remaining} more are needed at {demand}/day. "
                     f"Budget remaining at start: ${budget['remaining']:,.2f}.",
             recommendation="Approve more budget or space, or accept lower cover this cycle.")
        state["escalated"] = True
        risks.append(f"{remaining} units of the need are not covered until the buyer acts.")

    if accepted:
        decision = "accept"
    elif state["ordered"]:
        decision = "modify"
    elif state["escalated"]:
        decision = "escalate"
    else:
        decision = "accept"

    summary = f"Need was {need} units at {demand}/day; ordered {state['ordered']}."
    if rec_qty:
        summary = f"Recommendation of {rec_qty} {'accepted' if accepted else 'changed'}. " + summary
    if state["escalated"]:
        summary += " The remaining gap went to the buyer."
    submit(decision, demand, summary)
