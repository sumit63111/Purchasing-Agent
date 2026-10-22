# Architecture

```mermaid
flowchart LR
    UI[React UI<br/>cases, live trace,<br/>approvals, evals] -->|REST| API[FastAPI<br/>app/main.py]
    API --> RUN[Runner<br/>agent/runner.py]
    RUN --> LLM[LLM agent<br/>OpenRouter or Gemini]
    RUN --> RULES[Rule agent<br/>agent/rule_agent.py]
    LLM --> TOOLS[Tools<br/>agent/tools.py]
    RULES --> TOOLS
    TOOLS --> PLAN[planning.py<br/>demand, projection, need]
    TOOLS --> CHECKS[checks.py<br/>validate_order<br/>verify_outcome]
    TOOLS --> ORDERS[orders.py<br/>POs, approvals]
    ORDERS --> SUP[Mock supplier<br/>confirms real stock]
    PLAN --> DB[(SQLite<br/>mock ERP)]
    ORDERS --> DB
    CHECKS --> DB
    API --> APPROVALS[Approval queue] --> ORDERS
```

## Feedback loop

```mermaid
sequenceDiagram
    participant A as Agent
    participant V as check_order
    participant S as Supplier (mock)
    participant O as verify_outcome
    participant H as Buyer

    A->>V: check_order(supplier, qty)
    V-->>A: errors / warnings / max_feasible_qty
    A->>S: create_purchase_order
    alt needs approval
        S-->>H: queued in approval queue
        H->>S: approve
        S-->>H: confirmation (may be partial -> new AUTO case)
    else auto
        S-->>A: confirmed / partially confirmed / rejected
    end
    A->>A: partial? accept it and source the rest
    A->>O: submit_decision
    O-->>A: issues (coverage, budget, storage, unresolved partials, decision mismatch)
    A->>A: fix and resubmit (max 3)
    O-->>H: still failing -> run marked needs_review + escalation
```

## Layers

| Layer | File | Job |
|---|---|---|
| API | `app/main.py` | REST routes for the UI |
| Runner | `app/agent/runner.py` | Starts a run, stores the trace, closes it out |
| Agents | `app/agent/llm_agent.py`, `rule_agent.py` | LLM tool-use loop (OpenRouter / Gemini) / fixed playbook |
| Tools | `app/agent/tools.py` | 15 tools, the only way the agent touches data |
| Maths | `app/planning.py` | Demand estimate, stock projection, requirement |
| Guardrails | `app/checks.py` | Pre-action validation and post-action verification |
| Actions | `app/orders.py` | POs, budget, supplier replies, approval queue |
| Data | `app/db.py`, `mock_data/scenarios.json` | SQLite mock ERP seeded from JSON |
