import JsonBlock from "./JsonBlock.jsx";

export default function StepTimeline({ steps }) {
  if (steps.length === 0) return <p className="muted">No steps yet.</p>;

  const rows = [];
  for (let index = 0; index < steps.length; index++) {
    const step = steps[index];
    const next = steps[index + 1];
    if (step.kind === "tool_call") {
      const hasResult = next && (next.kind === "tool_result" || next.kind === "tool_error");
      rows.push(<ToolStep key={step.id} call={step} result={hasResult ? next : null} />);
      if (hasResult) index++;
    } else {
      rows.push(<Step key={step.id} step={step} />);
    }
  }
  return <ol className="timeline">{rows}</ol>;
}

function ToolStep({ call, result }) {
  const failed = result?.kind === "tool_error";
  return (
    <li className={failed ? "step step-error" : "step"}>
      <span className="step-kind">tool</span>
      <strong>{call.name}</strong>
      <code className="args">{formatArgs(call.payload)}</code>
      {result ? <JsonBlock label={failed ? "Error" : "Result"} value={result.payload} /> : <p className="muted">waiting...</p>}
    </li>
  );
}

function Step({ step }) {
  const payload = step.payload || {};

  if (step.kind === "thinking" || step.kind === "message") {
    return (
      <li className={`step step-${step.kind}`}>
        <span className="step-kind">{step.kind}</span>
        <p className="step-text">{payload.text}</p>
      </li>
    );
  }

  if (step.kind === "verification") {
    return (
      <li className={payload.passed ? "step step-passed" : "step step-failed"}>
        <span className="step-kind">verification</span>
        <strong>{step.name}</strong> {payload.passed ? "passed" : "failed"}
        <ul>
          {(payload.issues || []).map((issue, index) => (
            <li key={index}>{issue.message}</li>
          ))}
        </ul>
        <JsonBlock label="Details" value={payload} />
      </li>
    );
  }

  return (
    <li className={step.kind === "tool_error" ? "step step-error" : "step"}>
      <span className="step-kind">{step.kind.replace("_", " ")}</span>
      <strong>{step.name}</strong>
      <JsonBlock label="Details" value={step.payload} />
    </li>
  );
}

function formatArgs(args) {
  if (!args || typeof args !== "object") return String(args ?? "");
  return Object.entries(args)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
}
