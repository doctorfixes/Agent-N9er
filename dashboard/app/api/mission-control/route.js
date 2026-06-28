const BROWSER_SERVICE_URL = process.env.BROWSER_SERVICE_URL || "http://localhost:8001";
const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const MARKETPLACE_URL = process.env.MARKETPLACE_URL || "http://localhost:8300";
const REPUTATION_URL = process.env.REPUTATION_URL || "http://localhost:8500";
const SIMULATION_URL = process.env.SIMULATION_URL || "http://localhost:9100";

const SERVICES = [
  { name: "orchestrator", url: `${ORCHESTRATOR_URL}/health` },
  { name: "browser-service", url: `${BROWSER_SERVICE_URL}/health` },
  { name: "marketplace", url: `${MARKETPLACE_URL}/health` },
  { name: "reputation-ledger", url: `${REPUTATION_URL}/health` },
  { name: "simulation-engine", url: `${SIMULATION_URL}/health` },
];

async function fetchService(svc) {
  try {
    const resp = await fetch(svc.url, { signal: AbortSignal.timeout(3000) });
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return { name: svc.name, online: true, ...data };
  } catch {
    return { name: svc.name, online: false };
  }
}

export async function GET() {
  const [services, watchersRes, tasksRes, agentsRes, signalsRes] = await Promise.allSettled([
    Promise.all(SERVICES.map(fetchService)),
    fetch(`${BROWSER_SERVICE_URL}/watchers`, { signal: AbortSignal.timeout(3000) }).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return {}; } }),
    fetch(`${MARKETPLACE_URL}/feed`, { signal: AbortSignal.timeout(3000) }).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return {}; } }),
    fetch(`${REPUTATION_URL}/ledger`, { signal: AbortSignal.timeout(3000) }).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return {}; } }),
    fetch(`${BROWSER_SERVICE_URL}/signals`, { signal: AbortSignal.timeout(3000) }).then((r) => r.text()).then((t) => { try { return JSON.parse(t); } catch { return {}; } }),
  ]);

  const watchers = watchersRes.status === "fulfilled" ? watchersRes.value : { available: [], active: [] };
  const tasks = tasksRes.status === "fulfilled" ? tasksRes.value : [];
  const agents = agentsRes.status === "fulfilled" ? agentsRes.value : {};
  const signals = signalsRes.status === "fulfilled" ? signalsRes.value : [];

  return Response.json({
    services: services.status === "fulfilled" ? services.value : [],
    watchers,
    task_count: Array.isArray(tasks) ? tasks.length : 0,
    agent_count: Object.keys(agents).length,
    recent_signals: signals.slice(0, 5),
  });
}
