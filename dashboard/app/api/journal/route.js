const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    if (searchParams.get("limit")) params.set("limit", searchParams.get("limit"));
    if (searchParams.get("offset")) params.set("offset", searchParams.get("offset"));
    if (searchParams.get("severity")) params.set("severity", searchParams.get("severity"));
    if (searchParams.get("event")) params.set("event", searchParams.get("event"));
    const resp = await fetch(`${ORCHESTRATOR_URL}/journal?${params}`, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Orchestrator unreachable" }, { status: 502 });
  }
}
