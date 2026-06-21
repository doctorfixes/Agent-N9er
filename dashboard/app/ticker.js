"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((r) => r.json()).catch(() => null);

export default function TickerBar() {
  const { data: health } = useSWR("/api/health", fetcher, { refreshInterval: 15000 });
  const { data: stats } = useSWR("/api/prospects/stats", fetcher, { refreshInterval: 20000 });
  const { data: revenue } = useSWR("/api/revenue", fetcher, { refreshInterval: 30000 });
  const { data: scan } = useSWR("/api/scan", fetcher, { refreshInterval: 30000 });
  const { data: analytics } = useSWR("/api/analytics?days=1", fetcher, { refreshInterval: 30000 });

  const services = health ? Object.entries(health) : [];
  const onlineCount = services.filter(([, v]) => v?.status === "healthy").length;
  const totalServices = services.length;

  const items = [];

  items.push({ label: "SYS", value: `${onlineCount}/${totalServices}`, cls: onlineCount === totalServices ? "up" : "down" });
  items.push({ label: "PROSPECTS", value: stats?.total_prospects ?? "---", cls: "neutral" });
  items.push({ label: "APPROVED", value: stats?.by_status?.approved ?? "0", cls: "up" });
  items.push({ label: "EXECUTING", value: stats?.by_status?.executing ?? "0", cls: stats?.by_status?.executing > 0 ? "up" : "neutral" });
  items.push({ label: "REVENUE", value: `$${(revenue?.total_revenue_usd ?? 0).toFixed(2)}`, cls: revenue?.total_revenue_usd > 0 ? "up" : "neutral" });
  items.push({ label: "PROFIT", value: `$${(revenue?.total_profit_usd ?? 0).toFixed(2)}`, cls: revenue?.total_profit_usd > 0 ? "up" : "neutral" });
  items.push({ label: "MARGIN", value: `${(revenue?.profit_margin_pct ?? 0).toFixed(1)}%`, cls: (revenue?.profit_margin_pct ?? 0) > 50 ? "up" : "neutral" });
  items.push({ label: "TOKEN COST", value: `$${(revenue?.total_token_cost_usd ?? 0).toFixed(4)}`, cls: "down" });
  items.push({ label: "OUTSTANDING", value: `$${(revenue?.outstanding_usd ?? 0).toFixed(2)}`, cls: revenue?.outstanding_usd > 0 ? "down" : "neutral" });
  items.push({ label: "SCANS", value: scan?.total_scans ?? "0", cls: "neutral" });
  items.push({ label: "DISCOVERED", value: scan?.total_discovered ?? "0", cls: scan?.total_discovered > 0 ? "up" : "neutral" });
  items.push({ label: "AUTO-SCAN", value: scan?.auto_scan_enabled ? "ON" : "OFF", cls: scan?.auto_scan_enabled ? "up" : "neutral" });
  items.push({ label: "EXEC/24H", value: analytics?.total_executions ?? "0", cls: "neutral" });
  items.push({ label: "SUCCESS", value: analytics ? `${(analytics.success_rate * 100).toFixed(0)}%` : "---", cls: (analytics?.success_rate ?? 0) > 0.7 ? "up" : "down" });
  items.push({ label: "MODE", value: analytics?.live_executions > 0 ? "LIVE" : "SIM", cls: analytics?.live_executions > 0 ? "up" : "neutral" });
  items.push({ label: "DELIVERED", value: stats?.by_status?.delivered ?? "0", cls: "up" });
  items.push({ label: "PAID", value: stats?.by_status?.paid ?? "0", cls: "up" });

  const doubled = [...items, ...items];

  return (
    <div className="ticker-bar">
      <div className="ticker-track">
        {doubled.map((item, i) => (
          <span key={i} className="ticker-item">
            <span className="label">{item.label}</span>
            <span className={`value ${item.cls}`}>{item.value}</span>
            <span className="sep">//</span>
          </span>
        ))}
      </div>
    </div>
  );
}
