"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

export default function TasksPage() {
  const { data, error, isLoading } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });

  if (isLoading) return <p>Loading tasks...</p>;
  if (error) return <p>Failed to load tasks</p>;

  const tasks = data ?? [];

  return (
    <div>
      <h1>Task Feed ({tasks.length})</h1>
      {tasks.length === 0 ? (
        <p>No tasks published yet. Submit one from the home page.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "white" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #333", textAlign: "left" }}>
              <th style={{ padding: "8px" }}>ID</th>
              <th style={{ padding: "8px" }}>Objective</th>
              <th style={{ padding: "8px" }}>Priority</th>
              <th style={{ padding: "8px" }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((t, i) => (
              <tr key={t.id || i} style={{ borderBottom: "1px solid #ddd" }}>
                <td style={{ padding: "8px", fontFamily: "monospace", fontSize: "12px" }}>{(t.id || "").slice(0, 8)}</td>
                <td style={{ padding: "8px" }}>{t.objective}</td>
                <td style={{ padding: "8px" }}>{t.priority_score ?? "-"}</td>
                <td style={{ padding: "8px" }}>{t.status ?? "unknown"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
