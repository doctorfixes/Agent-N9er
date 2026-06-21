const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

const SERVICES = {
  orchestrator: process.env.ORCHESTRATOR_URL || "http://localhost:9000",
  normalization: process.env.NORMALIZATION_URL || "http://localhost:8100",
  ranking: process.env.RANKING_URL || "http://localhost:8200",
  marketplace: process.env.MARKETPLACE_URL || "http://localhost:8300",
  execution: process.env.EXECUTION_URL || "http://localhost:8400",
  reputation: process.env.REPUTATION_URL || "http://localhost:8500",
  recurring: process.env.RECURRING_URL || "http://localhost:8600",
};

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  const results = {};

  await Promise.all(
    Object.entries(SERVICES).map(async ([name, url]) => {
      try {
        const resp = await fetch(`${url}/health`, {
          headers: svcHeaders(),
          signal: AbortSignal.timeout(3000),
        });
        const data = await resp.json();
        results[name] = { status: data.ok === 1 ? "healthy" : "degraded", ...data };
      } catch {
        results[name] = { status: "unreachable", ok: 0 };
      }
    })
  );

  const allHealthy = Object.values(results).every((r) => r.status === "healthy");

  return Response.json({
    ok: allHealthy ? 1 : 0,
    services: results,
    timestamp: new Date().toISOString(),
  });
}
