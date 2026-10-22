import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";
import RunView from "./RunView.jsx";
import SalesChart from "./SalesChart.jsx";
import Table from "./Table.jsx";
import { Stat } from "./EvalTab.jsx";

const OPEN_ORDER_COLUMNS = [
  ["PO", (order) => order.po_id],
  ["Supplier", (order) => order.supplier_id],
  ["Qty", (order) => order.quantity],
  ["Confirmed", (order) => order.confirmed_qty ?? "-"],
  ["Incoming", (order) => order.incoming_qty],
  ["Status", (order) => <Badge value={order.status} />],
  ["Expected day", (order) => order.expected_day],
  ["Arrives in", (order) => `${order.arrives_in_days} days`],
];

const SUPPLIER_COLUMNS = [
  ["Supplier", (supplier) => (supplier.is_primary ? `${supplier.supplier_name} (primary)` : supplier.supplier_name)],
  ["Unit cost", (supplier) => supplier.unit_cost],
  ["MOQ", (supplier) => supplier.moq],
  ["Case pack", (supplier) => supplier.case_pack],
  ["Lead days", (supplier) => supplier.lead_days],
  ["Fill rate", (supplier) => percent(supplier.fill_rate)],
  ["On time", (supplier) => percent(supplier.on_time_rate)],
  ["Premium", (supplier) => `${supplier.price_premium_pct}%`],
];

export default function CaseDetail({ caseId, mode, onError, onCaseChanged }) {
  const [detail, setDetail] = useState(null);
  const [runs, setRuns] = useState([]);
  const [openRunId, setOpenRunId] = useState(null);
  const [starting, setStarting] = useState(false);

  function loadDetail() {
    api.getCase(caseId).then(setDetail).catch((err) => onError(err.message));
  }

  function loadRuns() {
    api.listRuns(caseId).then(setRuns).catch((err) => onError(err.message));
  }

  useEffect(() => {
    loadDetail();
    loadRuns();
  }, [caseId]);

  async function runAgent() {
    setStarting(true);
    try {
      const { run_id } = await api.runCase(caseId, mode);
      setOpenRunId(run_id);
      loadRuns();
    } catch (err) {
      onError(err.message);
    }
    setStarting(false);
  }

  function handleRunFinished() {
    loadRuns();
    loadDetail();
    onCaseChanged();
  }

  if (!detail) return <div className="card muted">Loading...</div>;

  const { case: caseInfo, item, demand, open_orders: openOrders, suppliers, requirement } = detail;
  const storageSpace = item.storage_capacity - item.storage_other_units;
  const isRunning = runs.some((run) => run.status === "running");

  return (
    <div>
      <div className="card">
        <div className="row spread">
          <div>
            <h2>{caseInfo.title}</h2>
            <div className="row">
              <Badge value={caseInfo.case_type} />
              <Badge value={caseInfo.status} />
              <span className="muted small">
                {caseInfo.case_id} · {caseInfo.product_name} ({caseInfo.sku}) · node {caseInfo.node_id}
                {caseInfo.ref_po_id && ` · ref ${caseInfo.ref_po_id}`}
              </span>
            </div>
          </div>
          <button className="primary" onClick={runAgent} disabled={starting || isRunning}>
            {isRunning ? "Running..." : `Run agent (${mode})`}
          </button>
        </div>
        <p>{caseInfo.description}</p>

        <div className="stats">
          <Stat label="On hand" value={item.on_hand} />
          <Stat label="Reserved" value={item.reserved} />
          <Stat label="Forecast / day" value={demand.forecast_daily} />
          <Stat label="Reference / day" value={demand.reference_daily_demand} />
          <Stat label="On order" value={requirement.on_order} />
          <Stat label="Budget left" value={item.budget_limit - item.budget_used} />
          <Stat label="Storage free" value={`${storageSpace - item.on_hand} / ${storageSpace}`} />
          <Stat label="Net requirement" value={requirement.net_requirement} />
        </div>
        <p className="muted small">Reference demand basis: {demand.reference_basis}</p>

        {demand.flags.length > 0 && (
          <div className="flags">
            <strong>Demand flags</strong>
            <ul>
              {demand.flags.map((flag) => (
                <li key={flag}>{flag}</li>
              ))}
            </ul>
          </div>
        )}

        <h3>Daily sales, last 28 days</h3>
        <SalesChart units={demand.daily_units_28d} forecast={demand.forecast_daily} />

        {caseInfo.recommended_qty != null && (
          <p>
            <strong>Recommendation:</strong> order {caseInfo.recommended_qty} units
            {caseInfo.recommended_supplier_id && ` from ${caseInfo.recommended_supplier_id}`}
          </p>
        )}
      </div>

      <div className="card">
        <h3>Open purchase orders</h3>
        <Table columns={OPEN_ORDER_COLUMNS} rows={openOrders} rowKey="po_id" />

        <h3>Supplier options</h3>
        <Table columns={SUPPLIER_COLUMNS} rows={suppliers} rowKey="supplier_id" />
      </div>

      <div className="card">
        <h3>Runs</h3>
        {runs.length === 0 && <p className="muted">This case has not been run yet.</p>}
        {runs.map((run) => (
          <button
            key={run.run_id}
            className={run.run_id === openRunId ? "run-item active" : "run-item"}
            onClick={() => setOpenRunId(run.run_id)}
          >
            <Badge value={run.status} />
            <Badge value={run.decision} />
            <span>{run.mode}</span>
            <span className="muted small">{run.started_at}</span>
            <span className="run-summary">{run.summary}</span>
          </button>
        ))}
      </div>

      {openRunId && <RunView key={openRunId} runId={openRunId} onError={onError} onFinished={handleRunFinished} />}
    </div>
  );
}

function percent(value) {
  return value == null ? "-" : `${Math.round(value * 100)}%`;
}
