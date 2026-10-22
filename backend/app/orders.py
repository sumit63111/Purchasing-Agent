import uuid

from app import db
from app.checks import validate_order
from app.planning import get_item, get_offer, get_po


class OrderError(Exception):
    pass


def change_budget(po, units):
    item = get_item(po["node_id"], po["sku"])
    db.execute("UPDATE limits SET budget_used = ROUND(budget_used + ?, 2) WHERE node_id = ? AND category = ?",
               (units * po["unit_cost"], po["node_id"], item["category"]))


# ==========================================
# Mock supplier: confirms what it really has in stock
# ==========================================
def supplier_confirm(po_id, requested_extra=None):
    po = get_po(po_id)
    offer = get_offer(po["supplier_id"], po["sku"])
    available = offer["capacity"] - offer["capacity"] % offer["case_pack"]

    if requested_extra is None:
        confirmed = min(po["quantity"], available)
        taken = confirmed
    else:
        taken = min(requested_extra, available)
        confirmed = (po["confirmed_qty"] or 0) + taken

    db.execute("UPDATE supplier_items SET capacity = capacity - ? WHERE supplier_id = ? AND sku = ?",
               (taken, po["supplier_id"], po["sku"]))

    if confirmed >= po["quantity"]:
        status, message = "confirmed", f"{offer['supplier_name']} confirmed {confirmed} units."
    elif confirmed > 0:
        status = "partially_confirmed"
        message = f"{offer['supplier_name']} can only supply {confirmed} of {po['quantity']} units right now."
    else:
        status, message = "rejected", f"{offer['supplier_name']} has no stock and rejected the order."
        change_budget(po, -po["quantity"])

    db.execute("UPDATE purchase_orders SET status = ?, confirmed_qty = ? WHERE po_id = ?", (status, confirmed, po_id))
    return {"po_id": po_id, "requested_qty": po["quantity"], "confirmed_qty": confirmed, "status": status,
            "expected_day": po["expected_day"], "message": message}


# ==========================================
# Agent actions
# ==========================================
def create_order(node_id, sku, supplier_id, quantity, daily_demand, reason, created_by, run_id=None, case_id=None):
    check = validate_order(node_id, sku, supplier_id, quantity, daily_demand)
    if not check["valid"]:
        raise OrderError("Order rejected by validation: " + " ".join(check["errors"]))

    offer = get_offer(supplier_id, sku)
    count = db.query_one("SELECT COUNT(*) AS n FROM purchase_orders WHERE po_id LIKE 'PO-9%'")["n"]
    po_id = f"PO-{9001 + count}"
    status = "pending_approval" if check["needs_approval"] else "submitted"
    db.execute("INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)",
               (po_id, node_id, sku, supplier_id, quantity, offer["unit_cost"], status,
                db.day(offer["lead_days"]), created_by, run_id, reason, db.now()))
    change_budget(get_po(po_id), quantity)

    if status == "pending_approval":
        approval_id = add_approval("purchase_order", f"Approve {po_id}: {quantity} x {sku} from {offer['supplier_name']}",
                                   reason + " | " + " ".join(check["approval_reasons"]), run_id, case_id, po_id)
        return {"po_id": po_id, "status": status, "quantity": quantity, "approval_id": approval_id,
                "message": "Valid, but waiting for human approval: " + " ".join(check["approval_reasons"]),
                "warnings": check["warnings"]}

    return {"po_id": po_id, "status": status, "quantity": quantity, "supplier_response": supplier_confirm(po_id),
            "warnings": check["warnings"]}


def change_order(po_id, new_quantity, daily_demand, reason, run_id=None):
    po = get_po(po_id)
    if po["status"] not in ("submitted", "confirmed"):
        raise OrderError(f"{po_id} is {po['status']} and cannot be changed.")
    if new_quantity <= po["quantity"]:
        raise OrderError("Only increases are supported. Use request_po_cancellation to reduce an order.")

    check = validate_order(po["node_id"], po["sku"], po["supplier_id"], new_quantity, daily_demand, po_id=po_id)
    if not check["valid"]:
        raise OrderError("Change rejected by validation: " + " ".join(check["errors"]))
    if check["needs_approval"]:
        raise OrderError("Change needs approval (" + " ".join(check["approval_reasons"]) +
                         "). Create a separate order so it goes to the approval queue.")

    extra = new_quantity - po["quantity"]
    change_budget(po, extra)
    db.execute("UPDATE purchase_orders SET quantity = ?, run_id = COALESCE(run_id, ?), note = note || ? WHERE po_id = ?",
               (new_quantity, run_id, f" | +{extra}: {reason}", po_id))
    reply = supplier_confirm(po_id, requested_extra=extra)
    return {"po_id": po_id, "added_confirmed": reply["confirmed_qty"] - (po["confirmed_qty"] or 0),
            "supplier_response": reply}


def accept_partial(po_id, note):
    po = get_po(po_id)
    if po["status"] != "partially_confirmed":
        raise OrderError(f"{po_id} is {po['status']}, not partially confirmed.")
    released = po["quantity"] - po["confirmed_qty"]
    change_budget(po, -released)
    db.execute("UPDATE purchase_orders SET quantity = confirmed_qty, status = 'confirmed', note = note || ? WHERE po_id = ?",
               (f" | partial accepted: {note}", po_id))
    return {"po_id": po_id, "final_quantity": po["confirmed_qty"], "units_released": released,
            "budget_released": round(released * po["unit_cost"], 2)}


def cancel(po_id):
    po = get_po(po_id)
    change_budget(po, -po["quantity"])
    db.execute("UPDATE purchase_orders SET status = 'cancelled' WHERE po_id = ?", (po_id,))


# ==========================================
# Approval queue
# ==========================================
def add_approval(kind, title, details, run_id=None, case_id=None, po_id=None):
    approval_id = "APR-" + uuid.uuid4().hex[:6].upper()
    db.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, NULL)",
               (approval_id, run_id, case_id, kind, po_id, title, details, db.now()))
    return approval_id


def decide(approval_id, approve, note=""):
    approval = db.query_one("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
    if approval is None:
        raise OrderError(f"{approval_id} not found.")
    if approval["status"] != "pending":
        raise OrderError(f"{approval_id} is already {approval['status']}.")

    result = {}
    if approval["kind"] == "purchase_order":
        if approve:
            db.execute("UPDATE purchase_orders SET status = 'submitted' WHERE po_id = ?", (approval["po_id"],))
            reply = supplier_confirm(approval["po_id"])
            result["supplier_response"] = reply
            if reply["status"] != "confirmed":
                result["follow_up_case"] = open_shortfall_case(approval["po_id"], reply)
        else:
            cancel(approval["po_id"])
    elif approval["kind"] == "cancel_order" and approve:
        cancel(approval["po_id"])

    if approval["kind"] == "escalation":
        status = "acknowledged" if approve else "dismissed"
    else:
        status = "approved" if approve else "rejected"
    db.execute("UPDATE approvals SET status = ?, decided_at = ?, note = ? WHERE approval_id = ?",
               (status, db.now(), note, approval_id))

    if approval["case_id"]:
        still_pending = db.query_one("SELECT COUNT(*) AS n FROM approvals WHERE case_id = ? AND status = 'pending'",
                                     (approval["case_id"],))["n"]
        if not still_pending:
            db.execute("UPDATE cases SET status = 'resolved' WHERE case_id = ?", (approval["case_id"],))

    result["approval"] = db.query_one("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
    return result


def open_shortfall_case(po_id, reply):
    """An approved order that comes back short becomes a new case for the agent."""
    po = get_po(po_id)
    count = db.query_one("SELECT COUNT(*) AS n FROM cases WHERE case_id LIKE 'AUTO-%'")["n"]
    case_id = f"AUTO-{count + 1:03d}"
    db.execute("INSERT INTO cases VALUES (?, 'supplier_shortfall', ?, ?, ?, ?, ?, NULL, NULL, 'open', ?)",
               (case_id, f"Supplier shortfall on {po_id}: {reply['confirmed_qty']} of {reply['requested_qty']} units",
                reply["message"] + " Decide what should happen next.", po["node_id"], po["sku"], po_id, db.now()))
    return case_id
