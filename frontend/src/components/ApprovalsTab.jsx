import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";
import JsonBlock from "./JsonBlock.jsx";

export default function ApprovalsTab({ onError }) {
  const [approvals, setApprovals] = useState([]);
  const [notes, setNotes] = useState({});
  const [lastResult, setLastResult] = useState(null);

  function loadApprovals() {
    api.listApprovals().then(setApprovals).catch((err) => onError(err.message));
  }

  useEffect(loadApprovals, []);

  async function decide(approval, approve) {
    try {
      const result = await api.decideApproval(approval.approval_id, approve, notes[approval.approval_id] || "");
      setLastResult(result);
      loadApprovals();
    } catch (err) {
      onError(err.message);
    }
  }

  const pending = approvals.filter((approval) => approval.status === "pending");
  const decided = approvals.filter((approval) => approval.status !== "pending");

  return (
    <div>
      {lastResult && <DecisionResult result={lastResult} onClose={() => setLastResult(null)} />}

      <div className="card">
        <h2>Pending ({pending.length})</h2>
        {pending.length === 0 && <p className="muted">Nothing waiting for a decision.</p>}
        {pending.map((approval) => {
          const isEscalation = approval.kind === "escalation";
          return (
            <div key={approval.approval_id} className="approval">
              <ApprovalSummary approval={approval} />
              <div className="approval-actions">
                <input
                  placeholder="Note (optional)"
                  value={notes[approval.approval_id] || ""}
                  onChange={(event) => setNotes({ ...notes, [approval.approval_id]: event.target.value })}
                />
                <button className="primary" onClick={() => decide(approval, true)}>
                  {isEscalation ? "Acknowledge" : "Approve"}
                </button>
                <button onClick={() => decide(approval, false)}>{isEscalation ? "Dismiss" : "Reject"}</button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="card">
        <h2>Decided ({decided.length})</h2>
        {decided.length === 0 && <p className="muted">No decisions yet.</p>}
        {decided.map((approval) => (
          <div key={approval.approval_id} className="approval">
            <ApprovalSummary approval={approval} />
            {approval.note && <p className="muted">Note: {approval.note}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

export function ApprovalSummary({ approval }) {
  return (
    <div>
      <div className="row">
        <Badge value={approval.kind} />
        <Badge value={approval.status} />
        <strong>{approval.title}</strong>
      </div>
      <p className="muted small">
        {approval.approval_id} · case {approval.case_id}
        {approval.po_id && ` · ${approval.po_id}`} · run {approval.run_id}
      </p>
      {typeof approval.details === "string" ? <p>{approval.details}</p> : <JsonBlock label="Details" value={approval.details} />}
    </div>
  );
}

function DecisionResult({ result, onClose }) {
  const supplier = result.supplier_response;
  return (
    <div className="card notice">
      <div className="row spread">
        <strong>Decision recorded: {result.approval?.title}</strong>
        <button onClick={onClose}>Close</button>
      </div>
      {supplier && (
        <p>
          Supplier response for {supplier.po_id}: {supplier.message} (requested {supplier.requested_qty}, confirmed{" "}
          {supplier.confirmed_qty}, status {supplier.status})
        </p>
      )}
      {result.follow_up_case && <p>A new case was opened: {result.follow_up_case}. See the Cases tab.</p>}
    </div>
  );
}
