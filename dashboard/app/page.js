"use client";

import { useState } from "react";

export default function HomePage() {
  const [objective, setObjective] = useState("");
  const [result, setResult] = useState(null);
  const [simResult, setSimResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [simLoading, setSimLoading] = useState(false);

  async function submitTask(e) {
    e.preventDefault();
    if (!objective.trim()) return;
    setLoading(true);
    try {
      const resp = await fetch("/api/pipeline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective }),
      });
      setResult(await resp.json());
      setObjective("");
    } catch {
      setResult({ error: "Failed to submit task" });
    }
    setLoading(false);
  }

  async function runSimulation(mode) {
    setSimLoading(true);
    try {
      const opts = mode === "live"
        ? { method: "POST" }
        : { method: "GET" };
      const resp = await fetch(`/api/simulate?n=5`, opts);
      setSimResult(await resp.json());
    } catch {
      setSimResult({ error: "Simulation failed" });
    }
    setSimLoading(false);
  }

  return (
    <div>
      <h1>Verixio Dashboard</h1>
      <p>Multi-agent task marketplace with autonomous bidding and execution</p>

      <div style={{ background: "white", padding: "20px", borderRadius: "8px", marginBottom: "20px" }}>
        <h2>Submit Task</h2>
        <form onSubmit={submitTask} style={{ display: "flex", gap: "10px" }}>
          <input
            type="text"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Describe the task objective..."
            style={{ flex: 1, padding: "8px", fontSize: "14px" }}
          />
          <button type="submit" disabled={loading} style={{ padding: "8px 20px" }}>
            {loading ? "Submitting..." : "Submit"}
          </button>
        </form>
        {result && (
          <pre style={{ marginTop: "10px", background: "#f0f0f0", padding: "10px", overflow: "auto", maxHeight: "300px" }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>

      <div style={{ background: "white", padding: "20px", borderRadius: "8px" }}>
        <h2>Run Simulation</h2>
        <div style={{ display: "flex", gap: "10px", marginBottom: "10px" }}>
          <button onClick={() => runSimulation("local")} disabled={simLoading} style={{ padding: "8px 20px" }}>
            {simLoading ? "Running..." : "Local Simulation (5 rounds)"}
          </button>
          <button onClick={() => runSimulation("live")} disabled={simLoading} style={{ padding: "8px 20px" }}>
            {simLoading ? "Running..." : "Live Pipeline (5 rounds)"}
          </button>
        </div>
        <p style={{ fontSize: "13px", color: "#666" }}>
          Local runs the agent loop in-memory. Live runs tasks through the full microservice pipeline.
        </p>
        {simResult && (
          <pre style={{ marginTop: "10px", background: "#f0f0f0", padding: "10px", overflow: "auto", maxHeight: "400px" }}>
            {JSON.stringify(simResult, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
