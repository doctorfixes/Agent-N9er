"use client";

import { useState, useRef, useEffect } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => { if (!r.ok) return null; return r.json(); }).catch(() => null);

export default function ChatPage() {
  const [selectedProspect, setSelectedProspect] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [generating, setGenerating] = useState(false);
  const [quoteAmount, setQuoteAmount] = useState("");
  const [statusFilter, setStatusFilter] = useState("applied");
  const chatEndRef = useRef(null);

  const { data: prospects } = useSWR(
    `/api/prospects?status=${statusFilter}`,
    fetcher,
    { refreshInterval: 15000 }
  );

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const selectProspect = (p) => {
    setSelectedProspect(p);
    setMessages([{
      role: "system",
      content: `Loaded prospect: ${p.title}\nPlatform: ${p.platform}\nBudget: $${p.budget_min}-$${p.budget_max}\nSkills: ${p.skills || "N/A"}`,
      time: new Date().toLocaleTimeString("en-US", { hour12: false }),
    }]);
    setQuoteAmount(p.budget_min > 0 ? String(p.budget_min) : "");
  };

  const generateQuote = async () => {
    if (!selectedProspect) return;
    setGenerating(true);

    const userMsg = input.trim();
    if (userMsg) {
      setMessages((prev) => [...prev, {
        role: "user",
        content: userMsg,
        time: new Date().toLocaleTimeString("en-US", { hour12: false }),
      }]);
    }

    try {
      const resp = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prospect_id: selectedProspect.id,
          title: selectedProspect.title,
          description: selectedProspect.description || "",
          platform: selectedProspect.platform,
          budget_min: selectedProspect.budget_min || 0,
          budget_max: selectedProspect.budget_max || 0,
          skills: selectedProspect.skills || "",
          client_message: userMsg,
          conversation: messages.filter((m) => m.role !== "system").map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });

      const text = await resp.text();
      let data;
      try { data = JSON.parse(text); } catch { data = { error: text || `Service returned ${resp.status}` }; }

      if (data.error) {
        setMessages((prev) => [...prev, {
          role: "error",
          content: data.error,
          time: new Date().toLocaleTimeString("en-US", { hour12: false }),
        }]);
      } else {
        setMessages((prev) => [...prev, {
          role: "assistant",
          content: data.reply,
          time: new Date().toLocaleTimeString("en-US", { hour12: false }),
          meta: `${data.mode} // ${data.model || "sim"} // $${data.cost_usd?.toFixed(4) || "0"} // ${data.tokens || 0} tokens`,
        }]);
      }
    } catch (e) {
      setMessages((prev) => [...prev, {
        role: "error",
        content: e.message,
        time: new Date().toLocaleTimeString("en-US", { hour12: false }),
      }]);
    }

    setInput("");
    setGenerating(false);
  };

  const copyLastReply = () => {
    const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
    if (lastAssistant) {
      navigator.clipboard.writeText(lastAssistant.content);
    }
  };

  const submitBid = async () => {
    if (!selectedProspect || !quoteAmount) return;
    const lastReply = [...messages].reverse().find((m) => m.role === "assistant");
    setGenerating(true);
    try {
      const resp = await fetch("/api/prospects/bid", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prospect_id: selectedProspect.id,
          amount: parseFloat(quoteAmount),
          period: 7,
          description: lastReply?.content || "",
        }),
      });
      const text = await resp.text();
      let data;
      try { data = JSON.parse(text); } catch { data = { error: text || `Service returned ${resp.status}` }; }

      if (data.error || data.detail) {
        setMessages((prev) => [...prev, {
          role: "error",
          content: data.error || data.detail,
          time: new Date().toLocaleTimeString("en-US", { hour12: false }),
        }]);
      } else {
        const statusLabel = data.status === "pending_approval"
          ? `Bid pending approval (ID: ${data.bid_id?.substring(0, 8)}). Approve via Prospects page.`
          : `Bid submitted: $${data.amount} on project ${data.project_id}`;
        setMessages((prev) => [...prev, {
          role: "system",
          content: statusLabel,
          time: new Date().toLocaleTimeString("en-US", { hour12: false }),
        }]);
      }
    } catch (e) {
      setMessages((prev) => [...prev, {
        role: "error",
        content: `Bid submission failed: ${e.message}`,
        time: new Date().toLocaleTimeString("en-US", { hour12: false }),
      }]);
    }
    setGenerating(false);
  };

  const updateProspectStatus = async (status) => {
    if (!selectedProspect) return;
    try {
      const resp = await fetch(`/api/prospects/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prospect_id: selectedProspect.id, status }),
      });
      if (resp.ok) {
        setMessages((prev) => [...prev, {
          role: "system",
          content: `Prospect status updated to: ${status}`,
          time: new Date().toLocaleTimeString("en-US", { hour12: false }),
        }]);
      }
    } catch (e) {
      setMessages((prev) => [...prev, {
        role: "error",
        content: `Status update failed: ${e.message}`,
        time: new Date().toLocaleTimeString("en-US", { hour12: false }),
      }]);
    }
  };

  const prospectList = Array.isArray(prospects) ? prospects : [];

  return (
    <div style={{ display: "flex", gap: 16, height: "calc(100vh - 120px)" }}>
      <div style={{ width: 320, flexShrink: 0, display: "flex", flexDirection: "column" }}>
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
            Prospect Chat
          </div>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {["applied", "executing", "hired", "discovered", "approved"].map((s) => (
              <button key={s} onClick={() => setStatusFilter(s)} className={`cmd-btn sm ${statusFilter === s ? "active" : ""}`}>
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="panel" style={{ flex: 1, overflow: "auto" }}>
          {prospectList.length > 0 ? prospectList.map((p) => (
            <div
              key={p.id}
              onClick={() => selectProspect(p)}
              style={{
                padding: "10px 12px",
                borderBottom: "1px solid rgba(30,45,74,0.3)",
                cursor: "pointer",
                background: selectedProspect?.id === p.id ? "rgba(6,182,212,0.08)" : "transparent",
                borderLeft: selectedProspect?.id === p.id ? "2px solid var(--accent-cyan)" : "2px solid transparent",
              }}
            >
              <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600, color: "var(--text-primary)", marginBottom: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {p.title}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
                <span style={{ textTransform: "uppercase" }}>{p.platform}</span>
                <span>{p.budget_max > 0 ? `$${p.budget_min}-$${p.budget_max}` : "---"}</span>
              </div>
            </div>
          )) : (
            <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              No prospects with status "{statusFilter}"
            </div>
          )}
        </div>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {selectedProspect ? (
          <>
            <div style={{ padding: "10px 14px", background: "var(--bg-card)", borderRadius: "4px 4px 0 0", border: "1px solid var(--border)", borderBottom: "none", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, color: "var(--text-primary)" }}>
                  {selectedProspect.title}
                </div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", marginTop: 2 }}>
                  {selectedProspect.platform?.toUpperCase()} // BUDGET: ${selectedProspect.budget_min}-${selectedProspect.budget_max} // STATUS: {selectedProspect.status?.toUpperCase()}
                </div>
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                <button className="cmd-btn sm" onClick={copyLastReply}>Copy Reply</button>
                <button className="cmd-btn sm success" onClick={() => updateProspectStatus("hired")}>Mark Hired</button>
                <button className="cmd-btn sm" onClick={() => updateProspectStatus("rejected")} style={{ color: "var(--accent-red)" }}>Reject</button>
              </div>
            </div>

            <div className="panel" style={{ flex: 1, overflow: "auto", borderRadius: "0", margin: 0, borderTop: "none" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: 12 }}>
                {messages.map((msg, i) => (
                  <div key={i} style={{
                    alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                    maxWidth: "80%",
                  }}>
                    <div style={{
                      padding: "10px 14px",
                      borderRadius: 6,
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      lineHeight: 1.6,
                      whiteSpace: "pre-wrap",
                      background: msg.role === "user"
                        ? "rgba(6,182,212,0.12)"
                        : msg.role === "error"
                          ? "rgba(239,68,68,0.1)"
                          : msg.role === "system"
                            ? "rgba(100,116,139,0.08)"
                            : "rgba(16,185,129,0.08)",
                      border: `1px solid ${
                        msg.role === "user"
                          ? "rgba(6,182,212,0.25)"
                          : msg.role === "error"
                            ? "rgba(239,68,68,0.25)"
                            : msg.role === "system"
                              ? "rgba(100,116,139,0.15)"
                              : "rgba(16,185,129,0.25)"
                      }`,
                      color: msg.role === "error"
                        ? "#f87171"
                        : msg.role === "system"
                          ? "var(--text-muted)"
                          : "var(--text-secondary)",
                    }}>
                      {msg.content}
                    </div>
                    <div style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--text-muted)", marginTop: 3, textAlign: msg.role === "user" ? "right" : "left" }}>
                      {msg.time} {msg.role === "assistant" && msg.meta && `// ${msg.meta}`}
                    </div>
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
            </div>

            <div style={{ padding: 12, background: "var(--bg-card)", borderRadius: "0 0 4px 4px", border: "1px solid var(--border)", borderTop: "none" }}>
              <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
                  <span>QUOTE $</span>
                  <input
                    className="cmd-input"
                    style={{ width: 80 }}
                    placeholder="amount"
                    value={quoteAmount}
                    onChange={(e) => setQuoteAmount(e.target.value)}
                  />
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  className="cmd-input"
                  style={{ flex: 1 }}
                  placeholder="Type client message or context for quote generation..."
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !generating && generateQuote()}
                />
                <button className="cmd-btn primary" onClick={generateQuote} disabled={generating}>
                  {generating ? ">>>" : "Generate Quote"}
                </button>
                <button className="cmd-btn success" onClick={submitBid} disabled={generating || !quoteAmount}>
                  Submit Bid
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="panel" style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div style={{ textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
              Select a prospect from the list to start a conversation.
              <br /><br />
              <span style={{ fontSize: 10 }}>
                Generate quotes, respond to clients, and manage prospect status.
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
