"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

const SOURCE_COLORS = {
  github: "#6366f1",
  slack: "#22c55e",
  gmail: "#ef4444",
  drive: "#f59e0b",
  notion: "#a78bfa",
  airtable: "#06b6d4",
  asana: "#f97316",
  trello: "#3b82f6",
  webhook: "#64748b",
};

function SourceBadge({ source }) {
  const color = SOURCE_COLORS[source] ?? "#64748b";
  return (
    <span style={{ background: `${color}22`, color, borderRadius: "4px", padding: "2px 8px", fontSize: "11px", fontWeight: 700, letterSpacing: "0.04em" }}>
      {source?.toUpperCase()}
    </span>
  );
}

export default function SignalIntelligencePage() {
  const { data: signals, error, isLoading } = useSWR("/api/signals", fetcher, { refreshInterval: 3000 });
  const { data: watcherData } = useSWR("/api/watchers", fetcher, { refreshInterval: 10000 });

  const rows = Array.isArray(signals) ? signals : [];
  const active = watcherData?.active ?? [];
  const available = watcherData?.available ?? [];

  return (
    <div>
      <h1 style={{ color: "#e2e8f0", marginTop: 0, marginBottom: "4px" }}>Signal Intelligence</h1>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "28px", fontSize: "14px" }}>
        Live stream of signals detected from connected tools. Every event is evaluated and drafted into a task for the pipeline.
      </p>

      <div style={{ display: "flex", gap: "24px", alignItems: "flex-start" }}>
        {/* Signal feed */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
            <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, margin: 0, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Event Stream
            </h2>
            <span style={{ fontSize: "12px", color: "#64748b" }}>
              {isLoading ? "Loading…" : `${rows.length} event${rows.length !== 1 ? "s" : ""} captured`}
            </span>
          </div>
          {error && <p style={{ color: "#ef4444", fontSize: "14px" }}>Failed to load signals.</p>}
          {!isLoading && rows.length === 0 && (
            <div style={{ background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "32px", textAlign: "center", color: "#64748b", fontSize: "14px" }}>
              No signals captured yet.<br />
              <span style={{ fontSize: "12px" }}>Trigger a webhook (GitHub, Slack, or generic) to see events here.</span>
            </div>
          )}
          {rows.length > 0 && (
            <table style={{ width: "100%", borderCollapse: "collapse", background: "#1a1a2e", borderRadius: "8px", overflow: "hidden" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #2d2d44" }}>
                  {["Time (UTC)", "Source", "Event Type", "Objective Drafted"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", textAlign: "left", fontSize: "11px", color: "#64748b", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((sig, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid #1e1e30" }}>
                    <td style={{ padding: "10px 14px", fontSize: "12px", color: "#64748b", fontFamily: "monospace", whiteSpace: "nowrap" }}>
                      {sig.ts ? sig.ts.replace("T", " ").slice(0, 19) : "—"}
                    </td>
                    <td style={{ padding: "10px 14px" }}>
                      <SourceBadge source={sig.source} />
                    </td>
                    <td style={{ padding: "10px 14px", fontSize: "12px", color: "#94a3b8" }}>{sig.event_type}</td>
                    <td style={{ padding: "10px 14px", fontSize: "13px", color: "#e2e8f0", maxWidth: "380px" }}>
                      <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {sig.objective}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Watcher status sidebar */}
        <div style={{ width: "220px", flexShrink: 0 }}>
          <h2 style={{ color: "#cbd5e1", fontSize: "15px", fontWeight: 600, marginTop: 0, marginBottom: "12px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
            Watchers
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            {available.map((name) => {
              const isActive = active.includes(name);
              return (
                <div
                  key={name}
                  style={{
                    background: "#1a1a2e",
                    border: `1px solid ${isActive ? "#22c55e44" : "#2d2d44"}`,
                    borderRadius: "6px",
                    padding: "8px 12px",
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                  }}
                >
                  <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: isActive ? "#22c55e" : "#374151", flexShrink: 0 }} />
                  <span style={{ fontSize: "13px", color: isActive ? "#e2e8f0" : "#64748b", flex: 1 }}>{name}</span>
                  <span style={{ fontSize: "10px", color: isActive ? "#22c55e" : "#374151", fontWeight: 600 }}>
                    {isActive ? "ON" : "OFF"}
                  </span>
                </div>
              );
            })}
          </div>
          <p style={{ fontSize: "11px", color: "#374151", marginTop: "12px" }}>
            Manage integrations in the <a href="/integrations" style={{ color: "#818cf8" }}>Integrations</a> tab.
          </p>
        </div>
      </div>
    </div>
  );
}
