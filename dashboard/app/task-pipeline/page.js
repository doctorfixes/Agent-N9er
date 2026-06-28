"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return null; } }).catch(() => null);

const STATUS_STYLES = {
  published:  { bg: "#1e3a5f", color: "#60a5fa" },
  executing:  { bg: "#1c2a1e", color: "#4ade80" },
  completed:  { bg: "#052e16", color: "#22c55e" },
  failed:     { bg: "#2d0a0a", color: "#f87171" },
  unknown:    { bg: "#1e1e30", color: "#64748b" },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] ?? STATUS_STYLES.unknown;
  return (
    <span style={{ background: s.bg, color: s.color, borderRadius: "4px", padding: "2px 8px", fontSize: "11px", fontWeight: 700 }}>
      {(status ?? "unknown").toUpperCase()}
    </span>
  );
}

export default function TaskPipelinePage() {
  const { data, error, isLoading, mutate } = useSWR("/api/tasks", fetcher, { refreshInterval: 4000 });
  const [objective, setObjective] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitResult, setSubmitResult] = useState(null);

  const tasks = Array.isArray(data) ? data : [];

  async function handleSubmit(e) {
    e.preventDefault();
    if (!objective.trim()) return;
    setSubmitting(true);
    setSubmitResult(null);
    try {
      const resp = await fetch("/api/pipeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      const result = await resp.text().then((t) => { try { return JSON.parse(t); } catch { return {}; } });
      setSubmitResult(result);
      setObjective("");
      mutate();
    } catch {
      setSubmitResult({ error: "Failed to submit task" });
    }
    setSubmitting(false);
  }

  const byStatus = tasks.reduce((acc, t) => {
    const s = t.status ?? "unknown";
    acc[s] = (acc[s] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <h1 style={{ color: "#e2e8f0", marginTop: 0, marginBottom: "4px" }}>Task Pipeline</h1>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "28px", fontSize: "14px" }}>
        Tasks flow from signal detection → normalization → ranking → marketplace → agent execution.
      </p>

      {/* Stage summary */}
      <div style={{ display: "flex", gap: "10px", marginBottom: "28px", flexWrap: "wrap" }}>
        {Object.entries(byStatus).map(([status, count]) => {
          const s = STATUS_STYLES[status] ?? STATUS_STYLES.unknown;
          return (
            <div key={status} style={{ background: s.bg, border: `1px solid ${s.color}44`, borderRadius: "6px", padding: "8px 16px", display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontWeight: 700, fontSize: "18px", color: s.color }}>{count}</span>
              <span style={{ fontSize: "12px", color: s.color, textTransform: "uppercase", letterSpacing: "0.06em" }}>{status}</span>
            </div>
          );
        })}
        {tasks.length === 0 && <span style={{ fontSize: "13px", color: "#64748b" }}>No tasks in pipeline yet.</span>}
      </div>

      {/* Submit form */}
      <div style={{ background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "20px", marginBottom: "28px" }}>
        <h2 style={{ color: "#cbd5e1", fontSize: "14px", fontWeight: 600, margin: "0 0 12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Inject Task
        </h2>
        <form onSubmit={handleSubmit} style={{ display: "flex", gap: "10px" }}>
          <input
            type="text"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Describe the task objective…"
            style={{ flex: 1, padding: "8px 12px", background: "#0d0d14", border: "1px solid #2d2d44", borderRadius: "6px", color: "#e2e8f0", fontSize: "14px", outline: "none" }}
          />
          <button
            type="submit"
            disabled={submitting}
            style={{ padding: "8px 20px", background: "#4f46e5", color: "white", border: "none", borderRadius: "6px", cursor: submitting ? "not-allowed" : "pointer", fontWeight: 600, fontSize: "14px" }}
          >
            {submitting ? "Submitting…" : "Submit"}
          </button>
        </form>
        {submitResult && (
          <pre style={{ marginTop: "12px", background: "#0d0d14", border: "1px solid #2d2d44", borderRadius: "6px", padding: "12px", overflow: "auto", maxHeight: "200px", fontSize: "12px", color: "#94a3b8" }}>
            {JSON.stringify(submitResult, null, 2)}
          </pre>
        )}
      </div>

      {/* Task table */}
      {error && <p style={{ color: "#ef4444", fontSize: "14px" }}>Failed to load tasks.</p>}
      {isLoading && <p style={{ color: "#64748b" }}>Loading tasks…</p>}
      {!isLoading && tasks.length === 0 && (
        <p style={{ color: "#64748b", fontSize: "14px" }}>No tasks published yet. Submit one above or trigger a connected integration.</p>
      )}
      {tasks.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "#1a1a2e", borderRadius: "8px", overflow: "hidden" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #2d2d44" }}>
              {["Task ID", "Objective", "Priority", "Category", "Status"].map((h) => (
                <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: "11px", color: "#64748b", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map((t, i) => (
              <tr key={t.id || i} style={{ borderBottom: "1px solid #1e1e30" }}>
                <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "11px", color: "#64748b" }}>{(t.id || "").slice(0, 8)}</td>
                <td style={{ padding: "10px 14px", fontSize: "13px", color: "#e2e8f0", maxWidth: "340px" }}>
                  <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.objective}</span>
                </td>
                <td style={{ padding: "10px 14px", fontSize: "13px", color: "#f59e0b", fontWeight: 600 }}>
                  {t.priority_score != null ? t.priority_score.toFixed(2) : "—"}
                </td>
                <td style={{ padding: "10px 14px", fontSize: "12px", color: "#94a3b8" }}>{t.category ?? "—"}</td>
                <td style={{ padding: "10px 14px" }}><StatusBadge status={t.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
