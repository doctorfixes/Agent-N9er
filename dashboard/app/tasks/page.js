"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

const STATUS_COLORS = {
  completed: { bg: "#dcfce7", fg: "#166534" },
  failed: { bg: "#fee2e2", fg: "#991b1b" },
  awarded: { bg: "#dbeafe", fg: "#1e40af" },
  open: { bg: "#f3f4f6", fg: "#374151" },
};

export default function TaskHistoryPage() {
  const [filter, setFilter] = useState("all");
  const { data, error, isLoading } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });

  if (isLoading) return <p style={{ color: "#6b7280" }}>Loading task history...</p>;
  if (error) return <p style={{ color: "#ef4444" }}>Failed to load tasks</p>;

  const tasks = data ?? [];
  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);

  const counts = {
    all: tasks.length,
    open: tasks.filter((t) => t.status === "open").length,
    awarded: tasks.filter((t) => t.status === "awarded").length,
    completed: tasks.filter((t) => t.status === "completed").length,
    failed: tasks.filter((t) => t.status === "failed").length,
  };

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h1 style={{ margin: "0 0 4px 0", fontSize: "1.5em" }}>Task History</h1>
        <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
          Full audit trail of all dispatched tasks
        </p>
      </div>

      <div style={{ display: "flex", gap: "6px", marginBottom: "16px" }}>
        {Object.entries(counts).map(([key, count]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            style={{
              padding: "6px 14px",
              fontSize: "13px",
              fontWeight: filter === key ? 600 : 400,
              border: "1px solid",
              borderColor: filter === key ? "#2563eb" : "#d1d5db",
              borderRadius: "6px",
              background: filter === key ? "#eff6ff" : "white",
              color: filter === key ? "#2563eb" : "#374151",
              cursor: "pointer",
            }}
          >
            {key.charAt(0).toUpperCase() + key.slice(1)} ({count})
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div style={{ background: "white", padding: "40px", borderRadius: "8px", border: "1px solid #e5e7eb", textAlign: "center" }}>
          <p style={{ color: "#9ca3af", fontSize: "15px" }}>
            {tasks.length === 0 ? "No tasks dispatched yet. Head to Mission Control to get started." : `No ${filter} tasks found.`}
          </p>
        </div>
      ) : (
        <div style={{ background: "white", borderRadius: "8px", border: "1px solid #e5e7eb", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left", background: "#f9fafb" }}>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "100px" }}>Task ID</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151" }}>Objective</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "80px" }}>Priority</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "100px" }}>Status</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "100px" }}>Agent</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t, i) => {
                const colors = STATUS_COLORS[t.status] || STATUS_COLORS.open;
                return (
                  <tr key={t.id || i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "12px", color: "#6b7280" }}>{(t.id || "").slice(0, 10)}</td>
                    <td style={{ padding: "10px 14px" }}>{t.objective || "-"}</td>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace" }}>{t.priority_score ?? "-"}</td>
                    <td style={{ padding: "10px 14px" }}>
                      <span style={{ padding: "3px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: 600, background: colors.bg, color: colors.fg }}>
                        {t.status || "open"}
                      </span>
                    </td>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "12px", color: "#6b7280" }}>
                      {t.awarded_to ? t.awarded_to.slice(0, 8) : "-"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
