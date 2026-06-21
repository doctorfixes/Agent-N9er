"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

const INTEGRATIONS = [
  { name: "github",   label: "GitHub",   icon: "🐙", desc: "Issues, PRs, and push events via webhook." },
  { name: "slack",    label: "Slack",    icon: "💬", desc: "Task messages and app mentions in any channel." },
  { name: "gmail",    label: "Gmail",    icon: "📧", desc: "Unread email threads drafted into tasks." },
  { name: "drive",    label: "Drive",    icon: "📁", desc: "New and updated files in watched folders." },
  { name: "notion",   label: "Notion",   icon: "📝", desc: "Page updates and new database entries." },
  { name: "airtable", label: "Airtable", icon: "📊", desc: "New records and field changes in linked bases." },
  { name: "asana",    label: "Asana",    icon: "✅", desc: "New tasks and project updates." },
  { name: "trello",   label: "Trello",   icon: "🗂️", desc: "New cards and list movements." },
];

export default function IntegrationsPage() {
  const { data, error, isLoading, mutate } = useSWR("/api/watchers", fetcher, { refreshInterval: 8000 });
  const [toggling, setToggling] = useState({});

  const active = new Set(data?.active ?? []);

  async function toggle(name) {
    const isActive = active.has(name);
    setToggling((t) => ({ ...t, [name]: true }));
    try {
      await fetch(`/api/watchers/${name}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: isActive ? "deactivate" : "activate" }),
      });
      await mutate();
    } catch {
      // silently ignore; next poll will sync
    }
    setToggling((t) => ({ ...t, [name]: false }));
  }

  const activeCount = active.size;

  return (
    <div>
      <h1 style={{ color: "#e2e8f0", marginTop: 0, marginBottom: "4px" }}>Data Source Integrations</h1>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "8px", fontSize: "14px" }}>
        Connect the tools Agent N9er watches. When a watcher is active, incoming events are automatically drafted into tasks and dispatched through the pipeline.
      </p>
      <p style={{ color: "#64748b", marginTop: 0, marginBottom: "28px", fontSize: "13px" }}>
        {isLoading ? "Loading watcher status…" : error ? "Could not reach browser service." : `${activeCount} of ${INTEGRATIONS.length} watchers active.`}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "16px" }}>
        {INTEGRATIONS.map(({ name, label, icon, desc }) => {
          const isActive = active.has(name);
          const isToggling = !!toggling[name];
          return (
            <div
              key={name}
              style={{
                background: "#1a1a2e",
                border: `1px solid ${isActive ? "#22c55e44" : "#2d2d44"}`,
                borderRadius: "10px",
                padding: "20px",
                display: "flex",
                flexDirection: "column",
                gap: "10px",
                transition: "border-color 0.2s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <span style={{ fontSize: "24px" }}>{icon}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: "15px", color: "#e2e8f0" }}>{label}</div>
                  <div style={{ fontSize: "11px", color: "#64748b", marginTop: "2px" }}>{desc}</div>
                </div>
                <span
                  style={{
                    width: "8px", height: "8px", borderRadius: "50%", flexShrink: 0,
                    background: isActive ? "#22c55e" : "#374151",
                    boxShadow: isActive ? "0 0 6px #22c55e88" : "none",
                  }}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{
                  fontSize: "11px", fontWeight: 700, letterSpacing: "0.04em",
                  color: isActive ? "#22c55e" : "#64748b",
                  background: isActive ? "#052e1644" : "#1e1e3044",
                  borderRadius: "4px", padding: "2px 8px",
                }}>
                  {isActive ? "● ACTIVE" : "○ INACTIVE"}
                </span>
                <button
                  onClick={() => toggle(name)}
                  disabled={isToggling}
                  style={{
                    padding: "6px 14px",
                    background: isActive ? "#2d0a0a" : "#0f172a",
                    color: isActive ? "#f87171" : "#818cf8",
                    border: `1px solid ${isActive ? "#ef444444" : "#818cf844"}`,
                    borderRadius: "6px",
                    cursor: isToggling ? "not-allowed" : "pointer",
                    fontSize: "12px",
                    fontWeight: 600,
                    opacity: isToggling ? 0.6 : 1,
                    transition: "opacity 0.15s",
                  }}
                >
                  {isToggling ? "…" : isActive ? "Deactivate" : "Activate"}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: "32px", background: "#1a1a2e", border: "1px solid #2d2d44", borderRadius: "8px", padding: "20px" }}>
        <h2 style={{ color: "#cbd5e1", fontSize: "14px", fontWeight: 600, margin: "0 0 10px", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Webhook Endpoints
        </h2>
        <p style={{ color: "#64748b", fontSize: "13px", margin: "0 0 10px" }}>
          Configure your connected tools to send events to these endpoints on the browser-service.
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          {[
            ["GitHub", "POST /webhooks/github", "X-GitHub-Event header required"],
            ["Slack", "POST /webhooks/slack", "X-Slack-Signature verification supported"],
            ["Generic", "POST /webhooks/generic", "JSON body with objective, title, or message field"],
          ].map(([label, path, note]) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "8px 0", borderBottom: "1px solid #1e1e30" }}>
              <span style={{ fontSize: "13px", color: "#94a3b8", minWidth: "70px" }}>{label}</span>
              <code style={{ fontSize: "12px", color: "#818cf8", background: "#0d0d14", padding: "2px 8px", borderRadius: "4px" }}>{path}</code>
              <span style={{ fontSize: "11px", color: "#374151" }}>{note}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
