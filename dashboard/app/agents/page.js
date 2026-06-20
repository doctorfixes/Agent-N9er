"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

export default function AgentsPage() {
  const { data, error, isLoading } = useSWR("/api/agents", fetcher, { refreshInterval: 5000 });

  if (isLoading) return <p>Loading agents...</p>;
  if (error) return <p>Failed to load agents</p>;

  const agents = data ?? {};
  const entries = Object.entries(agents);

  return (
    <div>
      <h1>Agent Reputation Ledger ({entries.length})</h1>
      {entries.length === 0 ? (
        <p>No agents registered yet. Run a simulation or execute tasks to populate.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "white" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #333", textAlign: "left" }}>
              <th style={{ padding: "8px" }}>Agent ID</th>
              <th style={{ padding: "8px" }}>Wins</th>
              <th style={{ padding: "8px" }}>Losses</th>
              <th style={{ padding: "8px" }}>Score</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(([id, stats]) => (
              <tr key={id} style={{ borderBottom: "1px solid #ddd" }}>
                <td style={{ padding: "8px", fontFamily: "monospace", fontSize: "12px" }}>{id.slice(0, 8)}</td>
                <td style={{ padding: "8px" }}>{stats.success}</td>
                <td style={{ padding: "8px" }}>{stats.fail}</td>
                <td style={{ padding: "8px" }}>{stats.score ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
