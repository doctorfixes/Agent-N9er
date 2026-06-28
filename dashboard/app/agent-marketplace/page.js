"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return null; } }).catch(() => null);

function ScoreBar({ score }) {
  const pct = Math.min(100, Math.max(0, (score ?? 0) * 100));
  const color = pct >= 70 ? "#22c55e" : pct >= 40 ? "#f59e0b" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
      <div style={{ flex: 1, height: "6px", background: "#2d2d44", borderRadius: "3px", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: "3px", transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: "12px", color, fontWeight: 600, minWidth: "36px", textAlign: "right" }}>
        {score != null ? score.toFixed(2) : "—"}
      </span>
    </div>
  );
}

export default function AgentMarketplacePage() {
  const { data: agentData, error, isLoading } = useSWR("/api/agents", fetcher, { refreshInterval: 5000 });
  const { data: taskData } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });
  const [simLoading, setSimLoading] = useState(false);
  const [simResult, setSimResult] = useState(null);

  const agents = agentData && typeof agentData === "object" ? Object.entries(agentData) : [];
  const tasks = Array.isArray(taskData) ? taskData : [];
  const openTasks = tasks.filter((t) => !t.status || t.status === "published" || t.status === "unknown").length;

  async function runSimulation() {
    setSimLoading(true);
    setSimResult(null);
    try {
      const resp = await fetch("/api/simulate?n=5", { method: "GET" });
      setSimResult(await resp.text().then((t) => { try { return JSON.parse(t); } catch { return {}; } }));
    } catch {
      setSimResult({ error: "Simulation failed" });
    }
    setSimLoading(false);
  }

  const totalWins = agents.reduce((s, [, a]) => s + (a.success ?? 0), 0);
  const totalLosses = agents.reduce((s, [, a]) => s + (a.fail ?? 0), 0);

  return (
    <div>
      <h1 style={{ color: "#e2e8f0", marginTop: 0, marginBottom: "4px" }}>Agent Marketplace</h1>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "28px", fontSize: "14px" }}>
        Autonomous agents bid on tasks, compete on confidence and price, and are dispatched to execute. Reputation is updated after each job.
      </p>

      {/* Summary stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: "14px", marginBottom: "28px" }}>
        {[
          ["Registered Agents", agents.length, "#818cf8"],
          ["Open Tasks", openTasks, "#f59e0b"],
          ["Total Wins", totalWins, "#22c55e"],
          ["Total Losses", totalLosses, "#ef4444"],
        ].map(([label, val, color]) => (
          <div key={label} style={{ background: "#1a1a2e", border: `1px solid ${color}33`, borderRadius: "8px", padding: "16px 20px" }}>
            <div style={{ fontSize: "26px", fontWeight: 700, color }}>{val}</div>
            <div style={{ fontSize: "12px", color: "#64748b", marginTop: "4px" }}>{label}</div>
          </div>
        ))}
      </div>

      {/* Agent leaderboard */}
      <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Agent Leaderboard
      </h2>
      {error && <p style={{ color: "#ef4444", fontSize: "14px" }}>Failed to load agent data.</p>}
      {isLoading && <p style={{ color: "#64748b" }}>Loading agents…</p>}
      {!isLoading && agents.length === 0 ? (
        <div style={{ background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "32px", textAlign: "center", color: "#64748b", fontSize: "14px", marginBottom: "28px" }}>
          No agents registered yet.<br />
          <span style={{ fontSize: "12px" }}>Run a simulation or register agents via the orchestrator to populate the leaderboard.</span>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "#1a1a2e", borderRadius: "8px", overflow: "hidden", marginBottom: "28px" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #2d2d44" }}>
              {["Rank", "Agent ID", "Wins", "Losses", "Win Rate", "Reputation Score"].map((h) => (
                <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: "11px", color: "#64748b", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents
              .sort(([, a], [, b]) => (b.score ?? 0) - (a.score ?? 0))
              .map(([id, stats], i) => {
                const total = (stats.success ?? 0) + (stats.fail ?? 0);
                const winRate = total > 0 ? ((stats.success ?? 0) / total) : null;
                return (
                  <tr key={id} style={{ borderBottom: "1px solid #1e1e30" }}>
                    <td style={{ padding: "10px 14px", fontSize: "13px", color: "#64748b", fontWeight: 600 }}>#{i + 1}</td>
                    <td style={{ padding: "10px 14px", fontFamily: "monospace", fontSize: "12px", color: "#818cf8" }}>{id.slice(0, 12)}…</td>
                    <td style={{ padding: "10px 14px", fontSize: "13px", color: "#22c55e", fontWeight: 600 }}>{stats.success ?? 0}</td>
                    <td style={{ padding: "10px 14px", fontSize: "13px", color: "#ef4444" }}>{stats.fail ?? 0}</td>
                    <td style={{ padding: "10px 14px", minWidth: "140px" }}>
                      <ScoreBar score={winRate} />
                    </td>
                    <td style={{ padding: "10px 14px", fontSize: "13px", color: "#a78bfa", fontWeight: 600 }}>
                      {stats.score != null ? stats.score.toFixed(3) : "—"}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      )}

      {/* Simulation */}
      <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Run Simulation
      </h2>
      <div style={{ background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "20px" }}>
        <p style={{ color: "#94a3b8", fontSize: "13px", margin: "0 0 14px" }}>
          Simulate 5 rounds of agent bidding and task execution in-memory to populate the leaderboard.
        </p>
        <button
          onClick={runSimulation}
          disabled={simLoading}
          style={{ padding: "8px 20px", background: "#4f46e5", color: "white", border: "none", borderRadius: "6px", cursor: simLoading ? "not-allowed" : "pointer", fontWeight: 600, fontSize: "14px", opacity: simLoading ? 0.7 : 1 }}
        >
          {simLoading ? "Running…" : "Simulate 5 Rounds"}
        </button>
        {simResult && (
          <pre style={{ marginTop: "12px", background: "#0d0d14", border: "1px solid #2d2d44", borderRadius: "6px", padding: "12px", overflow: "auto", maxHeight: "300px", fontSize: "12px", color: "#94a3b8" }}>
            {JSON.stringify(simResult, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
