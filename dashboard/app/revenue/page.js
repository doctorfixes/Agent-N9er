"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return null; } }).catch(() => null);

export default function RevenuePage() {
  const { data: revenue } = useSWR("/api/revenue", fetcher, { refreshInterval: 15000 });
  const { data: invoices } = useSWR("/api/invoices", fetcher, { refreshInterval: 10000 });

  return (
    <div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 14, fontWeight: 700, color: "var(--accent-cyan)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 16 }}>
        Revenue Operations
      </div>

      <div className="metric-grid" style={{ marginBottom: 16 }}>
        <div className="metric green">
          <div className="metric-label">Total Revenue</div>
          <div className="metric-value">${(revenue?.total_revenue_usd ?? 0).toFixed(2)}</div>
        </div>
        <div className="metric cyan">
          <div className="metric-label">Total Profit</div>
          <div className="metric-value">${(revenue?.total_profit_usd ?? 0).toFixed(2)}</div>
          <div className="metric-sub">{(revenue?.profit_margin_pct ?? 0).toFixed(1)}% margin</div>
        </div>
        <div className="metric red">
          <div className="metric-label">Token Costs</div>
          <div className="metric-value">${(revenue?.total_token_cost_usd ?? 0).toFixed(4)}</div>
        </div>
        <div className="metric amber">
          <div className="metric-label">Outstanding</div>
          <div className="metric-value">${(revenue?.outstanding_usd ?? 0).toFixed(2)}</div>
          <div className="metric-sub">{revenue?.total_invoices ?? 0} invoices</div>
        </div>
        <div className="metric green">
          <div className="metric-label">Paid</div>
          <div className="metric-value">{revenue?.paid_invoices ?? 0}</div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-header">
          <div className="panel-title"><span className="dot" /> Invoice Ledger</div>
        </div>
        <table className="data-table">
          <thead>
            <tr>
              <th>Description</th>
              <th>Client</th>
              <th>Amount</th>
              <th>Token Cost</th>
              <th>Profit</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {invoices && invoices.length > 0 ? invoices.map((inv) => (
              <tr key={inv.invoice_id}>
                <td style={{ maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis", color: "var(--text-primary)", fontWeight: 500 }}>{inv.description}</td>
                <td style={{ fontSize: 10 }}>{inv.client_email || "---"}</td>
                <td style={{ color: "var(--accent-green)" }}>${inv.amount_usd?.toFixed(2)}</td>
                <td style={{ color: "var(--accent-red)" }}>${inv.token_cost_usd?.toFixed(4)}</td>
                <td style={{ color: "var(--accent-cyan)" }}>${inv.profit_usd?.toFixed(2)}</td>
                <td><span className={`badge ${inv.status}`}>{inv.status}</span></td>
                <td style={{ fontSize: 10 }}>{inv.created_at ? new Date(inv.created_at).toLocaleDateString() : "---"}</td>
              </tr>
            )) : (
              <tr>
                <td colSpan={7} style={{ padding: 40, textAlign: "center", color: "var(--text-muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
                  No invoices generated. Execute the revenue pipeline to begin billing.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
