import json

from app import config, db, orders, planning
from app.checks import validate_order, verify_outcome


def schema(**properties):
    return {"type": "object", "properties": properties, "required": list(properties)}


TEXT = {"type": "string"}
NUMBER = {"type": "number"}
INTEGER = {"type": "integer"}
DEMAND = {"type": "number", "description": "Daily demand (units/day) you are planning with."}


# ==========================================
# Read tools
# ==========================================
def get_case(run, args):
    case = run["case"]
    result = {"case": case, "today": db.today().isoformat()}
    if case["ref_po_id"]:
        result["referenced_po"] = planning.get_po(case["ref_po_id"])
    return result


def get_inventory(run, args):
    item = planning.get_item(run["case"]["node_id"], run["case"]["sku"])
    return {
        "product": item["name"],
        "category": item["category"],
        "on_hand": item["on_hand"],
        "reserved": item["reserved"],
        "available": item["on_hand"] - item["reserved"],
        "last_physical_count": item["last_counted"],
        "shelf_life_days": item["shelf_life_days"],
        "storage_space_for_sku": item["storage_capacity"] - item["storage_other_units"],
    }


def get_demand(run, args):
    return planning.demand_signals(run["case"]["node_id"], run["case"]["sku"])


def get_open_orders(run, args):
    return {"open_orders": planning.open_orders(run["case"]["node_id"], run["case"]["sku"])}


def get_suppliers(run, args):
    return {"suppliers": planning.supplier_options(run["case"]["sku"]),
            "note": "Real supplier stock is only known after an order is submitted."}


def get_budget(run, args):
    item = planning.get_item(run["case"]["node_id"], run["case"]["sku"])
    return {"category": item["category"], "limit": item["budget_limit"], "used": item["budget_used"],
            "remaining": round(item["budget_limit"] - item["budget_used"], 2),
            "auto_approve_limit": config.AUTO_APPROVE_LIMIT}


def calculate_need(run, args):
    return planning.requirement(run["case"]["node_id"], run["case"]["sku"], float(args["daily_demand"]))


def project_stock(run, args):
    proposed = [{"supplier_id": o["supplier_id"], "quantity": int(o["quantity"])} for o in args.get("proposed_orders", [])]
    plan = planning.project(run["case"]["node_id"], run["case"]["sku"], float(args["daily_demand"]), proposed)
    plan["days"] = [{"day": d["day"], "arrivals": d["arrivals"], "closing": d["closing"]} for d in plan["days"]]
    return plan


def check_order(run, args):
    return validate_order(run["case"]["node_id"], run["case"]["sku"], args["supplier_id"], int(args["quantity"]),
                          float(args["daily_demand"]))


# ==========================================
# Action tools
# ==========================================
def create_purchase_order(run, args):
    return orders.create_order(run["case"]["node_id"], run["case"]["sku"], args["supplier_id"], int(args["quantity"]),
                               float(args["daily_demand"]), args["reason"], f"agent:{run['mode']}",
                               run["run_id"], run["case"]["case_id"])


def increase_order_quantity(run, args):
    check_scope(run, args["po_id"])
    return orders.change_order(args["po_id"], int(args["new_quantity"]), float(args["daily_demand"]), args["reason"],
                               run["run_id"])


def accept_partial_confirmation(run, args):
    check_scope(run, args["po_id"])
    return orders.accept_partial(args["po_id"], args["note"])


def request_po_cancellation(run, args):
    check_scope(run, args["po_id"])
    approval_id = orders.add_approval("cancel_order", f"Cancel {args['po_id']}", args["reason"],
                                      run["run_id"], run["case"]["case_id"], args["po_id"])
    return {"approval_id": approval_id, "status": "waiting for buyer"}


def escalate_to_buyer(run, args):
    approval_id = orders.add_approval("escalation", args["subject"],
                                      args["details"] + " Recommendation: " + args["recommendation"],
                                      run["run_id"], run["case"]["case_id"])
    return {"approval_id": approval_id, "status": "escalated"}


def submit_decision(run, args):
    run["attempts"] += 1
    args["quantity"] = int(args["quantity"])
    args["daily_demand_used"] = float(args["daily_demand_used"])
    result = verify_outcome(run["case"], args, run["run_id"])
    run["verification"] = result
    if result["passed"] or run["attempts"] >= config.MAX_VERIFY_ATTEMPTS:
        run["decision"] = args
        run["done"] = True
        return {"accepted": True, "verification": result}
    return {"error": "Verification failed. Fix the issues and call submit_decision again.",
            "issues": result["issues"], "warnings": result["warnings"],
            "attempts_left": config.MAX_VERIFY_ATTEMPTS - run["attempts"]}


def check_scope(run, po_id):
    po = planning.get_po(po_id)
    if po is None or po["sku"] != run["case"]["sku"] or po["node_id"] != run["case"]["node_id"]:
        raise orders.OrderError(f"{po_id} is not an order for this case.")


# ==========================================
# Tool list
# ==========================================
TOOLS = [
    ("get_case", get_case, "The case to work on, its recommendation and the referenced PO.", schema()),
    ("get_inventory", get_inventory, "On hand, reserved, last physical count, shelf life and storage space.", schema()),
    ("get_demand", get_demand, "Forecast vs 28 days of sales, outliers, demand shifts, data quality flags and a reference daily demand.", schema()),
    ("get_open_orders", get_open_orders, "Open purchase orders for this SKU with confirmed quantity and arrival day.", schema()),
    ("get_suppliers", get_suppliers, "Suppliers for this SKU: cost, premium vs primary, MOQ, case pack, lead time, fill rate.", schema()),
    ("get_budget", get_budget, "Category budget limit, used and remaining.", schema()),
    ("calculate_need", calculate_need, "Target stock, inventory position and net requirement for a daily demand.", schema(daily_demand=DEMAND)),
    ("project_stock", project_stock, "Day by day stock projection with open orders plus any proposed orders. Shows the stockout day.",
     schema(daily_demand=DEMAND, proposed_orders={"type": "array", "items": schema(supplier_id=TEXT, quantity=INTEGER)})),
    ("check_order", check_order, "Dry run every rule for a new order (MOQ, case pack, budget, storage, shelf life, approval). Returns max_feasible_qty. Creates nothing.",
     schema(supplier_id=TEXT, quantity=INTEGER, daily_demand=DEMAND)),
    ("create_purchase_order", create_purchase_order, "Validate and send a new PO. Big or pricey orders wait for approval. The supplier reply may confirm less than asked.",
     schema(supplier_id=TEXT, quantity=INTEGER, daily_demand=DEMAND, reason=TEXT)),
    ("increase_order_quantity", increase_order_quantity, "Increase an open PO. The supplier re-confirms the extra units.",
     schema(po_id=TEXT, new_quantity=INTEGER, daily_demand=DEMAND, reason=TEXT)),
    ("accept_partial_confirmation", accept_partial_confirmation, "Accept what the supplier confirmed on a partial PO and close the rest.",
     schema(po_id=TEXT, note=TEXT)),
    ("request_po_cancellation", request_po_cancellation, "Ask the buyer to cancel a PO. You cannot cancel directly.",
     schema(po_id=TEXT, reason=TEXT)),
    ("escalate_to_buyer", escalate_to_buyer, "Hand something to the human buyer: bad data, a gap you cannot cover, or a call outside your authority.",
     schema(subject=TEXT, details=TEXT, recommendation=TEXT)),
    ("submit_decision", submit_decision, "Last step. Records the decision and runs an independent check of the result. If it fails, fix the issues and submit again.",
     schema(decision={"type": "string", "enum": ["accept", "modify", "reject", "investigate", "escalate"]},
            quantity={"type": "integer", "description": "New units you ordered or added in this run, 0 if none. "
                                                      "Do not count units that were already on existing POs."},
            daily_demand_used=DEMAND, summary=TEXT,
            key_factors={"type": "array", "items": TEXT}, risks={"type": "array", "items": TEXT})),
]

HANDLERS = {name: handler for name, handler, _, _ in TOOLS}
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
    for name, _, description, parameters in TOOLS
]


# ==========================================
# Run a tool and record it in the trace
# ==========================================
def add_step(run_id, kind, name=None, payload=None):
    db.execute("INSERT INTO run_steps (run_id, kind, name, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
               (run_id, kind, name, json.dumps(payload, default=str), db.now()))


def run_tool(run, name, args):
    add_step(run["run_id"], "tool_call", name, args)
    try:
        result = HANDLERS[name](run, args)
    except KeyError:
        result = {"error": f"Unknown tool or missing argument in {name}."}
    except (orders.OrderError, TypeError, ValueError) as e:
        result = {"error": str(e)}

    add_step(run["run_id"], "tool_error" if "error" in result else "tool_result", name, result)
    if name == "submit_decision":
        add_step(run["run_id"], "verification", f"attempt {run['attempts']}", run["verification"])
    run["tools_called"].append(name)
    return result
