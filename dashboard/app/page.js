"use client";

import { useState } from "react";

export default function HomePage() {
  const [objective, setObjective] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

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

  return (
    <div>
      <h1>Verixio Dashboard</h1>
      <p>Multi-agent task marketplace</p>

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
          <pre style={{ marginTop: "10px", background: "#f0f0f0", padding: "10px", overflow: "auto" }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
