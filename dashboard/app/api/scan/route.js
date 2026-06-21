const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function headers() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  const resp = await fetch(`${ORCHESTRATOR_URL}/scan/status`, { headers: headers() });
  const data = await resp.json();
  return Response.json(data, { status: resp.status });
}

export async function POST() {
  const resp = await fetch(`${ORCHESTRATOR_URL}/scan/trigger`, {
    method: "POST",
    headers: headers(),
  });
  const data = await resp.json();
  return Response.json(data, { status: resp.status });
}
