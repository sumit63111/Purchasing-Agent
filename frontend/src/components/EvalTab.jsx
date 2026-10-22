import { useEffect, useState } from "react";
import { api } from "../api.js";
import Badge from "./Badge.jsx";

export default function EvalTab({ onError }) {
  const [report, setReport] = useState(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    api
      .getLatestEval()
      .then(setReport)
      .catch((err) => (err.status === 404 ? setMissing(true) : onError(err.message)));
  }, []);

  if (missing) {
    return (
      <div className="card">
        <p>
          No evaluation report yet. Run <code>python -m evals.run_evals</code> in <code>backend/</code> to generate a report.
        </p>
      </div>
    );
  }
  if (!report) return <p className="muted">Loading...</p>;

  const checkNames = [...new Set(report.results.flatMap((result) => result.checks.map((check) => check.name)))];

  return (
    <div className="card">
      <h2>Latest evaluation</h2>
      <div className="stats">
        <Stat label="Cases" value={report.summary.cases} />
        <Stat label="Passed" value={report.summary.passed} />
        <Stat label="Score" value={report.summary.score} />
        <Stat label="Mode" value={report.mode} />
        <Stat label="Generated" value={report.generated_at} />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Expected</th>
              <th>Actual</th>
              <th>Score</th>
              {checkNames.map((name) => (
                <th key={name}>{name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {report.results.map((result) => (
              <tr key={result.case_id} className={result.passed ? "" : "row-failed"}>
                <td title={result.title}>{result.case_id}</td>
                <td>{result.expected_decision.join(" / ")}</td>
                <td><Badge value={result.decision} /></td>
                <td>{result.score}</td>
                {checkNames.map((name) => {
                  const check = result.checks.find((item) => item.name === name);
                  if (!check) return <td key={name}>-</td>;
                  return (
                    <td key={name} title={check.detail} className={check.passed ? "pass" : "fail"}>
                      {check.passed ? "pass" : "fail"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">Hover a check cell to see its details.</p>
    </div>
  );
}

export function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value ?? "-"}</div>
    </div>
  );
}
