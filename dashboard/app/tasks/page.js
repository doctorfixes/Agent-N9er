"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return null; } }).catch(() => null);

export default function TasksPage() {
  const [filter, setFilter] = useState("");
  const { data: tasks } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });

  const taskList = Array.isArray(tasks) ? tasks : [];
  const filtered = filter ? taskList.filter((t) => t.status === filter) : taskList;
  const filters = ["", "open", "awarded", "completed", "failed"];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Task History
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
          {taskList.length} TOTAL // {taskList.filter((t) => t.status === "completed").length} COMPLETED // {taskList.filter((t) => t.status === "failed").length} FAILED
        </div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {filters.map((f) => (
          <button key={f || "all"} onClick={() => setFilter(f)} className={`cmd-btn sm ${filter === f ? "active" : ""}`}>
            {f || "All"}
          </button>
        ))}
      </div>

      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th>Task ID</th>
              <th>Objective</th>
              <th>Priority</th>
              <th>Status</th>
              <th>Agent</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length > 0 ? filtered.map((t) => (
              <tr key={t.id}>
                <td style={{ color: "var(--accent-cyan)" }}>{t.id?.substring(0, 12)}</td>
                <td style={{ maxWidth: 350, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-primary)" }}>{t.objective}</td>
                <td>{t.priority_score?.toFixed(2)}</td>
                <td><span className={`badge ${t.status}`}>{t.status}</span></td>
                <td style={{ color: "var(--text-muted)", fontSize: 10 }}>{t.awarded_to?.substring(0, 12) || "---"}</td>
              </tr>
            )) : (
              <tr>
                <td colSpan={5} style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  {taskList.length === 0 ? "No tasks in system." : "No tasks matching filter."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
