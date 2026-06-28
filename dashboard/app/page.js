"use client";

import { useState, useRef } from "react";
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

function Metric({ label, value, sub, color }) {
  return (
    <div className={`metric ${color || ""}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

function StatusDot({ status }) {
  const cls = status === "healthy" ? "online" : status === "degraded" ? "degraded" : "offline";
  return <span className={`status-dot ${cls}`} />;
}

export default function MissionControl() {
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState("full");
  const [taskResult, setTaskResult] = useState(null);
  const [dispatching, setDispatching] = useState(false);
  const [ruleObjective, setRuleObjective] = useState("");
  const [ruleCategory, setRuleCategory] = useState("uncategorized");
  const [activity, setActivity] = useState([]);
  const activityRef = useRef(activity);
  activityRef.current = activity;

  const { data: health } = useSWR("/api/health", fetcher, { refreshInterval: 15000 });
  const { data: tasks } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });
  const { data: rules, mutate: mutateRules } = useSWR("/api/recurring", fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR("/api/agents", fetcher, { refreshInterval: 10000 });
  const { data: analytics } = useSWR("/api/analytics?days=1", fetcher, { refreshInterval: 30000 });
  const { data: scanState } = useSWR("/api/scan", fetcher, { refreshInterval: 30000 });
  const { data: pipelineStats } = useSWR("/api/prospects/stats", fetcher, { refreshInterval: 10000 });
  const { data: messages } = useSWR("/api/messages?limit=5", fetcher, { refreshInterval: 15000 });
  const { data: autoReply } = useSWR("/api/auto-reply", fetcher, { refreshInterval: 15000 });
  const { data: revenue } = useSWR("/api/revenue", fetcher, { refreshInterval: 30000 });

  const addActivity = (msg, type = "info") => {
    const entry = { time: new Date().toLocaleTimeString("en-US", { hour12: false }), msg, type };
    const updated = [entry, ...activityRef.current].slice(0, 30);
    setActivity(updated);
  };

  const taskList = Array.isArray(tasks) ? tasks : [];
  const activeCount = taskList.filter((t) => t.status === "open" || t.status === "awarded").length;
  const completedCount = taskList.filter((t) => t.status === "completed").length;
  const failedCount = taskList.filter((t) => t.status === "failed").length;
  const agentEntries = agents ? Object.entries(agents) : [];
  const services = health ? Object.entries(health) : [];
  const onlineServices = services.filter(([, v]) => v?.status === "healthy").length;

  const dispatchTask = async () => {
    if (!objective.trim()) return;
    setDispatching(true);
    setTaskResult(null);
    addActivity(`Dispatching: "${objective.substring(0, 60)}..."`, "info");
    try {
      const url = mode === "full" ? "/api/pipeline/full" : "/api/pipeline";
      const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      const data = await resp.json();
      setTaskResult(data);
      if (data.status === "completed") {
        addActivity(`Task ${data.task_id?.substring(0, 8)} completed by ${data.winner?.agent_id}`, "success");
      } else if (data.status === "task_published") {
        addActivity(`Task ${data.task_id?.substring(0, 8)} published (priority: ${data.ranked?.priority_score?.toFixed(2)})`, "info");
      } else {
        addActivity(`Task result: ${data.status}`, data.status === "failed" ? "error" : "info");
      }
      setObjective("");
    } catch (e) {
      setTaskResult({ error: e.message });
      addActivity(`Dispatch failed: ${e.message}`, "error");
    }
    setDispatching(false);
  };

  const addRule = async () => {
    if (!ruleObjective.trim()) return;
    try {
      await fetch("/api/recurring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective: ruleObjective, category: ruleCategory }),
      });
      addActivity(`Rule created: "${ruleObjective.substring(0, 40)}..."`, "info");
      setRuleObjective("");
      mutateRules();
    } catch (e) {
      addActivity(`Rule creation failed: ${e.message}`, "error");
    }
  };

  const triggerRecurring = async () => {
    try {
      const resp = await fetch("/api/recurring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "trigger" }),
      });
      const data = await resp.json();
      addActivity(`Recurring triggered: ${data.processed || 0} tasks processed`, "success");
    } catch (e) {
      addActivity(`Trigger failed: ${e.message}`, "error");
    }
  };

  return (
    <div>
      <div className="metric-grid" style={{ marginBottom: 16 }}>
        <Metric label="Services" value={`${onlineServices}/${services.length}`} color={onlineServices === services.length ? "green" : "red"} sub={onlineServices === services.length ? "Nominal" : "Degraded"} />
        <Metric label="Prospects" value={pipelineStats?.total_prospects ?? 0} color="cyan" sub={`${pipelineStats?.by_status?.approved ?? 0} approved`} />
        <Metric label="Bids Out" value={pipelineStats?.by_status?.applied ?? 0} color="blue" sub="Awaiting response" />
        <Metric label="Hired" value={pipelineStats?.by_status?.hired ?? 0} color="green" sub="Ready to execute" />
        <Metric label="Executing" value={pipelineStats?.by_status?.executing ?? 0} color="purple" sub="In progress" />
        <Metric label="Delivered" value={pipelineStats?.by_status?.delivered ?? 0} color="amber" sub="Awaiting payment" />
        <Metric label="Paid" value={pipelineStats?.by_status?.paid ?? 0} color="green" sub={`$${pipelineStats?.revenue ?? 0}`} />
        <Metric label="Exec / 24h" value={analytics?.total_executions ?? 0} color="purple" sub={`${((analytics?.success_rate ?? 0) * 100).toFixed(0)}% success`} />
      </div>

      <div className="cmd-grid main-layout" style={{ marginBottom: 16 }}>
        <Panel title="Task Dispatch" dot="info">
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input
              className="cmd-input"
              style={{ flex: 1 }}
              placeholder="Enter task objective..."
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && dispatchTask()}
            />
            <select className="cmd-select" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="full">Autonomous</option>
              <option value="publish">Publish Only</option>
            </select>
            <button className="cmd-btn primary" onClick={dispatchTask} disabled={dispatching || !objective.trim()}>
              {dispatching ? ">>>" : "Dispatch"}
            </button>
          </div>
          {taskResult && (
            <div style={{
              padding: "10px 14px",
              borderRadius: 4,
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              background: taskResult.error ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)",
              border: `1px solid ${taskResult.error ? "rgba(239,68,68,0.3)" : "rgba(16,185,129,0.3)"}`,
              color: taskResult.error ? "#f87171" : "#34d399",
            }}>
              {taskResult.error
                ? `ERR: ${taskResult.error}`
                : `${taskResult.status?.toUpperCase()} // ID: ${taskResult.task_id?.substring(0, 12)} ${taskResult.winner ? `// AGENT: ${taskResult.winner.agent_id}` : ""}`}
            </div>
          )}
        </Panel>

        <Panel title="System Status" dot={onlineServices === services.length ? "" : "error"}>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {services.map(([name, info]) => (
              <div key={name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <StatusDot status={info?.status} />
                  <span style={{ color: "var(--text-secondary)", textTransform: "uppercase" }}>{name}</span>
                </div>
                <span style={{ color: "var(--text-muted)", fontSize: 10 }}>
                  {info?.status === "healthy" ? "OK" : info?.status || "---"}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <div className="cmd-grid main-layout" style={{ marginBottom: 16 }}>
        <Panel title="Recent Activity" dot="">
          {taskList.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Task ID</th>
                  <th>Objective</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Agent</th>
                </tr>
              </thead>
              <tbody>
                {taskList.slice(0, 10).map((t) => (
                  <tr key={t.id}>
                    <td style={{ color: "var(--accent-cyan)" }}>{t.id?.substring(0, 10)}</td>
                    <td style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis" }}>{t.objective}</td>
                    <td>{t.priority_score?.toFixed(2)}</td>
                    <td><span className={`badge ${t.status}`}>{t.status}</span></td>
                    <td style={{ color: "var(--text-muted)" }}>{t.awarded_to?.substring(0, 10) || "---"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ textAlign: "center", padding: 30, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
              No tasks dispatched. Use the panel above to queue work.
            </div>
          )}
        </Panel>

        <Panel title="Activity Log" dot="">
          <div style={{ maxHeight: 280, overflow: "auto" }}>
            {activity.length > 0 ? activity.map((a, i) => (
              <div key={i} className="activity-item">
                <span className="time">{a.time}</span>
                <span className="msg" style={{
                  color: a.type === "error" ? "var(--accent-red)" : a.type === "success" ? "var(--accent-green)" : "var(--text-secondary)"
                }}>{a.msg}</span>
              </div>
            )) : (
              <div style={{ textAlign: "center", padding: 30, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                Awaiting system events...
              </div>
            )}
          </div>
        </Panel>
      </div>

      <div className="cmd-grid main-layout" style={{ marginBottom: 16 }}>
        <Panel title="Freelancer Operations" dot="info">
          {autoReply && (
            <div style={{ padding: "6px 10px", marginBottom: 10, borderRadius: 4, fontSize: 10, fontFamily: "var(--font-mono)", background: autoReply.enabled ? "rgba(16,185,129,0.05)" : "rgba(239,68,68,0.05)", border: `1px solid ${autoReply.enabled ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.15)"}`, color: autoReply.enabled ? "#34d399" : "#f87171" }}>
              AUTO-REPLY: {autoReply.enabled ? "ON" : "OFF"} // DELAY: {autoReply.delay_seconds}s // PENDING: {autoReply.pending_replies} // TELEGRAM: {autoReply.telegram_commands ? "ON" : "OFF"}
            </div>
          )}
          {messages?.messages?.length > 0 ? messages.messages.map((msg) => (
            <div key={msg.thread_id} style={{ padding: "8px 12px", marginBottom: 6, borderRadius: 4, background: msg.is_read ? "var(--bg-input)" : "rgba(6,182,212,0.08)", border: `1px solid ${msg.is_read ? "var(--border)" : "rgba(6,182,212,0.25)"}` }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, fontFamily: "var(--font-mono)" }}>
                <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>
                  {msg.sender} {!msg.is_read && <span style={{ color: "var(--accent-cyan)", fontSize: 9 }}>NEW</span>}
                </span>
                <span style={{ color: "var(--text-muted)", fontSize: 9 }}>{msg.last_message_time ? new Date(msg.last_message_time * 1000).toLocaleTimeString() : ""}</span>
              </div>
              {msg.prospect && <div style={{ fontSize: 9, fontFamily: "var(--font-mono)", color: "var(--accent-cyan)", marginTop: 2 }}>{msg.prospect.title} // <span className={`badge ${msg.prospect.status}`} style={{ fontSize: 8, padding: "0 4px" }}>{msg.prospect.status}</span></div>}
              <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-secondary)", marginTop: 3, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{msg.last_message || "(no preview)"}</div>
            </div>
          )) : (
            <div style={{ textAlign: "center", padding: 20, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>No active conversations</div>
          )}
        </Panel>

        <Panel title="Pipeline Flow" dot="">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { label: "Discovered", key: "discovered", color: "var(--text-muted)" },
              { label: "Approved", key: "approved", color: "var(--accent-green)" },
              { label: "Bids Placed", key: "applied", color: "var(--accent-cyan)" },
              { label: "Hired", key: "hired", color: "#f59e0b" },
              { label: "Executing", key: "executing", color: "#a78bfa" },
              { label: "Delivered", key: "delivered", color: "#34d399" },
              { label: "Paid", key: "paid", color: "#10b981" },
            ].map((stage) => {
              const count = pipelineStats?.by_status?.[stage.key] ?? 0;
              const total = pipelineStats?.total_prospects || 1;
              const pct = Math.min(100, Math.round((count / total) * 100));
              return (
                <div key={stage.key}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, fontFamily: "var(--font-mono)", marginBottom: 3 }}>
                    <span style={{ color: stage.color }}>{stage.label}</span>
                    <span style={{ color: "var(--text-muted)" }}>{count}</span>
                  </div>
                  <div style={{ height: 4, background: "rgba(30,45,74,0.5)", borderRadius: 2 }}>
                    <div style={{ height: "100%", width: `${pct}%`, background: stage.color, borderRadius: 2, transition: "width 0.3s" }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 12, padding: "6px 10px", borderRadius: 4, background: "rgba(16,185,129,0.05)", border: "1px solid rgba(16,185,129,0.15)", fontFamily: "var(--font-mono)", fontSize: 10, color: "#34d399", display: "flex", justifyContent: "space-between" }}>
            <span>REVENUE: ${pipelineStats?.revenue ?? 0}</span>
            <span>PROFIT: ${pipelineStats?.estimated_profit ?? 0}</span>
          </div>
        </Panel>
      </div>

      <div className="cmd-grid cols-2">
        <Panel title="Recurring Automation" dot="" actions={
          <button className="cmd-btn sm success" onClick={triggerRecurring}>Trigger All</button>
        }>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input
              className="cmd-input"
              style={{ flex: 1 }}
              placeholder="Rule objective..."
              value={ruleObjective}
              onChange={(e) => setRuleObjective(e.target.value)}
            />
            <select className="cmd-select" value={ruleCategory} onChange={(e) => setRuleCategory(e.target.value)}>
              <option value="uncategorized">General</option>
              <option value="code_development">Dev</option>
              <option value="data_analysis">Data</option>
              <option value="content_creation">Content</option>
            </select>
            <button className="cmd-btn sm primary" onClick={addRule} disabled={!ruleObjective.trim()}>Add</button>
          </div>
          {rules && rules.length > 0 ? (
            <div style={{ maxHeight: 160, overflow: "auto" }}>
              {rules.map((r) => (
                <div key={r.rule_id} style={{ padding: "6px 0", borderBottom: "1px solid rgba(30,45,74,0.3)", fontSize: 11, fontFamily: "var(--font-mono)", display: "flex", justifyContent: "space-between" }}>
                  <span style={{ color: "var(--text-secondary)" }}>{r.objective?.substring(0, 50)}</span>
                  <span className={`badge ${r.category === "uncategorized" ? "draft" : "approved"}`}>{r.category}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: 20, color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>No automation rules</div>
          )}
        </Panel>

        <Panel title="Scan Status" dot={scanState?.running ? "warn" : ""} actions={
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: scanState?.auto_scan_enabled ? "var(--accent-green)" : "var(--text-muted)" }}>
            {scanState?.auto_scan_enabled ? "AUTO" : "MANUAL"}
          </span>
        }>
          <div className="metric-grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
            <Metric label="Total Scans" value={scanState?.total_scans ?? 0} color="blue" />
            <Metric label="Discovered" value={scanState?.total_discovered ?? 0} color="green" />
            <Metric label="Platforms" value={scanState?.platforms?.length ?? 0} color="cyan" />
          </div>
          {scanState?.last_scan_at && (
            <div style={{ marginTop: 10, fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
              Last scan: {new Date(scanState.last_scan_at).toLocaleString()}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
