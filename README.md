# AI Purchasing Agent

An agent that automates part of a buyer's job in a quick-commerce business. It takes a purchasing
situation, works out what is really going on, makes a decision, places or changes purchase orders,
and then checks that the result of those actions is actually acceptable. When it can't fix
something, it hands it to a human buyer with the numbers attached.

It is not a chatbot that answers questions. Every decision ends in actions on a mock ERP, and every
action is checked twice: before it runs and after it lands.

- **Full stack:** FastAPI backend, React UI, and SQLite as a mock ERP.
- **Two agents, same tools:**
  - an LLM agent (OpenRouter or Google Gemini, set in `.env`);
  - a deterministic rule agent that runs with no API key and gives the LLM a baseline.
- **Feedback loop:** each order is validated before it is placed. A mock supplier can confirm less
  than was ordered. The final state is checked independently, and the agent must fix any problems
  that check finds.
- **Human in the loop:** an approval queue for big or expensive orders, cancellations and escalations.
- **Evaluation:** 10 test cases covering all four scenarios in the brief, graded automatically.

---

## Contents

1. [Quick start](#quick-start)
2. [Configuration](#configuration)
3. [Choosing a model](#choosing-a-model)
4. [Using the app](#using-the-app)
5. [Test scenarios](#test-scenarios)
6. [Architecture](#architecture)
7. [Approach](#approach)
8. [Agent tools](#agent-tools)
9. [Human approval policy](#human-approval-policy)
10. [Validation and the feedback loop](#validation-and-the-feedback-loop)
11. [Evaluation](#evaluation)
12. [API reference](#api-reference)
13. [Mock data](#mock-data)
14. [Troubleshooting](#troubleshooting)
15. [Limitations and next steps](#limitations-and-next-steps)

---

## Quick start

**You need:** Python 3.11+, Node 18+ and npm. An LLM API key is optional.

### 1. Configure

```bash
cp .env.example .env
```

Open `.env` and add a key for one provider (see [Configuration](#configuration)):

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-oss-120b
```

With no key, the app uses the rule agent automatically, so everything still works offline.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Check: `curl http://localhost:8000/health` shows the active mode, provider and model.

The SQLite database (`backend/data/purchasing.db`) is created and seeded on first start.

### 3. Frontend (second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server forwards `/api` to the backend on port 8000.

### 4. Tests and evaluation

```bash
cd backend
pytest                                   # 12 tests, offline
python -m evals.run_evals                # grade the rule agent on all 10 cases
python -m evals.run_evals --mode llm     # grade the LLM agent (uses API credits)
python -m evals.run_evals --mode llm --case SHORT-201   # one case only
```

---

## Configuration

All settings live in `.env` at the repo root. `.env` is git-ignored; `.env.example` is the template.

| Variable | Default | What it does |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | `openrouter` or `gemini` |
| `OPENROUTER_API_KEY` | | Key from https://openrouter.ai/keys |
| `OPENROUTER_MODEL` | `openai/gpt-oss-120b` | Any OpenRouter model that supports tool calling |
| `GEMINI_API_KEY` | | Key from https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name |
| `AGENT_MODE` | `auto` | `auto` uses the LLM if the chosen provider has a key, otherwise the rule agent; can also be `llm` or `rules` |
| `AGENT_MAX_TURNS` | `30` | Maximum model turns per run before it is handed to a human |
| `AGENT_MAX_TOKENS` | `4000` | Output tokens per model reply. Tool calls are short, so keep this low on small credit balances |
| `SIMULATION_DATE` | `2026-10-22` | "Today" for the mock data. All dates are relative to it |
| `AUTO_APPROVE_LIMIT` | `3000` | Orders above this value ($) wait for human approval |
| `MAX_PRICE_PREMIUM` | `0.10` | Suppliers more than 10% above the primary price need approval |
| `MAX_COVER_DAYS` | `30` | Days of cover above which an order is flagged as overstock |
| `DATABASE_PATH` | `backend/data/purchasing.db` | SQLite file |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed UI origins |

You can also pick the mode per run, either in the UI's mode selector or with
`POST /api/cases/{id}/run?mode=llm|rules`.

---

## Choosing a model

The agent makes 8–15 tool calls per case and has to keep numbers straight across them. Reliable
tool calling matters more than raw size. Prices are OpenRouter list prices per million tokens
(input / output), checked when this was written.

| Model (`OPENROUTER_MODEL`) | Price | Use it for |
|---|---|---|
| `openai/gpt-oss-120b` | $0.15 / $0.60 | **Default.** Open-weight model with solid tool calling at a very low price. A case costs well under a cent. |
| `google/gemini-2.5-flash` | $0.30 / $2.50 | Fast and cheap, good at tool calling. |
| `anthropic/claude-sonnet-5.5` | $2 / $10 | Stronger multi-step reasoning when quality matters more than cost. |
| `anthropic/claude-haiku-5.5` | $0.10 / $0.50 | Cheapest paid option. Good for running the eval suite many times. |
| `google/gemini-3.8-flash` | $0.83 / $4.12 | Fast alternative. |
| `openai/gpt-6-sol` | $2 / $10 | Another option to compare against. |
| `anthropic/claude-opus-5.5` | $4 / $20 | Hardest reasoning, when quality matters more than cost. |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | free | Works with a free-tier key, but heavily rate limited. |

**Free-tier OpenRouter keys** (no credit added) can only call `:free` models, and only a limited
number of requests per day. A full 10-case LLM eval needs roughly 80–120 requests, so add a few
dollars of credit for regular use.

The same model is available straight from Google: set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY` and
`GEMINI_MODEL=gemini-2.5-flash`.

---

## Using the app

The UI has four tabs. The header has the agent mode selector (auto / llm / rules) and **Reset demo
data**, which puts the database back to its starting state.

| Tab | What you see |
|---|---|
| **Cases** | All purchasing situations. Selecting one shows stock, demand vs forecast (28-day chart), data flags, open POs, suppliers and the computed requirement. **Run agent** starts a run and streams its trace live: each tool call and result, verification attempts, and the final decision card. |
| **Approvals** | The human queue: orders waiting for approval, cancellation requests and escalations. Approving an order sends it to the mock supplier and shows the reply. |
| **Purchase Orders** | Every PO with status, confirmed quantity, arrival date and which run created it. |
| **Evaluation** | Scorecard from the latest `python -m evals.run_evals`. |

### Suggested demo (5 minutes)

1. **REC-101.** Run the agent. It rejects the 800-unit recommendation, computes a need of about
   160 units, orders 168 (full cases), and verification passes.
2. **SHORT-201.** Run the agent. The supplier only confirmed 250 of 500. The agent accepts the 250,
   orders the gap from an alternate supplier, and that supplier also short-ships (100 of 220). The
   agent accepts the 100 and orders the last 120 from a third supplier. That supplier is 15%
   pricier, so the order lands in **Approvals**.
3. **Approvals.** Approve it and the supplier confirms. If a supplier confirms less than an
   approved order, a new `AUTO-xxx` case opens automatically for the agent.
4. **REC-104.** Run the agent. The sales data is broken, so it refuses to buy and escalates.
5. **Evaluation.** Shows the scorecard.

---

## Test scenarios

All four scenarios in the brief run end to end. Each has at least one case where the obvious
answer is wrong.

| Case | Scenario | What makes it hard | Expected outcome |
|---|---|---|---|
| REC-101 | 1. Recommendation review | 800 recommended, real need ~160; 800 breaks budget and storage | **modify** to ~168 |
| REC-102 | 1. Recommendation review | Recommendation is right, but above the auto-approve limit | **accept**, PO waits for approval |
| REC-103 | 1. Recommendation review | Stock + open PO already cover ~48 days | **reject** |
| REC-104 | 1. Recommendation review | 5 zero-sales days while 420 units are "on hand", count 34 days old | **investigate**, escalate, no PO |
| SHORT-201 | 2. Supplier shortfall | 250 of 500 confirmed; the first alternate also short-ships | **modify**: accept partial, re-source twice, approval for pricey supplier |
| SHORT-202 | 2. Supplier shortfall | 250 confirmed is already enough | **accept** partial, no new PO |
| DEMAND-301 | 3. Demand change | Sustained jump from 30 to 71/day; stock runs out before the primary supplier can deliver | **modify**: bridge order from fast supplier + increase open PO |
| DEMAND-302 | 3. Demand change | The "spike" is one bulk order of 420 units | **accept** current plan |
| CONSTRAINT-401 | 4. Purchasing constraint | Need ~600, budget fits 384, storage fits ~530 | **modify**: buy 384, escalate the rest |
| CONSTRAINT-402 | 4. Purchasing constraint | Primary supplier's MOQ (300) does not fit the budget | **modify**: switch to supplier with MOQ 48 |

---

## Architecture

Diagrams (system and feedback loop sequence) are in [docs/architecture.md](docs/architecture.md).

```
React UI  --REST-->  FastAPI (main.py)
                         |
                      Runner (runner.py)  -- stores every step, escalates failed runs
                       /            \
          LLM agent (llm_agent.py)   Rule agent (rule_agent.py)
                       \            /
                    Tools (tools.py)   <- the only way an agent touches data
                   /        |        \
         planning.py    checks.py    orders.py --> mock supplier
         demand, stock  validate,    POs, budget,
         projection     verify       approvals
                   \        |        /
                    SQLite mock ERP (db.py)
```

```
backend/
  app/
    main.py            REST API
    config.py          settings, LLM provider, purchasing policy
    db.py              SQLite helpers, schema, seeding from mock_data
    planning.py        data reads, demand estimate, stock projection, requirement
    checks.py          validate_order (before acting), verify_outcome (after acting)
    orders.py          purchase orders, budget, mock supplier replies, approval queue
    agent/
      tools.py         15 tool definitions and the dispatcher that records the trace
      llm_agent.py     LLM tool-use loop (OpenAI-compatible: OpenRouter / Gemini)
      rule_agent.py    deterministic playbook (offline mode and baseline)
      runner.py        starts runs, stores results, escalates failed runs
  mock_data/scenarios.json   all mock data
  evals/expected.json        expected outcome per case, with the reasoning
  evals/run_evals.py         runs and grades every case
  tests/test_agent.py        pytest suite
frontend/                    React + Vite UI
docs/architecture.md         diagrams
```

**Tech:** Python, FastAPI, SQLite, `openai` SDK (as the client for OpenRouter and Gemini), React 18,
Vite.

---

## Approach

### Breaking the problem down

A buyer's decision comes down to four questions. The tools follow them:

1. **What is really happening?** Stock, open orders, sales vs forecast, and whether the data can be
   trusted.
2. **How much is needed, and by when?** Target stock = daily demand × (lead time + review period +
   safety days), compared with on hand + on order. A day-by-day projection shows whether stock runs
   out before a new order could arrive.
3. **What can actually be bought?** Supplier terms (MOQ, case pack, lead time, price, fill rate),
   budget, storage space and shelf life.
4. **Did it work?** Supplier confirmations, then an independent check of the final state.

### Design choices

- **The LLM decides, code does the maths.** The agent chooses which demand figure to trust, which
  supplier to use and when to escalate. Targets, projections, MOQ rounding and the largest feasible
  quantity come from tools, so arithmetic mistakes can't creep in through the prompt.
- **The recommendation is a hypothesis.** It is tested against the computed need and every hard
  limit before anything is ordered.
- **Demand is estimated, not copied.** `get_demand` tells three things apart:
  - a sustained shift (most of the last 7 days elevated);
  - a one-off bulk order (lots of units from few orders);
  - broken data (zero sales while stock is on hand, or a stale stock count).
  Broken data means no purchase.
- **Supplier capacity is hidden.** The agent sees fill rates but not real stock. Suppliers reveal
  what they can ship only when an order reaches them, as in real life. This is what drives the
  feedback loop.
- **Guardrails are in code, not in the prompt.** Order creation re-runs validation and refuses
  invalid orders, the approval policy is enforced in `orders.py`, and tools can only act on the
  case's own SKU and node.
- **Same tools for both agents.** The rule agent goes through the exact same tools, so it works
  offline, produces the same trace, and is a fair baseline in the evals.
- **Failures land with a human.** A crash, running out of turns, no decision, or verification
  still failing after 3 attempts all mark the run `needs_review` and create an escalation.

### Decision values

| Decision | Meaning |
|---|---|
| `accept` | The recommendation or current plan is right (may still place the recommended order or accept a partial confirmation) |
| `modify` | The plan needed changing: quantity, supplier, extra or larger orders |
| `reject` | No purchase is needed |
| `investigate` | Data is not good enough to decide; escalate and do not buy |
| `escalate` | The decision is outside the agent's authority |

---

## Agent tools

| Tool | Type | Purpose |
|---|---|---|
| `get_case` | read | The case, its recommendation and the referenced PO |
| `get_inventory` | read | On hand, reserved, last physical count, shelf life, storage space |
| `get_demand` | read | Forecast vs 28 days of sales, outliers, shifts, data-quality flags, reference demand |
| `get_open_orders` | read | Open POs with confirmed quantity and arrival day |
| `get_suppliers` | read | Cost, premium vs primary, MOQ, case pack, lead time, fill rate |
| `get_budget` | read | Category budget limit, used and remaining |
| `calculate_need` | maths | Target stock, inventory position, net requirement |
| `project_stock` | maths | Day-by-day projection with open and proposed orders; stockout day |
| `check_order` | check | Dry run of every rule for a proposed order; returns `max_feasible_qty` |
| `create_purchase_order` | action | Validates and sends a PO; may need approval; supplier may short-ship |
| `increase_order_quantity` | action | Increase an open PO; supplier re-confirms the extra units |
| `accept_partial_confirmation` | action | Accept what was confirmed, close the rest, release budget |
| `request_po_cancellation` | action | Ask a buyer to cancel; never cancels directly |
| `escalate_to_buyer` | action | Hand a problem to the buyer with details and a recommendation |
| `submit_decision` | final | Record the decision and run the independent outcome check |

---

## Human approval policy

| Action | Agent alone | Needs a human |
|---|---|---|
| Read data, run projections and checks | yes | |
| Create a PO | if it passes all checks | value above `AUTO_APPROVE_LIMIT` ($3,000), or price more than `MAX_PRICE_PREMIUM` (10%) above the primary supplier |
| Increase an open PO | if it passes all checks | if the increase would need approval (agent must create a separate order instead) |
| Accept a partial confirmation | yes | |
| Cancel a PO | | always |
| Raise budget or storage | | always (via escalation) |
| Buy when data failed quality checks | | always (escalate instead) |

Orders that need approval are created as `pending_approval`. Their budget is reserved, and they
are only sent to the supplier once a buyer approves them in the UI.

---

## Validation and the feedback loop

There are three checks, at three points in time.

**1. Before acting: `check_order` / `validate_order`.**

- Hard rules (the order is refused): MOQ, case pack, budget remaining, peak stock vs storage space,
  days of cover vs shelf life.
- Soft rules (warnings): overstock above `MAX_COVER_DAYS`, an order that arrives after the
  projected stockout, a supplier with a low fill rate.
- It also returns `max_feasible_qty`, the largest order that passes every hard rule. That is how
  the agent shrinks an order to fit a constraint.
- `create_purchase_order` runs the same check again, so the guardrail does not depend on the agent
  remembering to call it.

**2. Supplier reply.** Every order gets a confirmation: confirmed, partially confirmed or rejected.
A partial confirmation is an open gap. The agent must accept it, then source the rest elsewhere or
escalate.

**3. After acting: `verify_outcome`.** This runs on `submit_decision` and checks the real state,
not what the agent says it did:

| Check | Fails when |
|---|---|
| Coverage | Projected stockout before the next order cycle can land. Demand used is the higher of the agent's figure and the observed demand, so an optimistic estimate cannot hide a gap. A gap the agent has escalated becomes a warning. |
| Budget | Category budget is overspent |
| Storage | Peak stock over 30 days exceeds storage space |
| Unresolved partials | Any PO for the SKU is still partially confirmed |
| Decision vs actions | `reject` or `investigate` with orders placed; `investigate` or `escalate` without an escalation |
| Bad data | Orders placed on data that failed quality checks, without escalating |

When a check fails, the issues go back to the agent as a tool error. The agent fixes them and
submits again, up to 3 attempts. If it still fails, the run is marked `needs_review` and escalated.

The loop continues after the run too. When a buyer approves an order and the supplier then
short-ships it, a new `AUTO-xxx` supplier-shortfall case opens for the agent.

Every tool call, result, model message and verification attempt is stored in `run_steps` and
shown live in the UI, so each decision can be traced.

---

## Evaluation

`backend/evals/expected.json` holds the expected outcome for each case, with a sentence on why.
`python -m evals.run_evals` resets the database for each case, runs the agent, and grades the run
against the questions in the brief:

| Check | Question from the brief | How it is graded |
|---|---|---|
| `decision` | Was the decision correct? | Decision is in the accepted set for the case |
| `quantity` | Was the amount right? | Total ordered falls within a range that allows reasonable demand estimates |
| `information` | Did it obtain the necessary information? | Inventory, demand, open POs, suppliers and budget were all read before the first action |
| `constraints` | Did it respect constraints? | Final budget ≥ 0 and peak stock ≤ storage |
| `action` | Did it take the appropriate action? | Ordered or did not order as expected; escalated when required; right supplier; plausible demand figure |
| `validated` | Did it validate the result? | `verify_outcome` passed |
| `recovery` | What happens when the first action fails? | Shortfall cases: no unresolved partial confirmations and no stockout |

Expected outcomes are ranges, not exact numbers, because more than one answer can be right. An
agent planning at 72/day instead of 71.4/day should not fail. Some cases accept more than one
decision: REC-102 can be `accept` or a small `modify`, for example. The report is written to
`backend/evals/results/latest.json` and shown in the **Evaluation** tab.

### Results

| Agent | Cases fully passed | Notes |
|---|---|---|
| Rule agent | **10 / 10** | All checks pass on every case |
| LLM agent, `anthropic/claude-sonnet-5.5` via OpenRouter | REC-101 checked through the API | Called all 6 read tools, then `calculate_need`, `project_stock` and `check_order`, ordered 168 units, and passed verification on the first submission |
| LLM agent, `nvidia/nemotron-3-ultra-550b-a55b:free` via OpenRouter | SHORT-201 | Accepted 250 of 500, ordered 250 from Golden Harvest, got 100, accepted it, ordered the last 150 from Metro Mayoreo (queued for approval, 15% premium). Verification passed on the first submission. |

Run `python -m evals.run_evals --mode llm` with credit on your key to score the LLM on all 10
cases.

The SHORT-201 run exposed a grader weakness. The agent reported `quantity: 400` because it counted
the 250 units already on PO-2001, but it only ordered 250 new units. The grader now counts units
actually ordered from the run trace (`units_ordered` in `run_evals.py`) and shows the agent's
reported number next to it. Like `verify_outcome`, the evaluation checks what happened, not what
the agent says happened.

### Unit tests

`pytest` (12 tests, no network) covers:

- demand shift detection, bulk-order filtering and broken-data flags;
- projection stockout day;
- validation rules (budget, storage, MOQ, case pack, max feasible quantity) and the approval policy;
- a supplier short-shipping and verification catching the unresolved partial;
- an approved order that comes back short and opens a follow-up case;
- all 10 scenarios passing the eval grader with the rule agent;
- the API end to end.

---

## API reference

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, active agent mode, provider and model |
| GET | `/api/cases` | All cases |
| GET | `/api/cases/{id}` | Case with stock, demand signals, open POs, suppliers and requirement |
| POST | `/api/cases/{id}/run?mode=auto\|llm\|rules&wait=false` | Start a run (returns `run_id`); `wait=true` runs synchronously |
| GET | `/api/runs?case_id=` | Runs, newest first |
| GET | `/api/runs/{id}` | Run with decision, verification, step trace, orders and approvals |
| GET | `/api/orders` | All purchase orders |
| GET | `/api/approvals?status=` | Approval queue |
| POST | `/api/approvals/{id}/decide` | Body `{"approve": true, "note": ""}`; approving an order sends it to the supplier |
| GET | `/api/policy` | Active purchasing policy |
| GET | `/api/evals/latest` | Latest eval report |
| POST | `/api/reset` | Reset the database to the seeded scenarios |

Example:

```bash
curl -X POST "http://localhost:8000/api/cases/REC-101/run?mode=rules&wait=true"
```

---

## Mock data

Everything is in `backend/mock_data/scenarios.json` and loaded into SQLite on start or reset:

- **3 fulfilment nodes:** Bogota, Mexico City and Sao Paulo, each with a 7-day review period.
- **16 suppliers**, each with on-time rate and fill rate.
- **Per scenario:**
  - product master (category, shelf life, safety days, primary supplier);
  - supplier terms (cost, MOQ, case pack, lead time), plus hidden real stock that only the mock
    supplier uses;
  - inventory (on hand, reserved, last count date) and the forecast;
  - 28 days of sales (units and order count per day);
  - category budget and storage zone;
  - open POs and the case itself.

Each case uses its own SKU and node/category budget, so cases do not interfere with each other.
Dates are relative to `SIMULATION_DATE`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `402 ... requires more credits, or fewer max_tokens` | The OpenRouter key has little or no credit. Add credit, lower `AGENT_MAX_TOKENS`, or use a `:free` model. |
| `429` / rate limit on a `:free` model | Free models allow only a small number of requests per day. Wait, add credit, or switch model. |
| `LLM mode needs an API key` | Set the key for the provider named in `LLM_PROVIDER`, then restart the backend. |
| Health shows `"agent_mode": "rules"` | No key for the selected provider was found in `.env`. |
| A run ends as `needs_review` | The agent could not satisfy verification. The issues are in the run's verification card and in the escalation in **Approvals**. |
| UI shows network errors | The backend is not running on port 8000. |
| Data looks odd after many runs | Click **Reset demo data**, or `POST /api/reset`. |

---

## Limitations and next steps

- Each SKU sits at one node in the mock data. Transfers between nodes would be a natural next tool.
- Lead times are fixed. Supplier on-time rates are shown to the agent but not yet used to pad lead
  times.
- Demand estimation is simple on purpose: median baseline, 7-day shift test and outlier filter.
  Seasonality and promotions are not modelled.
- Other buyer problems this architecture could take on, as new case types and a few new tools:
  - supplier reliability scoring from PO history;
  - safety-stock tuning;
  - promotional buying;
  - a daily sweep over all open POs.
