"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json()).catch(() => null);

const severityColors = {
  info: { bg: "rgba(6,182,212,0.1)", color: "#22d3ee", border: "rgba(6,182,212,0.3)" },
  warn: { bg: "rgba(234,179,8,0.1)", color: "#facc15", border: "rgba(234,179,8,0.3)" },
  error: { bg: "rgba(239,68,68,0.1)", color: "#f87171", border: "rgba(239,68,68,0.3)" },
};

const outcomeColors = {
  ok: "#4ade80",
  resolved: "#4ade80",
  queued: "#22d3ee",
  pending: "#94a3b8",
  partial: "#facc15",
  degraded: "#facc15",
  skipped: "#94a3b8",
  blocked: "#f97316",
  rejected: "#f87171",
  error: "#f87171",
};

export default function JournalPage() {
  const [severityFilter, setSeverityFilter] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const params = new URLSearchParams({ limit: "100" });
  if (severityFilter) params.set("severity", severityFilter);
  if (eventFilter) params.set("event", eventFilter);

  const { data: journal } = useSWR(`/api/journal?${params}`, fetcher, { refreshInterval: 10000 });
  const { data: awareness } = useSWR("/api/self-awareness", fetcher, { refreshInterval: 30000 });

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Decision Journal
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {["", "info", "warn", "error"].map((s) => (
            <button key={s} onClick={() => setSeverityFilter(s)} className={`cmd-btn sm ${severityFilter === s ? "active" : ""}`}>
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {awareness && (
        <div className="panel" style={{ marginBottom: 16, padding: 16 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", marginBottom: 12, letterSpacing: "0.08em" }}>
            Self-Awareness Report
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12, marginBottom: 12 }}>
            <div className="metric">
              <div className="metric-label">Services</div>
              <div className="metric-value" style={{ color: awareness.health?.status === "healthy" ? "#4ade80" : "#facc15" }}>
                {awareness.health?.services_online || "?"}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Scans</div>
              <div className="metric-value">{awareness.activity?.total_scans ?? 0}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Discovered</div>
              <div className="metric-value">{awareness.activity?.total_discovered ?? 0}</div>
            </div>
            <div className="metric">
              <div className="metric-label">Errors (24h)</div>
              <div className="metric-value" style={{ color: awareness.stability?.errors_24h > 0 ? "#f87171" : "#4ade80" }}>
                {awareness.stability?.errors_24h ?? 0}
              </div>
            </div>
            <div className="metric">
              <div className="metric-label">Warnings (24h)</div>
              <div className="metric-value" style={{ color: awareness.stability?.warnings_24h > 0 ? "#facc15" : "#4ade80" }}>
                {awareness.stability?.warnings_24h ?? 0}
              </div>
            </div>
          </div>

          {awareness.issues?.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#f87171", fontWeight: 700, marginBottom: 4 }}>ISSUES</div>
              {awareness.issues.map((issue, i) => (
                <div key={i} style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#f87171", padding: "2px 0" }}>- {issue}</div>
              ))}
            </div>
          )}

          {awareness.recommendations?.length > 0 && (
            <div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#4ade80", fontWeight: 700, marginBottom: 4 }}>RECOMMENDATIONS</div>
              {awareness.recommendations.map((rec, i) => (
                <div key={i} style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", padding: "2px 0" }}>+ {rec}</div>
              ))}
            </div>
          )}
        </div>
      )}

      <div style={{ marginBottom: 12 }}>
        <input
          type="text"
          placeholder="Filter by event type..."
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          style={{
            background: "rgba(15,23,42,0.6)", border: "1px solid rgba(30,45,74,0.5)",
            color: "var(--text-primary)", fontFamily: "var(--font-mono)", fontSize: 11,
            padding: "6px 10px", borderRadius: 4, width: 300,
          }}
        />
        {journal && (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginLeft: 12 }}>
            {journal.total ?? 0} entries
          </span>
        )}
      </div>

      <div className="panel" style={{ maxHeight: "calc(100vh - 360px)", overflow: "auto" }}>
        <table className="cmd-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th style={{ width: 150 }}>Time</th>
              <th style={{ width: 60 }}>Severity</th>
              <th style={{ width: 160 }}>Event</th>
              <th>Decision</th>
              <th>Reasoning</th>
              <th style={{ width: 80 }}>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {journal?.entries?.length > 0 ? journal.entries.map((e) => {
              const sev = severityColors[e.severity] || severityColors.info;
              return (
                <tr key={e.id}>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                    {e.timestamp ? new Date(e.timestamp).toLocaleString() : "---"}
                  </td>
                  <td>
                    <span style={{
                      fontSize: 9, fontFamily: "var(--font-mono)", fontWeight: 700,
                      padding: "2px 6px", borderRadius: 3, textTransform: "uppercase",
                      background: sev.bg, color: sev.color, border: `1px solid ${sev.border}`,
                    }}>
                      {e.severity}
                    </span>
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent-cyan)" }}>
                    {e.event}
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-primary)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {e.decision}
                  </td>
                  <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-secondary)", maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {e.reasoning}
                  </td>
                  <td>
                    <span style={{
                      fontSize: 9, fontFamily: "var(--font-mono)", fontWeight: 600,
                      color: outcomeColors[e.outcome] || "#94a3b8",
                    }}>
                      {e.outcome}
                    </span>
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={6} style={{ padding: 40, textAlign: "center", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
                  Awaiting journal entries...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
