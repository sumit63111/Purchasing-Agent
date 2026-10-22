import json
import threading
import traceback
import uuid

import openai

from app import config, db, orders
from app.agent.llm_agent import run_llm_agent
from app.agent.rule_agent import run_rule_agent
from app.agent.tools import add_step


# ==========================================
# Start a run
# ==========================================
def create_run(case_id, mode=None):
    mode = config.pick_agent_mode(mode)
    run_id = "RUN-" + uuid.uuid4().hex[:8].upper()
    db.execute("INSERT INTO runs (run_id, case_id, mode, status, started_at) VALUES (?, ?, ?, 'running', ?)",
               (run_id, case_id, mode, db.now()))
    db.execute("UPDATE cases SET status = 'in_progress' WHERE case_id = ?", (case_id,))
    return run_id


def start_in_background(case_id, mode=None):
    run_id = create_run(case_id, mode)
    threading.Thread(target=execute_run, args=(run_id,), daemon=True).start()
    return run_id


def run_case(case_id, mode=None):
    run_id = create_run(case_id, mode)
    execute_run(run_id)
    return get_run(run_id)


# ==========================================
# Execute
# ==========================================
def execute_run(run_id):
    row = db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    case = db.query_one("SELECT * FROM cases WHERE case_id = ?", (row["case_id"],))
    run = {"run_id": run_id, "case": case, "mode": row["mode"], "attempts": 0, "done": False,
           "decision": None, "verification": None, "tools_called": []}
    add_step(run_id, "system", "start", {"mode": run["mode"], "provider": config.LLM_PROVIDER if run["mode"] == "llm" else None,
                                    "model": config.LLM["model"] if run["mode"] == "llm" else None})

    error = None
    try:
        if run["mode"] == "llm":
            run_llm_agent(run)
        else:
            run_rule_agent(run)
    except openai.APIError as e:
        error = f"{config.LLM_PROVIDER} API error: {e}"
    except Exception as e:
        error = str(e)
        add_step(run_id, "system", "crash", {"traceback": traceback.format_exc()})

    finish(run, error)


def finish(run, error):
    decision = run["decision"]
    passed = bool(run["verification"] and run["verification"]["passed"])

    if decision is None:
        status = "failed"
    elif passed:
        status = "completed"
    else:
        status = "needs_review"

    # Anything that did not end cleanly goes to a human
    if status != "completed":
        issues = (run["verification"] or {}).get("issues", [])
        orders.add_approval("escalation", f"Agent run needs review: {run['case']['case_id']}",
                            (error or "Verification still failing.") + " " + " ".join(i["message"] for i in issues),
                            run["run_id"], run["case"]["case_id"])

    db.execute(
        """UPDATE runs SET status = ?, decision = ?, quantity = ?, summary = ?, decision_json = ?,
           verification_json = ?, error = ?, finished_at = ? WHERE run_id = ?""",
        (status, decision and decision["decision"], decision and decision["quantity"], decision and decision["summary"],
         json.dumps(decision), json.dumps(run["verification"]), error, db.now(), run["run_id"]),
    )

    pending = {a["kind"] for a in db.query("SELECT kind FROM approvals WHERE case_id = ? AND status = 'pending'",
                                           (run["case"]["case_id"],))}
    if pending - {"escalation"}:
        case_status = "awaiting_approval"
    elif pending:
        case_status = "escalated"
    else:
        case_status = "resolved"
    db.execute("UPDATE cases SET status = ? WHERE case_id = ?", (case_status, run["case"]["case_id"]))
    add_step(run["run_id"], "system", "finish", {"status": status, "error": error})


# ==========================================
# Read
# ==========================================
def get_run(run_id):
    run = db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    if run is None:
        return None
    run["decision_detail"] = json.loads(run.pop("decision_json") or "null")
    run["verification"] = json.loads(run.pop("verification_json") or "null")
    run["steps"] = db.query("SELECT id, kind, name, payload_json, created_at FROM run_steps WHERE run_id = ? ORDER BY id",
                            (run_id,))
    for step in run["steps"]:
        step["payload"] = json.loads(step.pop("payload_json") or "null")
    run["orders"] = db.query("SELECT * FROM purchase_orders WHERE run_id = ?", (run_id,))
    run["approvals"] = db.query("SELECT * FROM approvals WHERE run_id = ?", (run_id,))
    run["tools_called"] = [s["name"] for s in run["steps"] if s["kind"] == "tool_call"]
    return run
