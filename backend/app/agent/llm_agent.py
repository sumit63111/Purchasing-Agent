import json

from openai import OpenAI

from app import config
from app.agent.tools import TOOL_DEFINITIONS, add_step, run_tool

SYSTEM_PROMPT = f"""You are a purchasing agent for a quick-commerce company. You work one case at a time
(one SKU at one fulfilment node) and act only through the tools. Reach a sound decision, carry it out,
and make sure the result is acceptable.

How to work a case
- Investigate first: inventory, demand, open orders, suppliers and budget. A system recommendation is a
  hypothesis to test, not an instruction.
- Choose the daily demand to plan with and say why. Watch for sustained shifts, one-off bulk orders,
  stale forecasts and data quality flags. If the data cannot be trusted, do not buy - escalate.
- Use calculate_need and project_stock for the numbers. If stock runs out before a new order can
  arrive, a faster supplier may be needed for the gap.
- Run check_order before ordering. If budget, storage, MOQ or shelf life blocks the ideal quantity,
  order the largest quantity that fits or use another supplier, and escalate what you cannot cover.
- Read every supplier reply. A partial confirmation means the gap is still open: accept the partial
  quantity, then source the rest elsewhere or escalate.
- Finish with submit_decision. It checks the state your actions produced. If it reports issues,
  fix them and submit again.

Decisions
- accept: the recommendation or current plan is right (you may still place the recommended order or
  accept a partial confirmation).
- modify: the plan needed changing (quantity, supplier, extra or bigger orders).
- reject: no purchase is needed.
- investigate: the data is not good enough to decide; escalate and do not buy.
- escalate: the decision is outside your authority.

Authority
- Orders above ${config.AUTO_APPROVE_LIMIT:,.0f}, or more than {config.MAX_PRICE_PREMIUM:.0%} pricier than the
  primary supplier, wait for human approval automatically. That is fine; do not avoid the right order
  because of it.
- You cannot cancel orders or raise budgets. Ask the buyer.

Keep the summary short, with the numbers that drove the decision."""


def case_prompt(case):
    lines = [f"Case {case['case_id']} ({case['case_type']}): {case['title']}", case["description"]]
    if case["recommended_qty"]:
        lines.append(f"System recommendation: {case['recommended_qty']} units from {case['recommended_supplier_id']}.")
    if case["ref_po_id"]:
        lines.append(f"Referenced purchase order: {case['ref_po_id']}.")
    lines.append(f"Today is {config.SIMULATION_DATE}.")
    return "\n".join(lines)


# ==========================================
# Agent loop (OpenAI-compatible API: OpenRouter or Gemini)
# ==========================================
def run_llm_agent(run):
    client = OpenAI(api_key=config.LLM["api_key"], base_url=config.LLM["base_url"])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": case_prompt(run["case"])},
    ]
    reminded = False

    for _ in range(config.MAX_TURNS):
        response = client.chat.completions.create(
            model=config.LLM["model"],
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            max_tokens=config.MAX_TOKENS,
        )
        message = response.choices[0].message

        # Keep the full message so provider extras (e.g. Gemini thought signatures) go back unchanged
        assistant = message.model_dump(exclude_none=True)
        assistant["content"] = message.content or ""
        messages.append(assistant)
        if message.content and message.content.strip():
            add_step(run["run_id"], "message", None, {"text": message.content})

        if not message.tool_calls:
            if reminded:
                raise RuntimeError("The agent stopped without submitting a decision.")
            reminded = True
            messages.append({"role": "user", "content": "Finish the case and call submit_decision."})
            continue

        for call in message.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                result = run_tool(run, call.function.name, args)
            except json.JSONDecodeError:
                result = {"error": f"Arguments for {call.function.name} were not valid JSON."}
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})

        if run["done"]:
            return

    raise RuntimeError(f"The agent did not finish within {config.MAX_TURNS} turns.")
