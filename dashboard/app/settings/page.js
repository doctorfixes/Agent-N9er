"use client";

import { useState, useEffect } from "react";

const SECTIONS = [
  { key: "agent", label: "Agent Identity" },
  { key: "api", label: "API Configuration" },
  { key: "scanning", label: "Scanning & Discovery" },
  { key: "guardrails", label: "Safety Guardrails" },
  { key: "billing", label: "Billing & Pricing" },
  { key: "notifications", label: "Notifications" },
];

const FIELD_META = {
  agent: {
    alias: { label: "Agent Alias", type: "text", hint: "Display name across all platforms" },
    description: { label: "Description", type: "text", hint: "Short bio shown in proposals and bids" },
    avatar_emoji: { label: "Avatar Code", type: "text", hint: "Emoji or character for the agent identity" },
  },
  api: {
    openrouter_model: { label: "Primary LLM Model", type: "select", options: [
      "anthropic/claude-sonnet-4-20250514", "anthropic/claude-haiku-4-5-20251001",
      "anthropic/claude-opus-4-20250514", "openai/gpt-4o", "openai/gpt-4o-mini",
      "google/gemini-2.5-pro", "meta-llama/llama-4-maverick",
    ], hint: "Model used for task execution and proposals" },
    openrouter_fallback: { label: "Fallback Model", type: "select", options: [
      "anthropic/claude-haiku-4-5-20251001", "openai/gpt-4o-mini",
      "google/gemini-2.5-flash", "meta-llama/llama-4-scout",
    ], hint: "Cheaper model for simple tasks and retries" },
    default_timeout: { label: "Default Timeout (sec)", type: "number", hint: "HTTP request timeout for service calls" },
    max_retries: { label: "Max Retries", type: "number", hint: "Retry count on transient failures" },
  },
  scanning: {
    auto_scan_enabled: { label: "Auto-Scan Enabled", type: "toggle", hint: "Automatically discover prospects on interval" },
    scan_interval_seconds: { label: "Scan Interval (sec)", type: "number", hint: "Time between automated scans" },
    scan_platforms: { label: "Active Platforms", type: "textarea", hint: "Comma-separated platform names to scan" },
    scan_keywords: { label: "Search Keywords", type: "textarea", hint: "Keywords for web-wide search (comma-separated)" },
    reddit_subreddits: { label: "Reddit Subreddits", type: "textarea", hint: "Subreddits to scan for gigs (comma-separated)" },
    craigslist_regions: { label: "Craigslist Regions", type: "text", hint: "Metro regions to scan (comma-separated)" },
    custom_rss_feeds: { label: "Custom RSS Feeds", type: "textarea", hint: "RSS feed URLs, one per line or comma-separated" },
    auto_evaluate: { label: "Auto-Evaluate New Prospects", type: "toggle", hint: "Automatically run evaluator on discovered prospects" },
  },
  guardrails: {
    max_single_task_usd: { label: "Max Single Task ($)", type: "number", hint: "Maximum spend per individual task" },
    max_daily_spend_usd: { label: "Max Daily Spend ($)", type: "number", hint: "Maximum total daily spending across all tasks" },
    require_approval_above_usd: { label: "Require Approval Above ($)", type: "number", hint: "Tasks above this amount need manual approval" },
    auto_execute_enabled: { label: "Auto-Execute Enabled", type: "toggle", hint: "Allow agent to execute tasks without manual approval" },
  },
  billing: {
    markup_multiplier: { label: "Markup Multiplier", type: "number", hint: "Quote = estimated cost x multiplier (e.g. 3.0 = 3x markup)" },
    minimum_quote_usd: { label: "Minimum Quote ($)", type: "number", hint: "Floor price for any quoted task" },
  },
  notifications: {
    smtp_host: { label: "SMTP Host", type: "text", hint: "Email server host (e.g. smtp.gmail.com)" },
    smtp_port: { label: "SMTP Port", type: "number", hint: "Usually 587 for TLS" },
    smtp_user: { label: "SMTP User", type: "text", hint: "Email address for sending" },
    notify_email: { label: "Notification Email", type: "text", hint: "Where to send high-value prospect alerts" },
    notify_min_budget: { label: "Alert Threshold ($)", type: "number", hint: "Minimum budget to trigger email alert" },
  },
};

function SettingsField({ field, value, onChange }) {
  const { label, type, hint, options } = field;

  if (type === "toggle") {
    return (
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 0", borderBottom: "1px solid rgba(30,45,74,0.3)" }}>
        <div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-primary)", fontWeight: 500 }}>{label}</div>
          {hint && <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>{hint}</div>}
        </div>
        <button
          onClick={() => onChange(!value)}
          style={{
            width: 44, height: 24, borderRadius: 12, border: "none", cursor: "pointer",
            background: value ? "rgba(16,185,129,0.3)" : "rgba(100,116,139,0.3)",
            position: "relative", transition: "background 0.2s",
          }}
        >
          <div style={{
            width: 18, height: 18, borderRadius: 9, position: "absolute", top: 3,
            left: value ? 23 : 3, transition: "left 0.2s",
            background: value ? "#34d399" : "#64748b",
          }} />
        </button>
      </div>
    );
  }

  if (type === "select") {
    return (
      <div style={{ padding: "10px 0", borderBottom: "1px solid rgba(30,45,74,0.3)" }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-primary)", fontWeight: 500, marginBottom: 4 }}>{label}</div>
        {hint && <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginBottom: 6 }}>{hint}</div>}
        <select
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          className="cmd-select"
          style={{ width: "100%", padding: "8px 10px", fontSize: 12 }}
        >
          {options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      </div>
    );
  }

  if (type === "textarea") {
    return (
      <div style={{ padding: "10px 0", borderBottom: "1px solid rgba(30,45,74,0.3)" }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-primary)", fontWeight: 500, marginBottom: 4 }}>{label}</div>
        {hint && <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginBottom: 6 }}>{hint}</div>}
        <textarea
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
          rows={3}
          style={{
            width: "100%", fontFamily: "var(--font-mono)", fontSize: 12,
            background: "var(--bg-input)", color: "var(--text-primary)",
            border: "1px solid var(--border)", borderRadius: 4, padding: "8px 12px",
            outline: "none", resize: "vertical",
          }}
        />
      </div>
    );
  }

  return (
    <div style={{ padding: "10px 0", borderBottom: "1px solid rgba(30,45,74,0.3)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-primary)", fontWeight: 500, marginBottom: 4 }}>{label}</div>
      {hint && <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginBottom: 6 }}>{hint}</div>}
      <input
        type={type === "number" ? "number" : "text"}
        value={value ?? ""}
        onChange={(e) => onChange(type === "number" ? parseFloat(e.target.value) || 0 : e.target.value)}
        className="cmd-input"
        style={{ width: "100%" }}
      />
    </div>
  );
}

export default function SettingsPage() {
  const [settings, setSettings] = useState(null);
  const [activeSection, setActiveSection] = useState("agent");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch("/api/settings").then((r) => r.json()).then(setSettings).catch(() => setError("Failed to load settings"));
  }, []);

  const handleChange = (section, key, value) => {
    setSettings((prev) => ({
      ...prev,
      [section]: { ...prev[section], [key]: value },
    }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const resp = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      const data = await resp.json();
      if (data.ok) {
        setSettings(data.settings);
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        setError("Save failed");
      }
    } catch (e) {
      setError(e.message);
    }
    setSaving(false);
  };

  const handleReset = async () => {
    try {
      const resp = await fetch("/api/settings");
      setSettings(await resp.json());
      setSaved(false);
    } catch (e) {
      setError(e.message);
    }
  };

  if (!settings) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 60, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>
        {error || "Loading settings..."}
      </div>
    );
  }

  const sectionFields = FIELD_META[activeSection] || {};

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Settings
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {saved && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#34d399" }}>
              SAVED
            </span>
          )}
          {error && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#f87171" }}>
              {error}
            </span>
          )}
          <button className="cmd-btn" onClick={handleReset}>Reset</button>
          <button className="cmd-btn success" onClick={handleSave} disabled={saving}>
            {saving ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 16 }}>
        <div className="panel" style={{ padding: 0, height: "fit-content" }}>
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => setActiveSection(s.key)}
              style={{
                display: "block", width: "100%", textAlign: "left",
                padding: "10px 16px", border: "none", cursor: "pointer",
                fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 500,
                letterSpacing: "0.04em",
                background: activeSection === s.key ? "rgba(6,182,212,0.1)" : "transparent",
                color: activeSection === s.key ? "var(--accent-cyan)" : "var(--text-muted)",
                borderLeft: activeSection === s.key ? "2px solid var(--accent-cyan)" : "2px solid transparent",
                transition: "all 0.15s",
              }}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="panel" style={{ padding: "16px 20px" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 16, paddingBottom: 10, borderBottom: "1px solid var(--border)" }}>
            {SECTIONS.find((s) => s.key === activeSection)?.label}
          </div>

          {Object.entries(sectionFields).map(([key, fieldMeta]) => (
            <SettingsField
              key={key}
              field={fieldMeta}
              value={settings[activeSection]?.[key]}
              onChange={(val) => handleChange(activeSection, key, val)}
            />
          ))}

          {activeSection === "agent" && (
            <div style={{ marginTop: 20, padding: 16, background: "rgba(6,182,212,0.05)", border: "1px solid rgba(6,182,212,0.15)", borderRadius: 6 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Preview</div>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{ width: 40, height: 40, borderRadius: 8, background: "rgba(6,182,212,0.15)", border: "1px solid rgba(6,182,212,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20 }}>
                  {settings.agent.avatar_emoji}
                </div>
                <div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--text-primary)" }}>
                    {settings.agent.alias}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
                    {settings.agent.description}
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeSection === "guardrails" && (
            <div style={{ marginTop: 20, padding: 16, background: "rgba(245,158,11,0.05)", border: "1px solid rgba(245,158,11,0.15)", borderRadius: 6 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-amber)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Guardrail Summary</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.8 }}>
                <div>Max per task: <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>${settings.guardrails.max_single_task_usd}</span></div>
                <div>Daily limit: <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>${settings.guardrails.max_daily_spend_usd}</span></div>
                <div>Approval needed above: <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>${settings.guardrails.require_approval_above_usd}</span></div>
                <div>Auto-execute: <span style={{ color: settings.guardrails.auto_execute_enabled ? "#34d399" : "#f87171", fontWeight: 600 }}>{settings.guardrails.auto_execute_enabled ? "ON" : "OFF"}</span></div>
              </div>
            </div>
          )}

          {activeSection === "scanning" && (
            <div style={{ marginTop: 20, padding: 16, background: "rgba(16,185,129,0.05)", border: "1px solid rgba(16,185,129,0.15)", borderRadius: 6 }}>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-green)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Active Sources</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {(settings.scanning.scan_platforms || "").split(",").filter(Boolean).map((p) => (
                  <span key={p} style={{
                    padding: "2px 8px", borderRadius: 3, fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 600,
                    background: "rgba(16,185,129,0.1)", border: "1px solid rgba(16,185,129,0.2)", color: "#34d399",
                  }}>{p.trim()}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
