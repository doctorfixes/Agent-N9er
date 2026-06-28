"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json()).catch(() => null);

function ProposalModal({ prospect, onClose }) {
  const [proposal, setProposal] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tone, setTone] = useState("professional");

  const generate = async () => {
    setLoading(true);
    try {
      const resp = await fetch("/api/proposals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prospect_id: prospect.id,
          title: prospect.title,
          description: prospect.description || "",
          platform: prospect.platform,
          budget_max: prospect.budget_max || 0,
          skills: prospect.skills || "",
          tone,
        }),
      });
      setProposal(await resp.json());
    } catch (e) {
      setProposal({ error: e.message });
    }
    setLoading(false);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div className="panel-title" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-cyan)" }}>
            <span className="dot info" /> Generate Proposal
          </div>
          <button className="cmd-btn sm" onClick={onClose}>Close</button>
        </div>
        <div style={{ marginBottom: 16, padding: "10px 14px", background: "var(--bg-input)", borderRadius: 4, border: "1px solid var(--border)" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: "var(--text-primary)", marginBottom: 4 }}>{prospect.title}</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
            {prospect.platform?.toUpperCase()} {prospect.budget_max > 0 && `// BUDGET: $${prospect.budget_max}`}
          </div>
        </div>
        <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
          {["professional", "friendly", "technical", "concise"].map((t) => (
            <button key={t} className={`cmd-btn sm ${tone === t ? "active" : ""}`} onClick={() => setTone(t)}>{t}</button>
          ))}
        </div>
        <button className="cmd-btn primary" onClick={generate} disabled={loading}>
          {loading ? "Generating..." : "Generate"}
        </button>
        {proposal && !proposal.error && (
          <div style={{ marginTop: 16 }}>
            <div style={{ background: "var(--bg-input)", padding: 16, borderRadius: 4, border: "1px solid var(--border)", whiteSpace: "pre-wrap", fontSize: 12, fontFamily: "var(--font-mono)", lineHeight: 1.7, color: "var(--text-secondary)" }}>
              {proposal.proposal}
            </div>
            <div style={{ marginTop: 8, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
              MODE: {proposal.mode?.toUpperCase()}
            </div>
          </div>
        )}
        {proposal?.error && (
          <div style={{ marginTop: 16, padding: 12, background: "rgba(239,68,68,0.1)", borderRadius: 4, border: "1px solid rgba(239,68,68,0.3)", color: "#f87171", fontFamily: "var(--font-mono)", fontSize: 12 }}>
            ERR: {proposal.error}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ProspectsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [proposalTarget, setProposalTarget] = useState(null);

  const { data: prospects, mutate } = useSWR("/api/prospects" + (statusFilter ? `?status=${statusFilter}` : ""), fetcher, { refreshInterval: 10000 });
  const { data: stats } = useSWR("/api/prospects/stats", fetcher, { refreshInterval: 15000 });
  const { data: platforms } = useSWR("/api/prospects/platforms", fetcher);
  const { data: scanState } = useSWR("/api/scan", fetcher, { refreshInterval: 30000 });

  const handleScan = async (platform) => {
    setScanning(true);
    setScanResult(null);
    try {
      const resp = await fetch("/api/prospects/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform }),
      });
      setScanResult(await resp.json());
      mutate();
    } catch (e) {
      setScanResult({ error: e.message });
    }
    setScanning(false);
  };

  const handleFullScan = async () => {
    setScanning(true);
    setScanResult(null);
    try {
      const resp = await fetch("/api/scan", { method: "POST" });
      const data = await resp.json();
      const results = data.results || {};
      setScanResult({
        discovered: Object.values(results).reduce((s, r) => s + (r.discovered || 0), 0),
        new: Object.values(results).reduce((s, r) => s + (r.new || 0), 0),
        full: true,
      });
      mutate();
    } catch (e) {
      setScanResult({ error: e.message });
    }
    setScanning(false);
  };

  const statusFilters = ["", "discovered", "approved", "applied", "hired", "executing", "delivered", "paid"];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Prospect Pipeline
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select id="platform-select" defaultValue="upwork" className="cmd-select">
            {platforms && platforms.map((p) => (
              <option key={p.name} value={p.name}>{p.label}</option>
            ))}
            {!platforms && <option value="upwork">Upwork</option>}
          </select>
          <button className="cmd-btn primary" onClick={() => handleScan(document.getElementById("platform-select").value)} disabled={scanning}>
            {scanning ? ">>>" : "Scan"}
          </button>
          <button className="cmd-btn success" onClick={handleFullScan} disabled={scanning}>
            {scanning ? "..." : "Full Scan"}
          </button>
        </div>
      </div>

      {scanState && (
        <div style={{ padding: "6px 14px", marginBottom: 12, borderRadius: 4, background: "rgba(6,182,212,0.05)", border: "1px solid rgba(6,182,212,0.15)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-cyan)", display: "flex", justifyContent: "space-between" }}>
          <span>AUTO-SCAN: {scanState.auto_scan_enabled ? "ON" : "OFF"} // SCANS: {scanState.total_scans} // DISCOVERED: {scanState.total_discovered}</span>
          {scanState.last_scan_at && <span>LAST: {new Date(scanState.last_scan_at).toLocaleString()}</span>}
        </div>
      )}

      {scanResult && (
        <div style={{
          padding: "10px 14px", marginBottom: 12, borderRadius: 4, fontFamily: "var(--font-mono)", fontSize: 12,
          background: scanResult.error ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)",
          border: `1px solid ${scanResult.error ? "rgba(239,68,68,0.3)" : "rgba(16,185,129,0.3)"}`,
          color: scanResult.error ? "#f87171" : "#34d399",
        }}>
          {scanResult.error ? `ERR: ${scanResult.error}` : `FOUND ${scanResult.discovered} // NEW ${scanResult.new}${scanResult.full ? " // FULL SCAN" : ""}`}
        </div>
      )}

      <div className="metric-grid" style={{ marginBottom: 16 }}>
        <div className="metric cyan"><div className="metric-label">Total</div><div className="metric-value">{stats?.total_prospects ?? 0}</div></div>
        <div className="metric green"><div className="metric-label">Approved</div><div className="metric-value">{stats?.by_status?.approved ?? 0}</div></div>
        <div className="metric blue"><div className="metric-label">Executing</div><div className="metric-value">{stats?.by_status?.executing ?? 0}</div></div>
        <div className="metric green"><div className="metric-label">Delivered</div><div className="metric-value">{stats?.by_status?.delivered ?? 0}</div></div>
        <div className="metric amber"><div className="metric-label">Revenue</div><div className="metric-value">${stats?.revenue ?? 0}</div></div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {statusFilters.map((s) => (
          <button key={s || "all"} onClick={() => setStatusFilter(s)} className={`cmd-btn sm ${statusFilter === s ? "active" : ""}`}>
            {s || "All"}
          </button>
        ))}
      </div>

      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Platform</th>
              <th>Budget</th>
              <th>Status</th>
              <th>Discovered</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {prospects && prospects.length > 0 ? prospects.map((p) => (
              <tr key={p.id}>
                <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-primary)", fontWeight: 500 }}>{p.title}</td>
                <td style={{ textTransform: "uppercase", fontSize: 10 }}>{p.platform}</td>
                <td>{p.budget_max > 0 ? `$${p.budget_min}-$${p.budget_max}` : "---"}</td>
                <td><span className={`badge ${p.status}`}>{p.status}</span></td>
                <td style={{ fontSize: 10 }}>{p.discovered_at ? new Date(p.discovered_at).toLocaleDateString() : "---"}</td>
                <td>
                  <button className="cmd-btn sm" onClick={() => setProposalTarget(p)}>Propose</button>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={6} style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  No prospects. Initiate scan to discover opportunities.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {proposalTarget && <ProposalModal prospect={proposalTarget} onClose={() => setProposalTarget(null)} />}
    </div>
  );
}
