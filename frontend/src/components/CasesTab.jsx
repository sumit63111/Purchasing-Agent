import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";
import CaseDetail from "./CaseDetail.jsx";

export default function CasesTab({ mode, onError }) {
  const [cases, setCases] = useState([]);
  const [selectedCaseId, setSelectedCaseId] = useState(null);

  function loadCases() {
    api.listCases().then(setCases).catch((err) => onError(err.message));
  }

  useEffect(loadCases, []);

  return (
    <div className="cases-layout">
      <aside className="card case-list">
        <h2>Cases</h2>
        {cases.length === 0 && <p className="muted">No cases.</p>}
        {cases.map((item) => (
          <button
            key={item.case_id}
            className={item.case_id === selectedCaseId ? "case-item active" : "case-item"}
            onClick={() => setSelectedCaseId(item.case_id)}
          >
            <div className="case-title">{item.title}</div>
            <div className="row">
              <Badge value={item.case_type} />
              <Badge value={item.status} />
            </div>
          </button>
        ))}
      </aside>

      <section className="case-main">
        {selectedCaseId ? (
          <CaseDetail key={selectedCaseId} caseId={selectedCaseId} mode={mode} onError={onError} onCaseChanged={loadCases} />
        ) : (
          <div className="card muted empty-state">Select a case to see its details.</div>
        )}
      </section>
    </div>
  );
}
