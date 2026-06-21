"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json());

function MetricCard({ title, value, subtitle, color }) {
  return (
    <div style={{ background: "white", padding: "20px 24px", borderRadius: "8px", border: "1px solid #e5e7eb", flex: 1, minWidth: 160 }}>
      <div style={{ fontSize: "12px", color: "#6b7280", textTransform: "uppercase", fontWeight: 600, letterSpacing: "0.05em" }}>{title}</div>
      <div style={{ fontSize: "32px", fontWeight: 700, color: color || "#111827", marginTop: 6 }}>{value}</div>
      {subtitle && <div style={{ fontSize: "12px", color: "#9ca3af", marginTop: 4 }}>{subtitle}</div>}
    </div>
  );
}

function InvoiceRow({ inv }) {
  const statusColor = {
    draft: "#6b7280", sent: "#3b82f6", paid: "#22c55e", failed: "#ef4444", refunded: "#f59e0b", cancelled: "#dc2626",
  }[inv.status] || "#6b7280";

  return (
    <tr style={{ borderTop: "1px solid #f3f4f6" }}>
      <td style={{ padding: "10px 16px", fontSize: 13, maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{inv.description}</td>
      <td style={{ padding: "10px 16px", fontSize: 13, color: "#374151" }}>{inv.client_email}</td>
      <td style={{ padding: "10px 16px", fontSize: 13, fontWeight: 600, color: "#111827" }}>${inv.amount_usd?.toFixed(2)}</td>
      <td style={{ padding: "10px 16px", fontSize: 13, color: "#6b7280" }}>${inv.token_cost_usd?.toFixed(2)}</td>
      <td style={{ padding: "10px 16px", fontSize: 13, fontWeight: 600, color: "#059669" }}>${inv.profit_usd?.toFixed(2)}</td>
      <td style={{ padding: "10px 16px" }}>
        <span style={{ display: "inline-block", padding: "2px 8px", borderRadius: "9999px", fontSize: 11, fontWeight: 600, color: "white", background: statusColor }}>
          {inv.status}
        </span>
      </td>
      <td style={{ padding: "10px 16px", fontSize: 12, color: "#9ca3af" }}>{inv.created_at ? new Date(inv.created_at).toLocaleDateString() : "-"}</td>
    </tr>
  );
}

export default function RevenuePage() {
  const { data: revenue } = useSWR("/api/revenue", fetcher, { refreshInterval: 15000 });
  const { data: invoices } = useSWR("/api/invoices", fetcher, { refreshInterval: 10000 });

  return (
    <div>
      <h1 style={{ margin: "0 0 20px 0", fontSize: "22px", fontWeight: 700, color: "#111827" }}>Revenue Dashboard</h1>

      <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap" }}>
        <MetricCard title="Total Revenue" value={`$${revenue?.total_revenue_usd?.toFixed(2) ?? "0.00"}`} color="#059669" />
        <MetricCard title="Total Profit" value={`$${revenue?.total_profit_usd?.toFixed(2) ?? "0.00"}`} color="#059669" subtitle={revenue?.profit_margin_pct ? `${revenue.profit_margin_pct}% margin` : ""} />
        <MetricCard title="Token Costs" value={`$${revenue?.total_token_cost_usd?.toFixed(2) ?? "0.00"}`} color="#dc2626" />
        <MetricCard title="Outstanding" value={`$${revenue?.outstanding_usd?.toFixed(2) ?? "0.00"}`} color="#f59e0b" subtitle={`${revenue?.total_invoices ?? 0} total invoices`} />
        <MetricCard title="Paid" value={revenue?.paid_invoices ?? 0} subtitle="invoices collected" />
      </div>

      <div style={{ background: "white", borderRadius: 8, border: "1px solid #e5e7eb", overflow: "hidden" }}>
        <div style={{ padding: "16px 16px 0", borderBottom: "1px solid #f3f4f6" }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 600, color: "#374151" }}>INVOICES</h3>
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#f9fafb" }}>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Description</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Client</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Amount</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Token Cost</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Profit</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Status</th>
              <th style={{ padding: "10px 16px", textAlign: "left", fontWeight: 600, color: "#6b7280", fontSize: 12 }}>Date</th>
            </tr>
          </thead>
          <tbody>
            {invoices && invoices.length > 0 ? invoices.map((inv) => (
              <InvoiceRow key={inv.invoice_id} inv={inv} />
            )) : (
              <tr>
                <td colSpan={7} style={{ padding: "40px 16px", textAlign: "center", color: "#9ca3af", fontSize: 14 }}>
                  No invoices yet. Revenue will appear here as Agent N9er completes jobs.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
