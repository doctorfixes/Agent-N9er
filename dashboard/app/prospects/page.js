"use client";

import { useState } from "react";
import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

const STATUS_COLORS = {
  discovered: "#6b7280",
  evaluating: "#3b82f6",
  approved: "#22c55e",
  applied: "#8b5cf6",
  hired: "#f59e0b",
  executing: "#ef4444",
  delivered: "#10b981",
  paid: "#059669",
  rated: "#6366f1",
  rejected: "#dc2626",
};

function Badge({ status }) {
  return (
    <span style={{
      display: "inline-block", padding: "2px 8px", borderRadius: "9999px",
      fontSize: "11px", fontWeight: 600, color: "white",
      background: STATUS_COLORS[status] || "#6b7280",
    }}>
      {status}
    </span>
  );
}

function Card({ title, value, subtitle }) {
  return (
    <div style={{ background: "white", padding: "16px 20px", borderRadius: "8px", border: "1px solid #e5e7eb", minWidth: 140 }}>
      <div style={{ fontSize: "12px", color: "#6b7280", textTransform: "uppercase", fontWeight: 600, letterSpacing: "0.05em" }}>{title}</div>
      <div style={{ fontSize: "28px", fontWeight: 700, color: "#111827", marginTop: 4 }}>{value}</div>
      {subtitle && <div style={{ fontSize: "12px", color: "#9ca3af", marginTop: 2 }}>{subtitle}</div>}
    </div>
  );
}

export default function ProspectsPage() {
  const [statusFilter, setStatusFilter] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState(null);

  const { data: prospects, mutate } = useSWR("/api/prospects" + (statusFilter ? `?status=${statusFilter}` : ""), fetcher, { refreshInterval: 10000 });
  const { data: stats } = useSWR("/api/prospects/stats", fetcher, { refreshInterval: 15000 });
  const { data: platforms } = useSWR("/api/prospects/platforms", fetcher);

  const handleScan = async (platform) => {
    setScanning(true);
    setScanResult(null);
    try {
      const resp = await fetch("/api/prospects/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ platform }),
      });
      const data = await resp.json();
      setScanResult(data);
      mutate();
    } catch (e) {
      setScanResult({ error: e.message });
    }
    setScanning(false);
  };

  const statusFilters = ["", "discovered", "approved", "applied", "hired", "executing", "delivered", "paid"];

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: "22px", fontWeight: 700, color: "#111827" }}>Prospect Pipeline</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => handleScan("upwork")}
            disabled={scanning}
            style={{ padding: "8px 16px", background: "#111827", color: "white", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13, fontWeight: 500 }}
          >
            {scanning ? "Scanning..." : "Scan Upwork"}
          </button>
        </div>
      </div>

      {scanResult && (
        <div style={{ padding: "12px 16px", marginBottom: 16, borderRadius: 8, background: scanResult.error ? "#fef2f2" : "#f0fdf4", border: `1px solid ${scanResult.error ? "#fecaca" : "#bbf7d0"}` }}>
          {scanResult.error
            ? `Scan failed: ${scanResult.error}`
            : `Found ${scanResult.discovered} jobs, ${scanResult.new} new prospects`}
        </div>
      )}

      {stats && (
        <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
          <Card title="Total" value={stats.total_prospects ?? 0} />
          <Card title="Approved" value={stats.by_status?.approved ?? 0} />
          <Card title="Executing" value={stats.by_status?.executing ?? 0} />
          <Card title="Delivered" value={stats.by_status?.delivered ?? 0} />
          <Card title="Revenue" value={`$${stats.revenue ?? 0}`} />
        </div>
      )}

      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {statusFilters.map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatusFilter(s)}
            style={{
              padding: "4px 12px", borderRadius: 6, border: "1px solid #e5e7eb",
              background: statusFilter === s ? "#111827" : "white",
              color: statusFilter === s ? "white" : "#374151",
              fontSize: 12, fontWeight: 500, cursor: "pointer",
            }}
          >
            {s || "All"}
          </button>
        ))}
      </div>

      <div style={{ background: "white", borderRadius: 8, border: "1px solid #e5e7eb", overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f9fafb" }}>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Title</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Platform</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Budget</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Status</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280" }}>Discovered</th>
            </tr>
          </thead>
          <tbody>
            {prospects && prospects.length > 0 ? prospects.map((p) => (
              <tr key={p.id} style={{ borderTop: "1px solid #f3f4f6" }}>
                <td style={{ padding: "10px 16px", fontWeight: 500, maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.title}</td>
                <td style={{ padding: "10px 16px", color: "#6b7280" }}>{p.platform}</td>
                <td style={{ padding: "10px 16px", color: "#374151" }}>
                  {p.budget_max > 0 ? `$${p.budget_min}-$${p.budget_max}` : "N/A"}
                </td>
                <td style={{ padding: "10px 16px" }}><Badge status={p.status} /></td>
                <td style={{ padding: "10px 16px", color: "#9ca3af", fontSize: 12 }}>{p.discovered_at ? new Date(p.discovered_at).toLocaleDateString() : "-"}</td>
              </tr>
            )) : (
              <tr>
                <td colSpan={5} style={{ padding: "40px 16px", textAlign: "center", color: "#9ca3af" }}>
                  No prospects yet. Click "Scan Upwork" to discover jobs.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
