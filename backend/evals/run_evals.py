"""Run every scenario on a fresh database and grade the agent.

    python -m evals.run_evals              # rules agent (no API key needed)
    python -m evals.run_evals --mode llm   # LLM agent (provider from .env)
    python -m evals.run_evals --case REC-101
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

from app import config, db

EVAL_DIR = Path(__file__).parent
EXPECTED = json.loads((EVAL_DIR / "expected.json").read_text(encoding="utf-8"))
INFO_TOOLS = ["get_inventory", "get_demand", "get_open_orders", "get_suppliers", "get_budget"]
ACTION_TOOLS = ["create_purchase_order", "increase_order_quantity", "accept_partial_confirmation",
                "request_po_cancellation"]


# ==========================================
# Grading
# ==========================================
def units_ordered(run):
    """New units the run actually ordered, taken from the trace rather than the agent's own claim."""
    total = 0
    for step in run["steps"]:
        if step["kind"] != "tool_result":
            continue
        result = step["payload"]
        if step["name"] == "create_purchase_order":
            total += result["supplier_response"]["confirmed_qty"] if "supplier_response" in result else result["quantity"]
        elif step["name"] == "increase_order_quantity":
            total += result["added_confirmed"]
    return total


def grade(run, expected):
    checks = []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    decision = run["decision_detail"] or {}
    verification = run["verification"] or {}
    tools = run["tools_called"]
    orders = [o for o in run["orders"] if o["status"] not in ("cancelled", "rejected")]

    # Was the decision correct?
    check("decision", run["decision"] in expected["decision"],
          f"got {run['decision']}, expected {' or '.join(expected['decision'])}")

    low, high = expected["quantity"]
    qty = units_ordered(run)
    check("quantity", low <= qty <= high, f"ordered {qty} (agent reported {run['quantity']}), expected {low}-{high}")

    # Did it gather the information first?
    first_action = next((i for i, t in enumerate(tools) if t in ACTION_TOOLS), len(tools))
    missing = [t for t in INFO_TOOLS if t not in tools[:first_action]]
    check("information", not missing, "missing before acting: " + ", ".join(missing) if missing else "all gathered")

    # Did it respect constraints?
    within = verification.get("budget_left", 0) >= 0 and verification.get("peak_stock", 0) <= verification.get("storage_space", 0)
    check("constraints", within, f"budget left {verification.get('budget_left')}, "
                                 f"peak {verification.get('peak_stock')} / space {verification.get('storage_space')}")

    # Did it take the right action?
    problems = []
    if expected["orders"] and not orders:
        problems.append("expected an order")
    if not expected["orders"] and orders:
        problems.append("ordered when it should not")
    if expected.get("escalate") and not any(a["kind"] == "escalation" for a in run["approvals"]):
        problems.append("expected an escalation")
    if expected.get("supplier") and not any(o["supplier_id"] == expected["supplier"] for o in orders):
        problems.append(f"expected supplier {expected['supplier']}")
    if expected.get("demand"):
        d_low, d_high = expected["demand"]
        used = decision.get("daily_demand_used", 0)
        if not d_low <= used <= d_high:
            problems.append(f"planned with {used}/day, expected {d_low}-{d_high}")
    check("action", not problems, "; ".join(problems) or "ok")

    # Did it validate the result?
    check("validated", verification.get("passed"),
          f"{len(verification.get('issues', []))} issue(s) after {tools.count('submit_decision')} submission(s)")

    # What happened when the first action did not work?
    if expected.get("recovery"):
        partials = db.query("SELECT po_id FROM purchase_orders WHERE sku = ? AND status = 'partially_confirmed'",
                            (run["case_sku"],))
        check("recovery", not partials and verification.get("stockout_day") is None,
              "partial confirmations resolved and coverage restored" if not partials else
              "unresolved: " + ", ".join(p["po_id"] for p in partials))

    passed = sum(c["passed"] for c in checks)
    return {"score": round(passed / len(checks), 2), "passed": passed == len(checks), "checks": checks}


# ==========================================
# Run
# ==========================================
def run_all(mode="rules", only=None):
    from app.agent.runner import run_case

    db.DB_PATH = str(config.BASE_DIR / "data" / "eval.db")
    results = []
    for case_id, expected in EXPECTED.items():
        if only and case_id != only:
            continue
        db.reset()
        sku = db.query_one("SELECT sku FROM cases WHERE case_id = ?", (case_id,))["sku"]
        run = run_case(case_id, mode)
        run["case_sku"] = sku
        graded = grade(run, expected)
        results.append({
            "case_id": case_id,
            "title": db.query_one("SELECT title FROM cases WHERE case_id = ?", (case_id,))["title"],
            "why": expected["why"],
            "expected_decision": expected["decision"],
            "decision": run["decision"],
            "quantity": units_ordered(run),
            "reported_quantity": run["quantity"],
            "run_status": run["status"],
            "verification_attempts": run["tools_called"].count("submit_decision"),
            **graded,
        })
        print(f"{case_id:15} {str(run['decision']):12} {graded['score']:>5}  "
              + " ".join(("+" if c["passed"] else "-") + c["name"] for c in graded["checks"]))

    report = {
        "mode": config.pick_agent_mode(mode),
        "provider": config.LLM_PROVIDER if config.pick_agent_mode(mode) == "llm" else None,
        "model": config.LLM["model"] if config.pick_agent_mode(mode) == "llm" else None,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "cases": len(results),
            "passed": sum(r["passed"] for r in results),
            "score": round(sum(r["score"] for r in results) / max(len(results), 1), 2),
        },
        "results": results,
    }
    out = EVAL_DIR / "results"
    out.mkdir(exist_ok=True)
    (out / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n{report['summary']['passed']}/{report['summary']['cases']} cases fully passed, "
          f"average score {report['summary']['score']}. Report: evals/results/latest.json")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="rules", choices=["rules", "llm", "auto"])
    parser.add_argument("--case")
    args = parser.parse_args()
    run_all(args.mode, args.case)
