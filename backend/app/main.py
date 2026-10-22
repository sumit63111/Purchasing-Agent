import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app import config, db, orders, planning
from app.agent import runner


@asynccontextmanager
async def lifespan(app):
    db.ensure_db()
    yield


app = FastAPI(title="Purchasing Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

EVAL_REPORT = config.BASE_DIR / "evals" / "results" / "latest.json"


# ==========================================
# Health Check API
# ==========================================
@app.get("/health")
async def health():
    return {"status": "ok", "agent_mode": config.pick_agent_mode(), "provider": config.LLM_PROVIDER,
            "model": config.LLM["model"]}


# ==========================================
# Cases API
# ==========================================
@app.get("/api/cases")
def list_cases():
    return db.query("""SELECT c.*, p.name AS product_name FROM cases c JOIN products p ON p.sku = c.sku
                       ORDER BY c.created_at, c.case_id""")


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    case = db.query_one("SELECT * FROM cases WHERE case_id = ?", (case_id,))
    if case is None:
        raise HTTPException(404, f"Case {case_id} not found")
    node_id, sku = case["node_id"], case["sku"]
    demand = planning.demand_signals(node_id, sku)
    return {
        "case": case,
        "item": planning.get_item(node_id, sku),
        "demand": demand,
        "open_orders": planning.open_orders(node_id, sku),
        "suppliers": planning.supplier_options(sku),
        "requirement": planning.requirement(node_id, sku, demand["reference_daily_demand"]),
    }


@app.post("/api/cases/{case_id}/run")
def run_case(case_id: str, mode: str = "auto", wait: bool = False):
    if db.query_one("SELECT 1 AS x FROM cases WHERE case_id = ?", (case_id,)) is None:
        raise HTTPException(404, f"Case {case_id} not found")
    if config.pick_agent_mode(mode) == "llm" and not config.LLM["api_key"]:
        raise HTTPException(400, f"LLM mode needs an API key for '{config.LLM_PROVIDER}' in .env. Use rules mode instead.")
    if wait:
        return runner.run_case(case_id, mode)
    return {"run_id": runner.start_in_background(case_id, mode)}


# ==========================================
# Runs API
# ==========================================
@app.get("/api/runs")
def list_runs(case_id: str | None = None):
    sql = "SELECT run_id, case_id, mode, status, decision, quantity, summary, started_at, finished_at FROM runs"
    if case_id:
        return db.query(sql + " WHERE case_id = ? ORDER BY started_at DESC", (case_id,))
    return db.query(sql + " ORDER BY started_at DESC")


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = runner.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return run


# ==========================================
# Purchase Orders API
# ==========================================
@app.get("/api/orders")
def list_orders():
    return db.query("""SELECT po.*, p.name AS product_name, s.name AS supplier_name
                       FROM purchase_orders po
                       JOIN products p ON p.sku = po.sku
                       JOIN suppliers s ON s.supplier_id = po.supplier_id
                       ORDER BY po.created_at DESC""")


# ==========================================
# Approvals API
# ==========================================
class Decision(BaseModel):
    approve: bool
    note: str = ""


@app.get("/api/approvals")
def list_approvals(status: str | None = None):
    if status:
        return db.query("SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC", (status,))
    return db.query("SELECT * FROM approvals ORDER BY status = 'pending' DESC, created_at DESC")


@app.post("/api/approvals/{approval_id}/decide")
def decide(approval_id: str, body: Decision):
    try:
        return orders.decide(approval_id, body.approve, body.note)
    except orders.OrderError as e:
        raise HTTPException(400, str(e))


# ==========================================
# Policy / Evals / Reset API
# ==========================================
@app.get("/api/policy")
def policy():
    return {
        "auto_approve_limit": config.AUTO_APPROVE_LIMIT,
        "max_price_premium": config.MAX_PRICE_PREMIUM,
        "max_cover_days": config.MAX_COVER_DAYS,
        "min_fill_rate": config.MIN_FILL_RATE,
        "needs_human": ["orders above the auto-approve limit", "suppliers above the price premium",
                        "any cancellation", "budget or storage increases", "escalations"],
    }


@app.get("/api/evals/latest")
def latest_eval():
    if not EVAL_REPORT.exists():
        raise HTTPException(404, "No eval report yet. Run: python -m evals.run_evals")
    return json.loads(EVAL_REPORT.read_text(encoding="utf-8"))


@app.post("/api/reset")
def reset():
    db.reset()
    return {"status": "ok"}
