const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function headers() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function POST() {
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/dispatch`, {
      method: "POST",
      headers: headers(),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Orchestrator unreachable" }, { status: 502 });
  }
}

export async function GET() {
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/dispatch/status`, { headers: headers() });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ auto_dispatch_enabled: false }, { status: 502 });
  }
}
