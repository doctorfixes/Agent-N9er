"use client";

import { useState, useEffect, useCallback } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

function StatusDot({ status }) {
  const color = status === "healthy" ? "#22c55e" : status === "degraded" ? "#eab308" : "#ef4444";
  return <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color, marginRight: 6 }} />;
}

function Card({ title, children, style }) {
  return (
    <div style={{ background: "white", padding: "20px", borderRadius: "8px", border: "1px solid #e5e7eb", ...style }}>
      {title && <h3 style={{ margin: "0 0 12px 0", fontSize: "15px", fontWeight: 600, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em" }}>{title}</h3>}
      {children}
    </div>
  );
}

export default function MissionControl() {
  const [objective, setObjective] = useState("");
  const [mode, setMode] = useState("full");
  const [taskResult, setTaskResult] = useState(null);
  const [taskLoading, setTaskLoading] = useState(false);
  const [ruleObjective, setRuleObjective] = useState("");
  const [ruleCategory, setRuleCategory] = useState("");
  const [triggerResult, setTriggerResult] = useState(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [activity, setActivity] = useState([]);

  const { data: health } = useSWR("/api/health", fetcher, { refreshInterval: 15000 });
  const { data: tasks } = useSWR("/api/tasks", fetcher, { refreshInterval: 5000 });
  const { data: rules, mutate: mutateRules } = useSWR("/api/recurring", fetcher, { refreshInterval: 10000 });
  const { data: agents } = useSWR("/api/agents", fetcher, { refreshInterval: 10000 });

  const taskList = Array.isArray(tasks) ? tasks : [];
  const ruleList = Array.isArray(rules) ? rules : [];
  const agentEntries = agents ? Object.entries(agents) : [];

  const activeCount = taskList.filter((t) => t.status === "open" || t.status === "awarded").length;
  const completedCount = taskList.filter((t) => t.status === "completed").length;
  const failedCount = taskList.filter((t) => t.status === "failed").length;

  const addActivity = useCallback((msg) => {
    setActivity((prev) => [{ msg, time: new Date().toLocaleTimeString() }, ...prev].slice(0, 20));
  }, []);

  async function dispatchTask(e) {
    e.preventDefault();
    if (!objective.trim()) return;
    setTaskLoading(true);
    setTaskResult(null);
    const endpoint = mode === "full" ? "/api/pipeline/full" : "/api/pipeline";
    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      const data = await resp.json();
      setTaskResult(data);
      addActivity(`Dispatched: "${objective.slice(0, 50)}" → ${data.status || "submitted"}`);
      setObjective("");
    } catch {
      setTaskResult({ error: "Pipeline unreachable" });
      addActivity(`Failed to dispatch: "${objective.slice(0, 50)}"`);
    }
    setTaskLoading(false);
  }

  async function addRule(e) {
    e.preventDefault();
    if (!ruleObjective.trim()) return;
    try {
      await fetch("/api/recurring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective: ruleObjective, category: ruleCategory || "uncategorized" }),
      });
      addActivity(`Rule added: "${ruleObjective.slice(0, 50)}"`);
      setRuleObjective("");
      setRuleCategory("");
      mutateRules();
    } catch {
      addActivity("Failed to add rule");
    }
  }

  async function triggerRecurring() {
    setTriggerLoading(true);
    setTriggerResult(null);
    try {
      const resp = await fetch("/api/recurring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "trigger" }),
      });
      const data = await resp.json();
      setTriggerResult(data);
      addActivity(`Recurring tick: ${data.processed || 0} tasks processed`);
    } catch {
      setTriggerResult({ error: "Trigger failed" });
      addActivity("Recurring trigger failed");
    }
    setTriggerLoading(false);
  }

  const healthServices = health?.services || {};
  const healthyCount = Object.values(healthServices).filter((s) => s.status === "healthy").length;
  const totalServices = Object.keys(healthServices).length;

  return (
    <div>
      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ margin: "0 0 4px 0", fontSize: "1.6em" }}>Mission Control</h1>
        <p style={{ margin: 0, color: "#6b7280", fontSize: "14px" }}>
          Autonomous task orchestration — dispatch, monitor, and manage your agent workforce
        </p>
      </div>

      {/* Status Bar */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "12px", marginBottom: "20px" }}>
        <Card style={{ padding: "14px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", fontWeight: 700 }}>{healthyCount}/{totalServices}</div>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Services Online</div>
        </Card>
        <Card style={{ padding: "14px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", fontWeight: 700 }}>{activeCount}</div>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Active Tasks</div>
        </Card>
        <Card style={{ padding: "14px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "#22c55e" }}>{completedCount}</div>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Completed</div>
        </Card>
        <Card style={{ padding: "14px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", fontWeight: 700, color: "#ef4444" }}>{failedCount}</div>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Failed</div>
        </Card>
        <Card style={{ padding: "14px 16px", textAlign: "center" }}>
          <div style={{ fontSize: "24px", fontWeight: 700 }}>{agentEntries.length}</div>
          <div style={{ fontSize: "12px", color: "#6b7280" }}>Agents</div>
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>
        {/* Dispatch Task */}
        <Card title="Dispatch Task">
          <form onSubmit={dispatchTask}>
            <input
              type="text"
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="Describe the task objective..."
              style={{ width: "100%", padding: "10px", fontSize: "14px", border: "1px solid #d1d5db", borderRadius: "6px", marginBottom: "10px", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                style={{ padding: "8px", fontSize: "13px", border: "1px solid #d1d5db", borderRadius: "6px" }}
              >
                <option value="full">Autonomous (bid + execute)</option>
                <option value="publish">Publish only (manual award)</option>
              </select>
              <button
                type="submit"
                disabled={taskLoading}
                style={{ padding: "8px 20px", fontSize: "13px", fontWeight: 600, background: "#2563eb", color: "white", border: "none", borderRadius: "6px", cursor: taskLoading ? "not-allowed" : "pointer" }}
              >
                {taskLoading ? "Dispatching..." : "Dispatch"}
              </button>
            </div>
          </form>
          {taskResult && (
            <div style={{ marginTop: "10px", padding: "10px", background: taskResult.error ? "#fef2f2" : "#f0fdf4", borderRadius: "6px", fontSize: "13px" }}>
              <strong>{taskResult.status || taskResult.error || "Submitted"}</strong>
              {taskResult.task_id && <span style={{ marginLeft: "8px", fontFamily: "monospace", fontSize: "11px", color: "#6b7280" }}>{taskResult.task_id.slice(0, 12)}</span>}
              {taskResult.winner && <span style={{ marginLeft: "8px" }}>Agent: {taskResult.winner.agent_id?.slice(0, 12)}</span>}
            </div>
          )}
        </Card>

        {/* Recurring Rules */}
        <Card title="Recurring Automation">
          <form onSubmit={addRule} style={{ marginBottom: "10px" }}>
            <input
              type="text"
              value={ruleObjective}
              onChange={(e) => setRuleObjective(e.target.value)}
              placeholder="Recurring task objective..."
              style={{ width: "100%", padding: "8px", fontSize: "13px", border: "1px solid #d1d5db", borderRadius: "6px", marginBottom: "8px", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                value={ruleCategory}
                onChange={(e) => setRuleCategory(e.target.value)}
                placeholder="Category (optional)"
                style={{ flex: 1, padding: "8px", fontSize: "13px", border: "1px solid #d1d5db", borderRadius: "6px" }}
              />
              <button type="submit" style={{ padding: "8px 14px", fontSize: "13px", background: "#059669", color: "white", border: "none", borderRadius: "6px", cursor: "pointer" }}>
                Add Rule
              </button>
            </div>
          </form>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
            <span style={{ fontSize: "13px", color: "#6b7280" }}>{ruleList.length} rule{ruleList.length !== 1 ? "s" : ""} configured</span>
            <button
              onClick={triggerRecurring}
              disabled={triggerLoading || ruleList.length === 0}
              style={{ padding: "6px 14px", fontSize: "12px", fontWeight: 600, background: "#7c3aed", color: "white", border: "none", borderRadius: "6px", cursor: triggerLoading ? "not-allowed" : "pointer" }}
            >
              {triggerLoading ? "Running..." : "Run All Now"}
            </button>
          </div>
          {ruleList.length > 0 && (
            <div style={{ maxHeight: "120px", overflow: "auto", fontSize: "12px" }}>
              {ruleList.map((r, i) => (
                <div key={r.rule_id || i} style={{ padding: "4px 0", borderBottom: "1px solid #f3f4f6", display: "flex", justifyContent: "space-between" }}>
                  <span>{r.objective?.slice(0, 50)}</span>
                  <span style={{ color: "#9ca3af", fontFamily: "monospace" }}>{r.category || "uncategorized"}</span>
                </div>
              ))}
            </div>
          )}
          {triggerResult && (
            <div style={{ marginTop: "8px", padding: "8px", background: "#f5f3ff", borderRadius: "6px", fontSize: "12px" }}>
              Processed: {triggerResult.processed || 0} tasks
            </div>
          )}
        </Card>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "16px" }}>
        {/* Recent Tasks */}
        <Card title="Recent Activity">
          {taskList.length === 0 ? (
            <p style={{ color: "#9ca3af", fontSize: "13px" }}>No tasks dispatched yet.</p>
          ) : (
            <div style={{ maxHeight: "300px", overflow: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                    <th style={{ padding: "6px 8px", fontWeight: 600, color: "#6b7280" }}>Objective</th>
                    <th style={{ padding: "6px 8px", fontWeight: 600, color: "#6b7280", width: "80px" }}>Priority</th>
                    <th style={{ padding: "6px 8px", fontWeight: 600, color: "#6b7280", width: "90px" }}>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {taskList.slice(0, 15).map((t, i) => (
                    <tr key={t.id || i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "6px 8px" }}>{t.objective?.slice(0, 60) || "-"}</td>
                      <td style={{ padding: "6px 8px", fontFamily: "monospace" }}>{t.priority_score ?? "-"}</td>
                      <td style={{ padding: "6px 8px" }}>
                        <span style={{
                          padding: "2px 8px", borderRadius: "10px", fontSize: "11px", fontWeight: 600,
                          background: t.status === "completed" ? "#dcfce7" : t.status === "failed" ? "#fee2e2" : t.status === "awarded" ? "#dbeafe" : "#f3f4f6",
                          color: t.status === "completed" ? "#166534" : t.status === "failed" ? "#991b1b" : t.status === "awarded" ? "#1e40af" : "#374151",
                        }}>
                          {t.status || "open"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* System Health + Activity Log */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <Card title="System Health">
            {totalServices === 0 ? (
              <p style={{ color: "#9ca3af", fontSize: "13px" }}>Checking...</p>
            ) : (
              <div style={{ fontSize: "13px" }}>
                {Object.entries(healthServices).map(([name, info]) => (
                  <div key={name} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "3px 0" }}>
                    <span><StatusDot status={info.status} />{name}</span>
                    <span style={{ fontSize: "11px", color: "#9ca3af" }}>{info.status}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Activity Log">
            {activity.length === 0 ? (
              <p style={{ color: "#9ca3af", fontSize: "13px" }}>Dispatch a task to see activity.</p>
            ) : (
              <div style={{ maxHeight: "180px", overflow: "auto", fontSize: "12px" }}>
                {activity.map((a, i) => (
                  <div key={i} style={{ padding: "3px 0", borderBottom: "1px solid #f3f4f6" }}>
                    <span style={{ color: "#9ca3af", fontFamily: "monospace", marginRight: "6px" }}>{a.time}</span>
                    {a.msg}
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
