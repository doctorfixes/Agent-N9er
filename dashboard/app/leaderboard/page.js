"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json()).catch(() => null);

function ScoreBar({ score, max }) {
  const pct = max > 0 ? Math.min(100, (score / max) * 100) : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 80, height: 6, background: "var(--border)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 3,
          background: pct > 60 ? "var(--accent-green)" : pct > 30 ? "var(--accent-amber)" : "var(--accent-red)",
          boxShadow: pct > 60 ? "var(--glow-green)" : "none",
        }} />
      </div>
      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{score}</span>
    </div>
  );
}

const RANK_ICONS = { 1: "I", 2: "II", 3: "III" };

export default function LeaderboardPage() {
  const { data: agents } = useSWR("/api/agents", fetcher, { refreshInterval: 10000 });

  const sorted = agents
    ? Object.entries(agents)
        .map(([id, a]) => ({ id, ...a }))
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
    : [];

  const maxScore = sorted.length > 0 ? Math.max(...sorted.map((a) => a.score ?? 0)) : 1;

  return (
    <div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 16 }}>
        Agent Leaderboard
      </div>

      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 50 }}>Rank</th>
              <th>Agent</th>
              <th>Rating</th>
              <th style={{ textAlign: "right" }}>Jobs</th>
              <th style={{ textAlign: "right" }}>Wins</th>
              <th style={{ textAlign: "right" }}>Losses</th>
              <th>Score</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length > 0 ? sorted.map((agent, i) => {
              const rank = i + 1;
              const displayName = agent.nickname || agent.id?.substring(0, 14);
              const isTop3 = rank <= 3;

              return (
                <tr key={agent.id} style={isTop3 ? { background: "rgba(245,158,11,0.03)" } : undefined}>
                  <td style={{
                    fontFamily: "var(--font-mono)", fontWeight: 700, fontSize: 14, textAlign: "center",
                    color: rank === 1 ? "var(--accent-amber)" : rank === 2 ? "var(--text-secondary)" : rank === 3 ? "#cd7f32" : "var(--text-muted)",
                  }}>
                    {RANK_ICONS[rank] || rank}
                  </td>
                  <td>
                    <div style={{ color: "var(--text-primary)", fontWeight: 600 }}>{displayName}</div>
                    {agent.nickname && (
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)", marginTop: 1 }}>{agent.id?.substring(0, 16)}</div>
                    )}
                  </td>
                  <td>
                    {agent.avg_rating > 0 ? (
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-amber)" }}>
                        {agent.avg_rating?.toFixed(1)} <span style={{ fontSize: 9, color: "var(--text-muted)" }}>({agent.total_ratings})</span>
                      </span>
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: 10 }}>---</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right", color: "var(--text-secondary)" }}>{agent.jobs_completed ?? (agent.success + agent.fail)}</td>
                  <td style={{ textAlign: "right", color: "var(--accent-green)" }}>{agent.success}</td>
                  <td style={{ textAlign: "right", color: "var(--accent-red)" }}>{agent.fail}</td>
                  <td><ScoreBar score={agent.score ?? 0} max={maxScore} /></td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  No agents registered. Register agents to populate the leaderboard.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
