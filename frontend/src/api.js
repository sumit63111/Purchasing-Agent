async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `Request failed (${response.status})`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}

function post(path, body) {
  return request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

export const api = {
  listCases: () => request("/api/cases"),
  getCase: (caseId) => request(`/api/cases/${caseId}`),
  runCase: (caseId, mode) => post(`/api/cases/${caseId}/run?mode=${mode}`),
  listRuns: (caseId) => request(`/api/runs?case_id=${encodeURIComponent(caseId)}`),
  getRun: (runId) => request(`/api/runs/${runId}`),
  listOrders: () => request("/api/orders"),
  listApprovals: () => request("/api/approvals"),
  decideApproval: (approvalId, approve, note) => post(`/api/approvals/${approvalId}/decide`, { approve, note }),
  getLatestEval: () => request("/api/evals/latest"),
  resetDemo: () => post("/api/reset"),
};
