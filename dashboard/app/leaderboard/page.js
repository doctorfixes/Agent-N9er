"use client";

import { useState, useEffect, useRef } from "react";
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

function AgentCard({ agent }) {
  const stateColors = {
    idle: "var(--accent-green)",
    busy: "var(--accent-cyan)",
    evaluating: "var(--accent-blue)",
    error: "var(--accent-red)",
    offline: "var(--text-muted)",
  };
  const stateColor = stateColors[agent.state] || "var(--text-muted)";

  const caps = Array.isArray(agent.capabilities)
    ? agent.capabilities.slice(0, 4)
    : typeof agent.capabilities === "object"
      ? Object.keys(agent.capabilities).slice(0, 4)
      : [];

  return (
    <div
      className="panel"
      style={{
        cursor: "default",
        transition: "border-color 0.2s",
        borderLeft: `3px solid ${stateColor}`,
      }}
    >
      <div className="panel-body" style={{ padding: "12px 14px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, fontWeight: 600, color: "var(--text-primary)" }}>
            {agent.agent_id?.substring(0, 14)}
          </span>
          <span
            className="badge"
            style={{
              background: `${stateColor}11`,
              color: stateColor,
              border: `1px solid ${stateColor}33`,
              fontSize: 9,
            }}
          >
            {agent.state}
          </span>
        </div>
        <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)", marginBottom: 6 }}>
          {agent.agent_type || "generic"} · ${agent.price_per_hour?.toFixed(2) || "0.00"}/hr
        </div>
        {caps.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {caps.map((c) => (
              <span
                key={c}
                style={{
                  fontSize: 9,
                  fontFamily: "var(--font-mono)",
                  color: "var(--accent-cyan)",
                  background: "rgba(6,182,212,0.08)",
                  border: "1px solid rgba(6,182,212,0.15)",
                  borderRadius: 3,
                  padding: "1px 6px",
                }}
              >
                {c}
              </span>
            ))}
            {agent.capabilities?.length > 4 && (
              <span style={{ fontSize: 9, color: "var(--text-muted)" }}>+{agent.capabilities.length - 4}</span>
            )}
          </div>
        )}
        {agent.last_heartbeat && (
          <div style={{ marginTop: 6, fontSize: 9, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            HB: {new Date(agent.last_heartbeat).toLocaleTimeString()}
          </div>
        )}
      </div>
    </div>
  );
}

function AgentFeedPanel({ events }) {
  const feedRef = useRef(null);
  const [paused, setPaused] = useState(false);
  const prevLength = useRef(0);

  useEffect(() => {
    if (!paused && feedRef.current && events.length > prevLength.current) {
      feedRef.current.scrollTop = 0;
    }
    prevLength.current = events.length;
  }, [events.length, paused]);

  const eventColor = (type) => {
    if (type === "agent_registered") return "var(--accent-green)";
    if (type === "agent_deregistered") return "var(--accent-red)";
    if (type === "agent_state_change") return "var(--accent-cyan)";
    if (type === "agent_load_change") return "var(--accent-amber)";
    if (type === "error") return "var(--accent-red)";
    return "var(--text-muted)";
  };

  const eventIcon = (type) => {
    if (type === "agent_registered") return "+";
    if (type === "agent_deregistered") return "✕";
    if (type === "agent_state_change") return "→";
    if (type === "agent_load_change") return "⚡";
    if (type === "error") return "!";
    return "•";
  };

  const formatEvent = (ev) => {
    switch (ev.type) {
      case "agent_registered":
        return `${ev.agent_id?.substring(0, 10)} registered [${ev.agent_type}] $${ev.price_per_hour?.toFixed(2)}/hr`;
      case "agent_deregistered":
        return `${ev.agent_id?.substring(0, 10)} deregistered`;
      case "agent_state_change":
        return `${ev.agent_id?.substring(0, 10)} ${ev.old_state} → ${ev.new_state}`;
      case "agent_load_change":
        return `${ev.agent_id?.substring(0, 10)} load: ${ev.load}`;
      case "snapshot":
        return `Snapshot: ${ev.agents?.length || 0} agents online`;
      case "error":
        return `ERR: ${ev.message}`;
      case "info":
        return ev.message;
      default:
        return ev.type;
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)" }}>
          {events.length} events
        </span>
        <button
          className={`cmd-btn sm ${paused ? "active" : ""}`}
          onClick={() => setPaused(!paused)}
        >
          {paused ? "▶ Live" : "❚❚ Pause"}
        </button>
      </div>
      <div
        ref={feedRef}
        style={{
          maxHeight: 560,
          overflow: "auto",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
        }}
      >
        {events.length === 0 ? (
          <div style={{ padding: 30, textAlign: "center", color: "var(--text-muted)" }}>
            Awaiting agent events...
          </div>
        ) : (
          events.slice(0, 200).map((ev, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                gap: 8,
                padding: "4px 0",
                borderBottom: "1px solid rgba(30,45,74,0.2)",
                animation: "fade-in 0.2s ease-out",
              }}
            >
              <span style={{ color: eventColor(ev.type), minWidth: 12 }}>{eventIcon(ev.type)}</span>
              <span style={{ color: "var(--text-muted)", minWidth: 48 }}>
                {ev.ts ? new Date(ev.ts).toLocaleTimeString("en-US", { hour12: false }) : ""}
              </span>
              <span style={{ color: "var(--text-secondary)" }}>{formatEvent(ev)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function LeaderboardPage() {
  const { data: agents } = useSWR("/api/agents", fetcher, { refreshInterval: 10000 });
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [filter, setFilter] = useState("all");
  const [sortBy, setSortBy] = useState("state");

  useEffect(() => {
    const es = new EventSource("/api/agent-feed");
    let buffer = [];

    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);

    es.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data);
        buffer.push(ev);
        if (buffer.length > 500) buffer = buffer.slice(-500);
        setEvents([...buffer]);
      } catch {}
    };

    return () => es.close();
  }, []);

  const agentList = agents
    ? Object.entries(agents).map(([id, a]) => ({ ...a, agent_id: id }))
    : [];

  const filtered = filter === "all" ? agentList : agentList.filter((a) => a.state === filter);
  const sorted = [...filtered].sort((a, b) => {
    if (sortBy === "state") {
      const order = { idle: 0, busy: 1, evaluating: 2, error: 3, offline: 4 };
      return (order[a.state] ?? 99) - (order[b.state] ?? 99);
    }
    if (sortBy === "price") return (b.price_per_hour || 0) - (a.price_per_hour || 0);
    if (sortBy === "name") return (a.agent_id || "").localeCompare(b.agent_id || "");
    return 0;
  });

  // State counts
  const counts = { idle: 0, busy: 0, evaluating: 0, error: 0, offline: 0 };
  for (const a of agentList) {
    counts[a.state] = (counts[a.state] || 0) + 1;
  }

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 16, fontWeight: 700, color: "var(--text-bright)", marginBottom: 4 }}>
          Agent Leaderboard
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)", display: "flex", gap: 16 }}>
          <span>Total: <strong style={{ color: "var(--text-primary)" }}>{agentList.length}</strong></span>
          <span>Idle: <strong style={{ color: "var(--accent-green)" }}>{counts.idle || 0}</strong></span>
          <span>Busy: <strong style={{ color: "var(--accent-cyan)" }}>{counts.busy || 0}</strong></span>
          <span>Evaluating: <strong style={{ color: "var(--accent-blue)" }}>{counts.evaluating || 0}</strong></span>
          <span>Error: <strong style={{ color: "var(--accent-red)" }}>{counts.error || 0}</strong></span>
        </div>
      </div>

      <div className="cmd-grid wide-layout" style={{ marginBottom: 16 }}>
        <Panel
          title="Agents"
          dot={connected ? "" : "warn"}
          actions={
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: connected ? "var(--accent-green)" : "var(--accent-red)",
                  boxShadow: connected ? "0 0 6px var(--accent-green)" : "0 0 6px var(--accent-red)",
                }}
              />
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--text-muted)" }}>
                {connected ? "LIVE" : "OFFLINE"}
              </span>
            </div>
          }
        >
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <select className="cmd-select" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ fontSize: 10, flex: 1, minWidth: 100 }}>
              <option value="all">All States</option>
              <option value="idle">Idle</option>
              <option value="busy">Busy</option>
              <option value="evaluating">Evaluating</option>
              <option value="error">Error</option>
              <option value="offline">Offline</option>
            </select>
            <select className="cmd-select" value={sortBy} onChange={(e) => setSortBy(e.target.value)} style={{ fontSize: 10, flex: 1, minWidth: 100 }}>
              <option value="state">Sort: State</option>
              <option value="price">Sort: Price</option>
              <option value="name">Sort: Name</option>
            </select>
          </div>
          <div className="cmd-grid cols-2" style={{ gap: 8 }}>
            {sorted.map((a) => (
              <AgentCard key={a.agent_id} agent={a} />
            ))}
          </div>
          {sorted.length === 0 && (
            <div style={{ textAlign: "center", padding: 20, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
              No agents{filter !== "all" ? ` with state "${filter}"` : ""} registered
            </div>
          )}
        </Panel>

        <Panel title="Agent Activity Feed" dot={connected ? "" : "warn"}>
          <AgentFeedPanel events={events} />
        </Panel>
      </div>
    </div>
  );
}