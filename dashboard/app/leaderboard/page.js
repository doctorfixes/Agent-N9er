"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

function Medal({ rank }) {
  if (rank === 1) return <span style={{ fontSize: "16px" }}>1st</span>;
  if (rank === 2) return <span style={{ fontSize: "14px" }}>2nd</span>;
  if (rank === 3) return <span style={{ fontSize: "14px" }}>3rd</span>;
  return <span style={{ color: "#6b7280" }}>{rank}</span>;
}

export default function LeaderboardPage() {
  const { data, error, isLoading } = useSWR("/api/agents", fetcher, { refreshInterval: 10000 });

  if (isLoading) return <p style={{ color: "#6b7280" }}>Loading leaderboard...</p>;
  if (error) return <p style={{ color: "#ef4444" }}>Failed to load leaderboard</p>;

  const agents = data ?? {};
  const entries = Object.entries(agents)
    .map(([id, stats]) => ({ id, ...stats, total: (stats.success || 0) + (stats.fail || 0) }))
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

  const topScore = entries[0]?.score ?? 0;

  return (
    <div>
      <div style={{ marginBottom: "20px" }}>
        <h1 style={{ margin: "0 0 4px 0", fontSize: "1.5em" }}>Agent Leaderboard</h1>
        <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
          {entries.length} agent{entries.length !== 1 ? "s" : ""} ranked by reputation score
        </p>
      </div>

      {entries.length === 0 ? (
        <div style={{ background: "white", padding: "40px", borderRadius: "8px", border: "1px solid #e5e7eb", textAlign: "center" }}>
          <p style={{ color: "#9ca3af", fontSize: "15px" }}>No agents registered yet. Dispatch tasks from Mission Control to populate the leaderboard.</p>
        </div>
      ) : (
        <div style={{ background: "white", borderRadius: "8px", border: "1px solid #e5e7eb", overflow: "hidden" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "14px" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #e5e7eb", textAlign: "left", background: "#f9fafb" }}>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "60px" }}>Rank</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151" }}>Agent</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "80px" }}>Wins</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "80px" }}>Losses</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "80px" }}>Total</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "100px" }}>Score</th>
                <th style={{ padding: "10px 14px", fontWeight: 600, color: "#374151", width: "120px" }}>Win Rate</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((agent, i) => {
                const winRate = agent.total > 0 ? ((agent.success || 0) / agent.total * 100).toFixed(1) : "0.0";
                const barWidth = topScore > 0 ? ((agent.score ?? 0) / topScore * 100) : 0;
                return (
                  <tr key={agent.id} style={{ borderBottom: "1px solid #f3f4f6", background: i < 3 ? "#fefce8" : "transparent" }}>
                    <td style={{ padding: "10px 14px", textAlign: "center" }}><Medal rank={i + 1} /></td>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "12px" }}>{agent.id.slice(0, 12)}</td>
                    <td style={{ padding: "10px 14px", color: "#16a34a", fontWeight: 600 }}>{agent.success || 0}</td>
                    <td style={{ padding: "10px 14px", color: "#dc2626" }}>{agent.fail || 0}</td>
                    <td style={{ padding: "10px 14px" }}>{agent.total}</td>
                    <td style={{ padding: "10px 14px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <div style={{ flex: 1, height: "6px", background: "#f3f4f6", borderRadius: "3px", overflow: "hidden" }}>
                          <div style={{ width: `${barWidth}%`, height: "100%", background: "#2563eb", borderRadius: "3px" }} />
                        </div>
                        <span style={{ fontWeight: 600, minWidth: "30px", textAlign: "right" }}>{agent.score ?? 0}</span>
                      </div>
                    </td>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "12px" }}>{winRate}%</td>
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
