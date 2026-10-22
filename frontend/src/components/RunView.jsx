import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";
import StepTimeline from "./StepTimeline.jsx";
import { OrdersTable } from "./OrdersTab.jsx";
import { ApprovalSummary } from "./ApprovalsTab.jsx";

export default function RunView({ runId, onError, onFinished }) {
  const [run, setRun] = useState(null);

  useEffect(() => {
    let stopped = false;
    let timer = null;

    async function poll() {
      try {
        const data = await api.getRun(runId);
        if (stopped) return;
        setRun(data);
        if (data.status === "running") {
          timer = setTimeout(poll, 1000);
        } else {
          onFinished();
        }
      } catch (err) {
        if (!stopped) onError(err.message);
      }
    }

    poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId]);

  if (!run) return <div className="card muted">Loading run...</div>;

  const decision = run.decision_detail;
  const verification = run.verification;

  return (
    <div>
      <div className="card">
        <div className="row">
          <h2>Run {run.run_id}</h2>
          <Badge value={run.status} />
          <span className="muted">mode {run.mode}</span>
        </div>
        <p className="muted small">
          Started {run.started_at}
          {run.finished_at && ` · finished ${run.finished_at}`}
        </p>
        {run.error && <p className="text-error">{run.error}</p>}
      </div>

      <div className="two-columns">
        <div className="card">
          <h3>Decision</h3>
          {decision ? (
            <>
              <div className="row">
                <Badge value={decision.decision} />
                <span>Quantity: <strong>{decision.quantity ?? "-"}</strong></span>
                <span>Daily demand used: <strong>{decision.daily_demand_used ?? "-"}</strong></span>
              </div>
              <p>{decision.summary}</p>
              <TextList title="Key factors" items={decision.key_factors} />
              <TextList title="Risks" items={decision.risks} />
            </>
          ) : (
            <p className="muted">{run.status === "running" ? "Waiting for the agent..." : "No decision submitted."}</p>
          )}
        </div>

        <div className={verification ? (verification.passed ? "card verified" : "card unverified") : "card"}>
          <h3>Verification</h3>
          {verification ? (
            <>
              <p>
                Passed: <strong>{verification.passed ? "yes" : "no"}</strong>
              </p>
              <TextList title="Issues" items={(verification.issues || []).map((issue) => `${issue.code}: ${issue.message}`)} />
              <TextList title="Warnings" items={verification.warnings} />
              <p className="muted small">
                Checked demand {verification.checked_daily_demand}/day · stockout day {verification.stockout_day ?? "none"} ·
                budget left {verification.budget_left} · peak stock {verification.peak_stock} of {verification.storage_space}
              </p>
            </>
          ) : (
            <p className="muted">Not verified yet.</p>
          )}
        </div>
      </div>

      {run.orders.length > 0 && (
        <div className="card">
          <h3>Orders created</h3>
          <div className="table-wrap">
            <OrdersTable orders={run.orders} />
          </div>
        </div>
      )}

      {run.approvals.length > 0 && (
        <div className="card">
          <h3>Approvals raised</h3>
          {run.approvals.map((approval) => (
            <div key={approval.approval_id} className="approval">
              <ApprovalSummary approval={approval} />
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h3>Trace</h3>
        <StepTimeline steps={run.steps} />
        {run.status === "running" && <p className="muted">Agent is working...</p>}
      </div>
    </div>
  );
}

function TextList({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <strong>{title}</strong>
      <ul>
        {items.map((text, index) => (
          <li key={index}>{text}</li>
        ))}
      </ul>
    </div>
  );
}
