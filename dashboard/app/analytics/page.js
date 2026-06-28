"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return null; } }).catch(() => null);

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data } = useSWR(`/api/analytics?days=${days}`, fetcher, { refreshInterval: 30000 });

  if (!data) return (
    <div style={{ padding: 60, textAlign: "center", fontFamily: "var(--font-mono)", color: "var(--text-muted)", fontSize: 12 }}>
      LOADING TELEMETRY...
    </div>
  );

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Execution Analytics
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} className={`cmd-btn sm ${days === d ? "active" : ""}`}>{d}D</button>
          ))}
        </div>
      </div>

      <div className="metric-grid" style={{ marginBottom: 16 }}>
        <div className="metric blue">
          <div className="metric-label">Total Executions</div>
          <div className="metric-value">{data.total_executions}</div>
        </div>
        <div className={`metric ${data.success_rate > 0.7 ? "green" : "red"}`}>
          <div className="metric-label">Success Rate</div>
          <div className="metric-value">{(data.success_rate * 100).toFixed(1)}%</div>
          <div className="metric-sub">{data.successes}W / {data.failures}L</div>
        </div>
        <div className="metric cyan">
          <div className="metric-label">Avg Duration</div>
          <div className="metric-value">{data.avg_duration}s</div>
        </div>
        <div className="metric amber">
          <div className="metric-label">Total Cost</div>
          <div className="metric-value">${data.total_cost_usd?.toFixed(4) || "0"}</div>
        </div>
        <div className="metric green">
          <div className="metric-label">Live</div>
          <div className="metric-value">{data.live_executions}</div>
          <div className="metric-sub">Real LLM calls</div>
        </div>
        <div className="metric purple">
          <div className="metric-label">Simulated</div>
          <div className="metric-value">{data.simulated_executions}</div>
          <div className="metric-sub">No API key</div>
        </div>
      </div>

      {data.by_agent && data.by_agent.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="panel-header">
            <div className="panel-title"><span className="dot info" /> Performance by Agent</div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th style={{ textAlign: "right" }}>Tasks</th>
                <th style={{ textAlign: "right" }}>Wins</th>
                <th style={{ textAlign: "right" }}>Rate</th>
                <th style={{ textAlign: "right" }}>Avg Duration</th>
                <th style={{ textAlign: "right" }}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {data.by_agent.map((a) => (
                <tr key={a.agent_id}>
                  <td style={{ color: "var(--accent-cyan)" }}>{a.agent_id}</td>
                  <td style={{ textAlign: "right" }}>{a.tasks}</td>
                  <td style={{ textAlign: "right", color: "var(--accent-green)" }}>{a.wins}</td>
                  <td style={{ textAlign: "right", color: a.success_rate > 0.7 ? "var(--accent-green)" : "var(--accent-red)" }}>
                    {(a.success_rate * 100).toFixed(1)}%
                  </td>
                  <td style={{ textAlign: "right" }}>{a.avg_duration}s</td>
                  <td style={{ textAlign: "right", color: "var(--accent-amber)" }}>${a.total_cost?.toFixed(4) || "0"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.by_model && data.by_model.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title"><span className="dot" /> Model Utilization</div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Model</th>
                <th style={{ textAlign: "right" }}>Uses</th>
                <th style={{ textAlign: "right" }}>Cost</th>
                <th style={{ textAlign: "right" }}>Avg Duration</th>
              </tr>
            </thead>
            <tbody>
              {data.by_model.map((m) => (
                <tr key={m.model}>
                  <td style={{ color: "var(--accent-cyan)", fontSize: 11 }}>{m.model}</td>
                  <td style={{ textAlign: "right" }}>{m.uses}</td>
                  <td style={{ textAlign: "right", color: "var(--accent-amber)" }}>${m.total_cost?.toFixed(4) || "0"}</td>
                  <td style={{ textAlign: "right" }}>{m.avg_duration}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
