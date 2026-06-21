"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

function MetricCard({ title, value, subtitle, color }) {
  return (
    <div style={{ background: "white", padding: "16px 20px", borderRadius: "8px", border: "1px solid #e5e7eb", minWidth: 140 }}>
      <div style={{ fontSize: "12px", color: "#6b7280", textTransform: "uppercase", fontWeight: 600, letterSpacing: "0.05em" }}>{title}</div>
      <div style={{ fontSize: "28px", fontWeight: 700, color: color || "#111827", marginTop: 4 }}>{value}</div>
      {subtitle && <div style={{ fontSize: "12px", color: "#9ca3af", marginTop: 2 }}>{subtitle}</div>}
    </div>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data } = useSWR(`/api/analytics?days=${days}`, fetcher, { refreshInterval: 30000 });

  if (!data) return <div style={{ padding: 40, textAlign: "center", color: "#9ca3af" }}>Loading analytics...</div>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: "22px", fontWeight: 700, color: "#111827" }}>Execution Analytics</h1>
        <div style={{ display: "flex", gap: 4 }}>
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} style={{
              padding: "4px 12px", borderRadius: 6, border: "1px solid #e5e7eb",
              background: days === d ? "#111827" : "white",
              color: days === d ? "white" : "#374151",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
            }}>{d}d</button>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <MetricCard title="Total Executions" value={data.total_executions} />
        <MetricCard title="Success Rate" value={`${(data.success_rate * 100).toFixed(1)}%`} color={data.success_rate > 0.7 ? "#16a34a" : "#dc2626"} />
        <MetricCard title="Avg Duration" value={`${data.avg_duration}s`} />
        <MetricCard title="Total Cost" value={`$${data.total_cost_usd?.toFixed(4) || "0"}`} />
        <MetricCard title="Live" value={data.live_executions} subtitle="Real LLM calls" />
        <MetricCard title="Simulated" value={data.simulated_executions} subtitle="No API key" />
      </div>

      {data.by_agent && data.by_agent.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "#111827", marginBottom: 12, marginTop: 24 }}>By Agent</h2>
          <div style={{ background: "white", borderRadius: 8, border: "1px solid #e5e7eb", overflow: "hidden", marginBottom: 24 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Agent</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Tasks</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Wins</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Rate</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Avg Duration</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_agent.map((a) => (
                  <tr key={a.agent_id} style={{ borderTop: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "10px 16px", fontWeight: 500 }}>{a.agent_id}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>{a.tasks}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>{a.wins}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right", color: a.success_rate > 0.7 ? "#16a34a" : "#dc2626" }}>{(a.success_rate * 100).toFixed(1)}%</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>{a.avg_duration}s</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>${a.total_cost?.toFixed(4) || "0"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {data.by_model && data.by_model.length > 0 && (
        <>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "#111827", marginBottom: 12 }}>By Model</h2>
          <div style={{ background: "white", borderRadius: 8, border: "1px solid #e5e7eb", overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: "#f9fafb" }}>
                  <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Model</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Uses</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Cost</th>
                  <th style={{ padding: "10px 16px", textAlign: "right", fontWeight: 600, color: "#6b7280" }}>Avg Duration</th>
                </tr>
              </thead>
              <tbody>
                {data.by_model.map((m) => (
                  <tr key={m.model} style={{ borderTop: "1px solid #f3f4f6" }}>
                    <td style={{ padding: "10px 16px", fontWeight: 500, fontFamily: "monospace", fontSize: 12 }}>{m.model}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>{m.uses}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>${m.total_cost?.toFixed(4) || "0"}</td>
                    <td style={{ padding: "10px 16px", textAlign: "right" }}>{m.avg_duration}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
