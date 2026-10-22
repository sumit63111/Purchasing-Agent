import pytest
from fastapi.testclient import TestClient

from app import db, orders
from app.agent.runner import run_case
from app.agent.tools import run_tool
from app.checks import validate_order
from app.planning import demand_signals, project


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    db.DB_PATH = str(tmp_path / "test.db")
    db.reset()


# ==========================================
# Demand signals
# ==========================================
def test_detects_sustained_demand_shift():
    signals = demand_signals("BOG-01", "ELECTRO-500ML")
    assert signals["reference_daily_demand"] > 60
    assert any("sustained" in f for f in signals["flags"])


def test_ignores_one_off_bulk_order():
    signals = demand_signals("MEX-02", "PLATES-50")
    assert signals["avg_last_7"] > 90
    assert 35 <= signals["reference_daily_demand"] <= 45


def test_flags_broken_sales_feed():
    assert demand_signals("BOG-01", "YOGURT-400G")["data_ok"] is False


def test_projection_finds_stockout_before_open_po():
    assert project("BOG-01", "ELECTRO-500ML", 71.4)["stockout_day"] == 4


# ==========================================
# Order validation
# ==========================================
def test_recommended_800_breaks_budget_and_storage():
    check = validate_order("BOG-01", "OIL-1L", "SUP-01", 800, 40)
    assert not check["valid"]
    assert any("budget" in e for e in check["errors"])
    assert any("storage" in e for e in check["errors"])


def test_moq_and_case_pack():
    check = validate_order("BOG-01", "OIL-1L", "SUP-01", 50, 40)
    assert any("minimum" in e for e in check["errors"])
    assert any("case pack" in e for e in check["errors"])


def test_large_order_needs_approval():
    check = validate_order("MEX-02", "RICE-5KG", "SUP-03", 480, 60)
    assert check["valid"] and check["needs_approval"]


def test_max_feasible_respects_budget():
    check = validate_order("SAO-03", "DIAPER-M", "SUP-11", 600, 70)
    assert check["max_feasible_qty"] == 384


# ==========================================
# Feedback loop
# ==========================================
def test_supplier_short_ships_and_verification_catches_it():
    case = db.query_one("SELECT * FROM cases WHERE case_id = 'SHORT-201'")
    run = {"run_id": "TEST", "case": case, "mode": "test", "attempts": 0, "done": False,
           "decision": None, "verification": None, "tools_called": []}

    run_tool(run, "accept_partial_confirmation", {"po_id": "PO-2001", "note": "test"})
    result = run_tool(run, "create_purchase_order", {"supplier_id": "SUP-05", "quantity": 220,
                                                     "daily_demand": 50, "reason": "test"})
    assert result["supplier_response"]["confirmed_qty"] == 100

    submit = {"decision": "modify", "quantity": 220, "daily_demand_used": 50, "summary": "s",
              "key_factors": [], "risks": []}
    feedback = run_tool(run, "submit_decision", submit)
    codes = {i["code"] for i in feedback["issues"]}
    assert "unresolved_partial" in codes
    assert not run["done"]


def test_approved_order_that_comes_back_short_opens_a_new_case():
    db.execute("UPDATE supplier_items SET capacity = 200 WHERE supplier_id = 'SUP-03' AND sku = 'RICE-5KG'")
    result = orders.create_order("MEX-02", "RICE-5KG", "SUP-03", 480, 60, "test", "test")
    decision = orders.decide(result["approval_id"], True)
    assert decision["supplier_response"]["confirmed_qty"] == 200
    assert decision["follow_up_case"].startswith("AUTO-")


# ==========================================
# End to end: every scenario with the rules agent
# ==========================================
def test_all_scenarios_pass_evals():
    from evals.run_evals import EXPECTED, grade

    for case_id, expected in EXPECTED.items():
        db.reset()
        run = run_case(case_id, "rules")
        run["case_sku"] = db.query_one("SELECT sku FROM cases WHERE case_id = ?", (case_id,))["sku"]
        graded = grade(run, expected)
        failed = [c for c in graded["checks"] if not c["passed"]]
        assert not failed, f"{case_id}: {failed}"


def test_api_runs_a_case():
    from app.main import app

    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/api/cases").json()) == 10
    run = client.post("/api/cases/REC-101/run?mode=rules&wait=true").json()
    assert run["decision"] == "modify"
    assert client.get(f"/api/runs/{run['run_id']}").json()["status"] == "completed"
