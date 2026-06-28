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

function ThreadModal({ msg, onClose }) {
  const [messages, setMessages] = useState(null);
  const [loading, setLoading] = useState(true);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [autoReplying, setAutoReplying] = useState(false);

  const loadThread = async () => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/thread/${msg.thread_id}`);
      const data = await resp.json();
      setMessages(data.messages || []);
    } catch (e) {
      setMessages([]);
    }
    setLoading(false);
  };

  useState(() => { loadThread(); }, []);

  const sendReply = async () => {
    if (!replyText.trim()) return;
    setSending(true);
    try {
      await fetch(`/api/thread/${msg.thread_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: replyText }),
      });
      setReplyText("");
      await loadThread();
    } catch (e) {
      alert("Failed to send: " + e.message);
    }
    setSending(false);
  };

  const triggerAutoReply = async () => {
    setAutoReplying(true);
    try {
      await fetch("/api/auto-reply/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: msg.thread_id }),
      });
      setTimeout(loadThread, 3000);
    } catch (e) {
      alert("Auto-reply failed: " + e.message);
    }
    setAutoReplying(false);
  };

  const freelancerUserId = null; // Will match from API

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 600, maxHeight: "80vh", display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-cyan)", fontWeight: 600 }}>
            <span className="dot info" /> Thread with {msg.sender || "Unknown"}
          </div>
          <button className="cmd-btn sm" onClick={onClose}>Close</button>
        </div>

        {msg.prospect && (
          <div style={{ padding: "8px 12px", marginBottom: 12, background: "var(--bg-input)", borderRadius: 4, border: "1px solid var(--border)" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-primary)", fontWeight: 600 }}>{msg.prospect.title}</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
              Status: <span className={`badge ${msg.prospect.status}`} style={{ fontSize: 9, padding: "1px 6px" }}>{msg.prospect.status}</span>
              {msg.prospect.quoted_price > 0 && ` // Bid: $${msg.prospect.quoted_price}`}
            </div>
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", marginBottom: 12, padding: "8px 0" }}>
          {loading && <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", textAlign: "center", padding: 20 }}>Loading messages...</div>}
          {messages && messages.length === 0 && <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-muted)", textAlign: "center", padding: 20 }}>No messages in thread.</div>}
          {messages && messages.map((m, i) => {
            const isOurs = m.from_user && String(m.from_user) === (typeof window !== "undefined" ? localStorage.getItem("freelancer_user_id") : "");
            return (
              <div key={m.id || i} style={{
                padding: "8px 12px", marginBottom: 6, borderRadius: 6,
                maxWidth: "85%",
                marginLeft: isOurs ? "auto" : 0,
                marginRight: isOurs ? 0 : "auto",
                background: isOurs ? "rgba(6,182,212,0.12)" : "var(--bg-input)",
                border: `1px solid ${isOurs ? "rgba(6,182,212,0.25)" : "var(--border)"}`,
              }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-primary)", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>
                  {m.message}
                </div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)", marginTop: 4 }}>
                  {m.time_created ? new Date(m.time_created * 1000).toLocaleString() : ""}
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
          <button className="cmd-btn sm" onClick={triggerAutoReply} disabled={autoReplying}>
            {autoReplying ? "..." : "Auto-Reply"}
          </button>
          <button className="cmd-btn sm" onClick={loadThread}>Refresh</button>
        </div>

        <div style={{ display: "flex", gap: 6 }}>
          <textarea
            value={replyText}
            onChange={(e) => setReplyText(e.target.value)}
            placeholder="Type a reply..."
            style={{
              flex: 1, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 11,
              background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: 4,
              color: "var(--text-primary)", resize: "none", minHeight: 40, maxHeight: 80,
            }}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendReply(); } }}
          />
          <button className="cmd-btn primary" onClick={sendReply} disabled={sending || !replyText.trim()}>
            {sending ? "..." : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function BidModal({ prospect, onClose, onBid }) {
  const [bidAmount, setBidAmount] = useState(prospect.quoted_price || prospect.budget_min || 50);
  const [period, setPeriod] = useState(7);
  const [proposal, setProposal] = useState("");
  const [generating, setGenerating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const generateProposal = async () => {
    setGenerating(true);
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
          tone: "professional",
        }),
      });
      const data = await resp.json();
      if (data.proposal) setProposal(data.proposal);
    } catch (e) {
      alert("Proposal generation failed: " + e.message);
    }
    setGenerating(false);
  };

  const submitBid = async () => {
    setSubmitting(true);
    try {
      const resp = await fetch("/api/bid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prospect_id: prospect.id,
          bid_amount: parseFloat(bidAmount),
          period: parseInt(period),
          milestone_percentage: 100,
          description: proposal,
        }),
      });
      const data = await resp.json();
      setResult(data);
      if (data.ok && onBid) onBid();
    } catch (e) {
      setResult({ error: e.message });
    }
    setSubmitting(false);
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 550 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-cyan)", fontWeight: 600 }}>
            <span className="dot info" /> Place Bid
          </div>
          <button className="cmd-btn sm" onClick={onClose}>Close</button>
        </div>

        <div style={{ padding: "8px 12px", marginBottom: 16, background: "var(--bg-input)", borderRadius: 4, border: "1px solid var(--border)" }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>{prospect.title}</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
            {prospect.platform?.toUpperCase()} // Budget: ${prospect.budget_min || 0} - ${prospect.budget_max || 0}
          </div>
        </div>

        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <label style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>BID AMOUNT ($)</label>
            <input type="number" value={bidAmount} onChange={(e) => setBidAmount(e.target.value)}
              style={{ width: "100%", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 12, background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-primary)" }}
            />
          </div>
          <div style={{ flex: 1 }}>
            <label style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", display: "block", marginBottom: 4 }}>PERIOD (DAYS)</label>
            <input type="number" value={period} onChange={(e) => setPeriod(e.target.value)}
              style={{ width: "100%", padding: "6px 10px", fontFamily: "var(--font-mono)", fontSize: 12, background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: 4, color: "var(--text-primary)" }}
            />
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
            <label style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>PROPOSAL</label>
            <button className="cmd-btn sm" onClick={generateProposal} disabled={generating}>
              {generating ? "Generating..." : "AI Generate"}
            </button>
          </div>
          <textarea value={proposal} onChange={(e) => setProposal(e.target.value)}
            placeholder="Write your proposal or click AI Generate..."
            style={{
              width: "100%", minHeight: 120, padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 11,
              background: "var(--bg-input)", border: "1px solid var(--border)", borderRadius: 4,
              color: "var(--text-primary)", resize: "vertical", lineHeight: 1.6,
            }}
          />
        </div>

        {result && (
          <div style={{
            padding: "8px 12px", marginBottom: 12, borderRadius: 4, fontFamily: "var(--font-mono)", fontSize: 11,
            background: result.error ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)",
            border: `1px solid ${result.error ? "rgba(239,68,68,0.3)" : "rgba(16,185,129,0.3)"}`,
            color: result.error ? "#f87171" : "#34d399",
          }}>
            {result.error ? `ERR: ${result.error}` : `BID PLACED // ID: ${result.bid_id || "OK"}`}
          </div>
        )}

        <button className="cmd-btn primary" onClick={submitBid} disabled={submitting || !proposal.trim()}>
          {submitting ? "Submitting..." : `Submit Bid — $${bidAmount}`}
        </button>
      </div>
    </div>
  );
}

export default function ProspectsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState(null);
  const [proposalTarget, setProposalTarget] = useState(null);
  const [threadTarget, setThreadTarget] = useState(null);
  const [bidTarget, setBidTarget] = useState(null);

  const { data: prospects, mutate } = useSWR("/api/prospects" + (statusFilter ? `?status=${statusFilter}` : ""), fetcher, { refreshInterval: 10000 });
  const { data: stats } = useSWR("/api/prospects/stats", fetcher, { refreshInterval: 15000 });
  const { data: platforms } = useSWR("/api/prospects/platforms", fetcher);
  const { data: scanState } = useSWR("/api/scan", fetcher, { refreshInterval: 30000 });
  const { data: messages } = useSWR("/api/messages?limit=10", fetcher, { refreshInterval: 30000 });
  const { data: autoReply } = useSWR("/api/auto-reply", fetcher, { refreshInterval: 15000 });

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

  const statusFilters = ["", "discovered", "approved", "applied", "rejected", "hired", "executing", "delivered", "paid"];

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

      {autoReply && (
        <div style={{ padding: "6px 14px", marginBottom: 12, borderRadius: 4, background: autoReply.enabled ? "rgba(16,185,129,0.05)" : "rgba(239,68,68,0.05)", border: `1px solid ${autoReply.enabled ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)"}`, fontFamily: "var(--font-mono)", fontSize: 10, color: autoReply.enabled ? "#34d399" : "#f87171", display: "flex", justifyContent: "space-between" }}>
          <span>AUTO-REPLY: {autoReply.enabled ? "ON" : "OFF"} // DELAY: {autoReply.delay_seconds}s // LIMIT: {autoReply.max_per_thread_hour}/hr // TELEGRAM: {autoReply.telegram_commands ? "ON" : "OFF"}</span>
          <span>PENDING: {autoReply.pending_replies} // THREADS: {autoReply.active_threads} // RATE-LIMITED: {autoReply.rate_limited_threads}</span>
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
        <div className="metric blue"><div className="metric-label">Applied</div><div className="metric-value">{stats?.by_status?.applied ?? 0}</div></div>
        <div className="metric red"><div className="metric-label">Rejected</div><div className="metric-value">{stats?.by_status?.rejected ?? 0}</div></div>
        <div className="metric blue"><div className="metric-label">Executing</div><div className="metric-value">{stats?.by_status?.executing ?? 0}</div></div>
        <div className="metric green"><div className="metric-label">Delivered</div><div className="metric-value">{stats?.by_status?.delivered ?? 0}</div></div>
        <div className="metric green"><div className="metric-label">Hired</div><div className="metric-value">{stats?.by_status?.hired ?? 0}</div></div>
        <div className="metric green"><div className="metric-label">Paid</div><div className="metric-value">{stats?.by_status?.paid ?? 0}</div></div>
        <div className="metric amber"><div className="metric-label">Revenue</div><div className="metric-value">${stats?.revenue ?? 0}</div></div>
      </div>

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {statusFilters.map((s) => (
          <button key={s || "all"} onClick={() => setStatusFilter(s)} className={`cmd-btn sm ${statusFilter === s ? "active" : ""}`}>
            {s || "All"}
          </button>
        ))}
      </div>

      {messages?.messages?.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--accent-cyan)", fontWeight: 600, marginBottom: 10, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            <span className="dot info" /> Freelancer Messages ({messages.count})
          </div>
          {messages.messages.map((msg) => (
            <div key={msg.thread_id} onClick={() => setThreadTarget(msg)} style={{
              padding: "10px 14px", marginBottom: 6, borderRadius: 4, cursor: "pointer",
              background: msg.is_read ? "var(--bg-input)" : "rgba(6,182,212,0.08)",
              border: `1px solid ${msg.is_read ? "var(--border)" : "rgba(6,182,212,0.25)"}`,
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>
                  {msg.sender || "Unknown"} {!msg.is_read && <span style={{ color: "var(--accent-cyan)", fontSize: 10 }}>NEW</span>}
                </span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                  {msg.last_message_time ? new Date(msg.last_message_time * 1000).toLocaleString() : ""}
                </span>
              </div>
              {msg.prospect && (
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--accent-cyan)", marginBottom: 4 }}>
                  {msg.prospect.title} // <span className={`badge ${msg.prospect.status}`} style={{ fontSize: 9, padding: "1px 6px" }}>{msg.prospect.status}</span>
                </div>
              )}
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-secondary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {msg.last_message || "(no preview)"}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="panel">
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Platform</th>
              <th>Budget</th>
              <th>Bid</th>
              <th>Status</th>
              <th>Applied</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {prospects && prospects.length > 0 ? prospects.map((p) => (
              <tr key={p.id}>
                <td style={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-primary)", fontWeight: 500 }}>
                  {p.url ? <a href={p.url} target="_blank" rel="noopener noreferrer" style={{ color: "inherit", textDecoration: "none" }}>{p.title}</a> : p.title}
                </td>
                <td style={{ textTransform: "uppercase", fontSize: 10 }}>{p.platform}</td>
                <td>{p.budget_max > 0 ? `$${p.budget_min}-$${p.budget_max}` : "---"}</td>
                <td style={{ fontSize: 11, color: "var(--accent-cyan)" }}>{p.quoted_price > 0 ? `$${p.quoted_price}` : "---"}</td>
                <td><span className={`badge ${p.status}`}>{p.status}</span></td>
                <td style={{ fontSize: 10 }}>{p.applied_at ? new Date(p.applied_at).toLocaleDateString() : "---"}</td>
                <td style={{ display: "flex", gap: 4 }}>
                  <button className="cmd-btn sm" onClick={() => setProposalTarget(p)}>Propose</button>
                  <button className="cmd-btn sm primary" onClick={() => setBidTarget(p)}>Bid</button>
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  No prospects. Initiate scan to discover opportunities.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {proposalTarget && <ProposalModal prospect={proposalTarget} onClose={() => setProposalTarget(null)} />}
      {threadTarget && <ThreadModal msg={threadTarget} onClose={() => setThreadTarget(null)} />}
      {bidTarget && <BidModal prospect={bidTarget} onClose={() => setBidTarget(null)} onBid={() => { setBidTarget(null); mutate(); }} />}
    </div>
  );
}
