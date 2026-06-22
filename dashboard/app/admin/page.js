"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json()).catch(() => null);

function Panel({ title, dot, children, actions }) {
  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <span className={`dot ${dot || ""}`} />
          {title}
        </div>
        {actions && <div style={{ display: "flex", gap: 6 }}>{actions}</div>}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  );
}

function TabBar({ tabs, active, onChange }) {
  return (
    <div className="admin-tabs">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          className={`admin-tab ${active === tab.id ? "active" : ""}`}
          onClick={() => onChange(tab.id)}
        >
          <span className="tab-icon">{tab.icon}</span>
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function RoleBadge({ role }) {
  const colors = {
    admin: "var(--accent-red)",
    operator: "var(--accent-cyan)",
    viewer: "var(--accent-green)",
  };
  return (
    <span
      style={{
        padding: "2px 8px",
        borderRadius: 3,
        fontSize: 10,
        fontFamily: "var(--font-mono)",
        fontWeight: 600,
        textTransform: "uppercase",
        background: `${colors[role] || "var(--text-muted)"}20`,
        color: colors[role] || "var(--text-muted)",
        border: `1px solid ${colors[role] || "var(--text-muted)"}40`,
      }}
    >
      {role}
    </span>
  );
}

function StatusIndicator({ status }) {
  const colors = {
    healthy: "var(--accent-green)",
    degraded: "var(--accent-yellow, #f59e0b)",
    unreachable: "var(--accent-red)",
  };
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: colors[status] || "var(--text-muted)",
        boxShadow: `0 0 6px ${colors[status] || "var(--text-muted)"}60`,
      }}
    />
  );
}

// ──────────────────────────────────────────────
// System Health Tab
// ──────────────────────────────────────────────

function SystemHealthTab() {
  const { data: health } = useSWR("/api/admin/health", fetcher, { refreshInterval: 15000 });

  if (!health) {
    return <div className="admin-loading">Loading system health...</div>;
  }

  const services = health.services ? Object.entries(health.services) : [];
  const healthyCount = services.filter(([, v]) => v.status === "healthy").length;

  return (
    <div>
      <div className="admin-summary-bar">
        <div className="admin-summary-item">
          <span className="admin-summary-label">Overall</span>
          <span className={`admin-summary-value ${health.overall === "healthy" ? "green" : "red"}`}>
            {health.overall?.toUpperCase()}
          </span>
        </div>
        <div className="admin-summary-item">
          <span className="admin-summary-label">Services</span>
          <span className="admin-summary-value">{healthyCount}/{services.length}</span>
        </div>
        <div className="admin-summary-item">
          <span className="admin-summary-label">Last Check</span>
          <span className="admin-summary-value mono">
            {health.checked_at ? new Date(health.checked_at).toLocaleTimeString() : "---"}
          </span>
        </div>
      </div>

      <div className="admin-service-grid">
        {services.map(([name, info]) => (
          <div key={name} className="admin-service-card">
            <div className="service-card-header">
              <StatusIndicator status={info.status} />
              <span className="service-name">{name}</span>
            </div>
            <div className="service-card-body">
              <div className="service-detail">
                <span className="detail-label">Status</span>
                <span className={`detail-value ${info.status}`}>{info.status}</span>
              </div>
              <div className="service-detail">
                <span className="detail-label">URL</span>
                <span className="detail-value mono">{info.url}</span>
              </div>
              {info.error && (
                <div className="service-detail">
                  <span className="detail-label">Error</span>
                  <span className="detail-value error">{info.error.substring(0, 60)}</span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────
// Users Tab
// ──────────────────────────────────────────────

function UsersTab() {
  const { data: users, mutate } = useSWR("/api/admin/users", fetcher, { refreshInterval: 30000 });
  const [showForm, setShowForm] = useState(false);
  const [newUser, setNewUser] = useState({ username: "", password: "", role: "viewer", display_name: "", email: "" });
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!newUser.username || !newUser.password) return;
    setCreating(true);
    try {
      const resp = await fetch("/api/admin/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newUser),
      });
      if (resp.ok) {
        setNewUser({ username: "", password: "", role: "viewer", display_name: "", email: "" });
        setShowForm(false);
        mutate();
      }
    } catch {
      // Error handled silently
    }
    setCreating(false);
  };

  const userList = Array.isArray(users) ? users : [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>
          {userList.length} user{userList.length !== 1 ? "s" : ""} registered
        </div>
        <button className="cmd-btn sm primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? "Cancel" : "+ New User"}
        </button>
      </div>

      {showForm && (
        <div className="admin-form-card">
          <div className="admin-form-grid">
            <div className="form-field">
              <label>Username</label>
              <input className="cmd-input" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} placeholder="username" />
            </div>
            <div className="form-field">
              <label>Password</label>
              <input className="cmd-input" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} placeholder="password" />
            </div>
            <div className="form-field">
              <label>Role</label>
              <select className="cmd-select" value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
                <option value="viewer">Viewer</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="form-field">
              <label>Display Name</label>
              <input className="cmd-input" value={newUser.display_name} onChange={(e) => setNewUser({ ...newUser, display_name: e.target.value })} placeholder="Display name" />
            </div>
            <div className="form-field">
              <label>Email</label>
              <input className="cmd-input" type="email" value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} placeholder="email@example.com" />
            </div>
            <div className="form-field" style={{ display: "flex", alignItems: "flex-end" }}>
              <button className="cmd-btn primary" onClick={handleCreate} disabled={creating || !newUser.username || !newUser.password}>
                {creating ? "Creating..." : "Create User"}
              </button>
            </div>
          </div>
        </div>
      )}

      <table className="data-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Display Name</th>
            <th>Role</th>
            <th>Email</th>
            <th>Created</th>
            <th>Last Login</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {userList.map((u) => (
            <tr key={u.user_id}>
              <td style={{ color: "var(--accent-cyan)", fontFamily: "var(--font-mono)" }}>{u.username}</td>
              <td>{u.display_name}</td>
              <td><RoleBadge role={u.role} /></td>
              <td style={{ color: "var(--text-muted)" }}>{u.email || "---"}</td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {u.created_at ? new Date(u.created_at).toLocaleDateString() : "---"}
              </td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}
              </td>
              <td>
                <span className={`badge ${u.active ? "approved" : "rejected"}`}>
                  {u.active ? "Active" : "Disabled"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────
// API Keys Tab
// ──────────────────────────────────────────────

function APIKeysTab() {
  const { data: keys, mutate } = useSWR("/api/admin/apikeys", fetcher, { refreshInterval: 30000 });
  const [showForm, setShowForm] = useState(false);
  const [newKey, setNewKey] = useState({ name: "", role: "viewer", expires_in_days: 90 });
  const [createdKey, setCreatedKey] = useState(null);
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    if (!newKey.name) return;
    setCreating(true);
    try {
      const resp = await fetch("/api/admin/apikeys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newKey),
      });
      if (resp.ok) {
        const data = await resp.json();
        setCreatedKey(data.api_key);
        setNewKey({ name: "", role: "viewer", expires_in_days: 90 });
        mutate();
      }
    } catch {
      // Error handled silently
    }
    setCreating(false);
  };

  const handleRevoke = async (keyId) => {
    try {
      await fetch(`/api/admin/apikeys?key_id=${keyId}`, { method: "DELETE" });
      mutate();
    } catch {
      // Error handled silently
    }
  };

  const keyList = Array.isArray(keys) ? keys : [];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-muted)" }}>
          {keyList.filter((k) => k.active).length} active key{keyList.filter((k) => k.active).length !== 1 ? "s" : ""}
        </div>
        <button className="cmd-btn sm primary" onClick={() => { setShowForm(!showForm); setCreatedKey(null); }}>
          {showForm ? "Cancel" : "+ New API Key"}
        </button>
      </div>

      {showForm && (
        <div className="admin-form-card">
          {createdKey && (
            <div className="admin-key-reveal">
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent-green)", marginBottom: 4 }}>
                API Key Created - Copy now, it won't be shown again:
              </div>
              <code className="admin-key-value">{createdKey}</code>
            </div>
          )}
          <div className="admin-form-grid">
            <div className="form-field">
              <label>Key Name</label>
              <input className="cmd-input" value={newKey.name} onChange={(e) => setNewKey({ ...newKey, name: e.target.value })} placeholder="e.g. CI Pipeline Key" />
            </div>
            <div className="form-field">
              <label>Role</label>
              <select className="cmd-select" value={newKey.role} onChange={(e) => setNewKey({ ...newKey, role: e.target.value })}>
                <option value="viewer">Viewer</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="form-field">
              <label>Expires In (days)</label>
              <input className="cmd-input" type="number" min="1" max="365" value={newKey.expires_in_days} onChange={(e) => setNewKey({ ...newKey, expires_in_days: parseInt(e.target.value) || 90 })} />
            </div>
            <div className="form-field" style={{ display: "flex", alignItems: "flex-end" }}>
              <button className="cmd-btn primary" onClick={handleCreate} disabled={creating || !newKey.name}>
                {creating ? "Creating..." : "Generate Key"}
              </button>
            </div>
          </div>
        </div>
      )}

      <table className="data-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Prefix</th>
            <th>Role</th>
            <th>Created</th>
            <th>Expires</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {keyList.map((k) => (
            <tr key={k.key_id}>
              <td>{k.name}</td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--accent-cyan)" }}>{k.key_prefix}</td>
              <td><RoleBadge role={k.role} /></td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {k.created_at ? new Date(k.created_at).toLocaleDateString() : "---"}
              </td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "---"}
              </td>
              <td>
                <span className={`badge ${k.active ? "approved" : "rejected"}`}>
                  {k.active ? "Active" : "Revoked"}
                </span>
              </td>
              <td>
                {k.active && (
                  <button className="cmd-btn sm danger" onClick={() => handleRevoke(k.key_id)}>
                    Revoke
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────
// Audit Log Tab
// ──────────────────────────────────────────────

function AuditLogTab() {
  const [filters, setFilters] = useState({ limit: 50, action: "", user_id: "" });
  const params = new URLSearchParams();
  params.set("limit", filters.limit);
  if (filters.action) params.set("action", filters.action);
  if (filters.user_id) params.set("user_id", filters.user_id);

  const { data: logs } = useSWR(`/api/audit?${params.toString()}`, fetcher, { refreshInterval: 10000 });

  const handleExport = async () => {
    try {
      const resp = await fetch("/api/admin/export?type=audit");
      if (resp.ok) {
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "audit_export.csv";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      // Error handled silently
    }
  };

  const entries = logs?.entries || [];

  return (
    <div>
      <div className="admin-filter-bar">
        <input
          className="cmd-input"
          style={{ width: 200 }}
          placeholder="Filter by user..."
          value={filters.user_id}
          onChange={(e) => setFilters({ ...filters, user_id: e.target.value })}
        />
        <input
          className="cmd-input"
          style={{ width: 200 }}
          placeholder="Filter by action..."
          value={filters.action}
          onChange={(e) => setFilters({ ...filters, action: e.target.value })}
        />
        <select className="cmd-select" value={filters.limit} onChange={(e) => setFilters({ ...filters, limit: parseInt(e.target.value) })}>
          <option value="25">25 entries</option>
          <option value="50">50 entries</option>
          <option value="100">100 entries</option>
          <option value="200">200 entries</option>
        </select>
        <button className="cmd-btn sm" onClick={handleExport}>Export CSV</button>
      </div>

      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", marginBottom: 12 }}>
        {logs?.total ?? 0} total entries
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>User</th>
            <th>Role</th>
            <th>Action</th>
            <th>Resource</th>
            <th>Method</th>
            <th>Status</th>
            <th>Duration</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
                {e.timestamp ? new Date(e.timestamp).toLocaleString() : "---"}
              </td>
              <td style={{ color: "var(--accent-cyan)" }}>{e.user_id}</td>
              <td><RoleBadge role={e.user_role} /></td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{e.action}</td>
              <td style={{ color: "var(--text-muted)", fontSize: 11 }}>
                {e.resource_type}{e.resource_id ? `/${e.resource_id.substring(0, 8)}` : ""}
              </td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>{e.method}</td>
              <td>
                <span className={`badge ${e.status_code < 400 ? "approved" : e.status_code < 500 ? "draft" : "rejected"}`}>
                  {e.status_code || "---"}
                </span>
              </td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {e.duration_ms ? `${e.duration_ms.toFixed(0)}ms` : "---"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────
// System Config Tab
// ──────────────────────────────────────────────

function SystemConfigTab() {
  const { data: config, mutate } = useSWR("/api/admin/config", fetcher, { refreshInterval: 30000 });
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!newKey.trim()) return;
    setSaving(true);
    try {
      await fetch("/api/admin/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [newKey]: newValue }),
      });
      setNewKey("");
      setNewValue("");
      mutate();
    } catch {
      // Error handled silently
    }
    setSaving(false);
  };

  const entries = config ? Object.entries(config) : [];

  return (
    <div>
      <div className="admin-form-card" style={{ marginBottom: 16 }}>
        <div className="admin-form-grid" style={{ gridTemplateColumns: "1fr 2fr auto" }}>
          <div className="form-field">
            <label>Key</label>
            <input className="cmd-input" value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="config.key" />
          </div>
          <div className="form-field">
            <label>Value</label>
            <input className="cmd-input" value={newValue} onChange={(e) => setNewValue(e.target.value)} placeholder="value" />
          </div>
          <div className="form-field" style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="cmd-btn primary" onClick={handleSave} disabled={saving || !newKey.trim()}>
              {saving ? "Saving..." : "Set"}
            </button>
          </div>
        </div>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Key</th>
            <th>Value</th>
            <th>Updated</th>
            <th>Updated By</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, info]) => (
            <tr key={key}>
              <td style={{ fontFamily: "var(--font-mono)", color: "var(--accent-cyan)" }}>{key}</td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{info.value}</td>
              <td style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                {info.updated_at ? new Date(info.updated_at).toLocaleString() : "---"}
              </td>
              <td style={{ color: "var(--text-muted)" }}>{info.updated_by}</td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={4} style={{ textAlign: "center", padding: 30, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                No configuration entries. Add one above.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// ──────────────────────────────────────────────
// Bulk Operations Tab
// ──────────────────────────────────────────────

function BulkOpsTab() {
  const [objectives, setObjectives] = useState("");
  const [mode, setMode] = useState("publish");
  const [dispatching, setDispatching] = useState(false);
  const [results, setResults] = useState(null);

  const handleBulkDispatch = async () => {
    const lines = objectives.split("\n").map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return;

    setDispatching(true);
    try {
      const resp = await fetch("/api/admin/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: "tasks", objectives: lines, mode }),
      });
      const data = await resp.json();
      setResults(data);
    } catch (e) {
      setResults({ error: e.message });
    }
    setDispatching(false);
  };

  return (
    <div>
      <Panel title="Bulk Task Dispatch" dot="info">
        <div style={{ marginBottom: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)" }}>
          Enter one task objective per line (max 50)
        </div>
        <textarea
          className="cmd-input"
          style={{ width: "100%", minHeight: 120, resize: "vertical", fontFamily: "var(--font-mono)", fontSize: 12 }}
          placeholder={"Analyze Q3 revenue trends\nGenerate API documentation for billing service\nReview security audit findings"}
          value={objectives}
          onChange={(e) => setObjectives(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <select className="cmd-select" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="publish">Publish Only</option>
            <option value="full">Full Autonomous</option>
          </select>
          <button
            className="cmd-btn primary"
            onClick={handleBulkDispatch}
            disabled={dispatching || !objectives.trim()}
          >
            {dispatching ? "Dispatching..." : `Dispatch ${objectives.split("\n").filter((l) => l.trim()).length} Tasks`}
          </button>
        </div>
      </Panel>

      {results && (
        <Panel title="Bulk Results" dot={results.error ? "error" : "success"} style={{ marginTop: 16 }}>
          {results.error ? (
            <div style={{ color: "var(--accent-red)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
              Error: {results.error}
            </div>
          ) : (
            <div>
              <div className="admin-summary-bar" style={{ marginBottom: 12 }}>
                <div className="admin-summary-item">
                  <span className="admin-summary-label">Total</span>
                  <span className="admin-summary-value">{results.total}</span>
                </div>
                <div className="admin-summary-item">
                  <span className="admin-summary-label">Dispatched</span>
                  <span className="admin-summary-value green">{results.dispatched}</span>
                </div>
                <div className="admin-summary-item">
                  <span className="admin-summary-label">Failed</span>
                  <span className="admin-summary-value red">{results.failed}</span>
                </div>
              </div>
              <div style={{ maxHeight: 200, overflow: "auto" }}>
                {results.results?.map((r, i) => (
                  <div key={i} className="activity-item">
                    <span className={`badge ${r.status === "error" ? "rejected" : "approved"}`} style={{ fontSize: 10 }}>
                      {r.status}
                    </span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", marginLeft: 8 }}>
                      {r.objective}
                    </span>
                    {r.task_id && (
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-cyan)", marginLeft: 8 }}>
                        {r.task_id.substring(0, 10)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────
// Main Admin Page
// ──────────────────────────────────────────────

const TABS = [
  { id: "health", label: "System Health", icon: "◉" },
  { id: "users", label: "Users & RBAC", icon: "▣" },
  { id: "apikeys", label: "API Keys", icon: "◇" },
  { id: "audit", label: "Audit Log", icon: "◎" },
  { id: "config", label: "Configuration", icon: "■" },
  { id: "bulk", label: "Bulk Operations", icon: "▶" },
];

export default function AdminConsole() {
  const [activeTab, setActiveTab] = useState("health");

  return (
    <div>
      <div className="admin-header">
        <h1 className="admin-title">Enterprise Admin Console</h1>
        <span className="admin-subtitle">System management, access control, and compliance</span>
      </div>

      <TabBar tabs={TABS} active={activeTab} onChange={setActiveTab} />

      <div className="admin-content">
        {activeTab === "health" && <SystemHealthTab />}
        {activeTab === "users" && <UsersTab />}
        {activeTab === "apikeys" && <APIKeysTab />}
        {activeTab === "audit" && <AuditLogTab />}
        {activeTab === "config" && <SystemConfigTab />}
        {activeTab === "bulk" && <BulkOpsTab />}
      </div>
    </div>
  );
}
