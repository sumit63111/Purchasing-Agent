import { useState } from "react";
import { api } from "./api.js";
import CasesTab from "./components/CasesTab.jsx";
import ApprovalsTab from "./components/ApprovalsTab.jsx";
import OrdersTab from "./components/OrdersTab.jsx";
import EvalTab from "./components/EvalTab.jsx";

const TABS = ["Cases", "Approvals", "Purchase Orders", "Evaluation"];
const MODES = ["auto", "llm", "rules"];

export default function App() {
  const [tab, setTab] = useState("Cases");
  const [mode, setMode] = useState("auto");
  const [error, setError] = useState("");
  const [resetCount, setResetCount] = useState(0);

  async function resetDemo() {
    if (!window.confirm("Reset all demo data? Runs, orders and approvals will be cleared.")) return;
    try {
      await api.resetDemo();
      setError("");
      setResetCount((count) => count + 1);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Purchasing Agent</h1>
        <div className="header-actions">
          <label>
            Mode{" "}
            <select value={mode} onChange={(event) => setMode(event.target.value)}>
              {MODES.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </label>
          <button onClick={resetDemo}>Reset demo data</button>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((name) => (
          <button key={name} className={name === tab ? "tab active" : "tab"} onClick={() => setTab(name)}>
            {name}
          </button>
        ))}
      </nav>

      {error && (
        <div className="error-banner">
          <span>{error}</span>
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}

      <main key={resetCount}>
        {tab === "Cases" && <CasesTab mode={mode} onError={setError} />}
        {tab === "Approvals" && <ApprovalsTab onError={setError} />}
        {tab === "Purchase Orders" && <OrdersTab onError={setError} />}
        {tab === "Evaluation" && <EvalTab onError={setError} />}
      </main>
    </div>
  );
}
