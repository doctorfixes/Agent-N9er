"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

const STATUS_COLORS = {
  online: { dot: "#22c55e", bg: "#052e16", text: "#86efac" },
  offline: { dot: "#ef4444", bg: "#2d0a0a", text: "#fca5a5" },
};

function ServiceCard({ svc }) {
  const s = svc.online ? STATUS_COLORS.online : STATUS_COLORS.offline;
  return (
    <div style={{ background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "16px", minWidth: "160px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px" }}>
        <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: s.dot, display: "inline-block", flexShrink: 0 }} />
        <span style={{ fontSize: "13px", color: "#94a3b8", fontWeight: 600 }}>{svc.name}</span>
      </div>
      <span style={{ fontSize: "11px", background: s.bg, color: s.text, borderRadius: "4px", padding: "2px 8px" }}>
        {svc.online ? "ONLINE" : "OFFLINE"}
      </span>
    </div>
  );
}

function StatCard({ label, value, accent }) {
  return (
    <div style={{ background: "#1a1a2e", border: `1px solid ${accent}33`, borderRadius: "8px", padding: "20px 24px" }}>
      <div style={{ fontSize: "28px", fontWeight: 700, color: accent }}>{value ?? "—"}</div>
      <div style={{ fontSize: "13px", color: "#64748b", marginTop: "4px" }}>{label}</div>
    </div>
  );
}

export default function MissionControlPage() {
  const { data, error, isLoading } = useSWR("/api/mission-control", fetcher, { refreshInterval: 5000 });

  if (isLoading) return <p style={{ color: "#64748b" }}>Loading Mission Control…</p>;
  if (error) return <p style={{ color: "#ef4444" }}>Failed to load Mission Control data.</p>;

  const { services = [], watchers = {}, task_count = 0, agent_count = 0, recent_signals = [] } = data ?? {};
  const onlineCount = services.filter((s) => s.online).length;

  return (
    <div>
      <h1 style={{ color: "#e2e8f0", marginTop: 0, marginBottom: "4px" }}>Mission Control</h1>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "28px", fontSize: "14px" }}>
        Agent N9er watches every connected tool, drafts the work it finds, and dispatches autonomous agents to clear it — end to end.
      </p>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "16px", marginBottom: "32px" }}>
        <StatCard label="Services Online" value={`${onlineCount} / ${services.length}`} accent="#818cf8" />
        <StatCard label="Active Watchers" value={(watchers.active ?? []).length} accent="#22c55e" />
        <StatCard label="Tasks in Queue" value={task_count} accent="#f59e0b" />
        <StatCard label="Agents Registered" value={agent_count} accent="#a78bfa" />
      </div>

      {/* Service Health */}
      <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Service Health
      </h2>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "12px", marginBottom: "32px" }}>
        {services.length === 0
          ? <p style={{ color: "#64748b", fontSize: "14px" }}>No service data available.</p>
          : services.map((svc) => <ServiceCard key={svc.name} svc={svc} />)
        }
      </div>

      {/* Recent Signals */}
      <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        Recent Signals
      </h2>
      {recent_signals.length === 0 ? (
        <p style={{ color: "#64748b", fontSize: "14px" }}>No signals yet. Trigger a webhook to see activity here.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", background: "#1a1a2e", borderRadius: "8px", overflow: "hidden" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #2d2d44" }}>
              {["Time", "Source", "Event", "Objective"].map((h) => (
                <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: "12px", color: "#64748b", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {recent_signals.map((sig, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #1e1e30" }}>
                <td style={{ padding: "10px 14px", fontSize: "12px", color: "#64748b", whiteSpace: "nowrap" }}>{sig.ts?.slice(11, 19)}</td>
                <td style={{ padding: "10px 14px", fontSize: "12px", color: "#818cf8", fontWeight: 600 }}>{sig.source}</td>
                <td style={{ padding: "10px 14px", fontSize: "12px", color: "#94a3b8" }}>{sig.event_type}</td>
                <td style={{ padding: "10px 14px", fontSize: "13px", color: "#e2e8f0" }}>{sig.objective}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
