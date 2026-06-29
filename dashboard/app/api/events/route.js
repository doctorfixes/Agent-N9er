const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const endpoint = searchParams.get("endpoint") || "recent";

  const urls = {
    recent: `${ORCHESTRATOR_URL}/events/recent?limit=${searchParams.get("limit") || 50}`,
    stats: `${ORCHESTRATOR_URL}/events/stats`,
    subscriptions: `${ORCHESTRATOR_URL}/events/subscriptions`,
    momentum: `${ORCHESTRATOR_URL}/pipeline/momentum`,
  };

  const url = urls[endpoint];
  if (!url) {
    return Response.json({ error: "Unknown endpoint" }, { status: 400 });
  }

  try {
    const resp = await fetch(url, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "orchestrator unreachable" }, { status: 502 });
  }
}
