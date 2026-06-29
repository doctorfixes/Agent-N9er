const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function headers() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/scan/status`, { headers: headers() });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ running: false, total_scans: 0, total_discovered: 0, platforms: [] }, { status: 502 });
  }
}

export async function POST() {
  try {
    const resp = await fetch(`${ORCHESTRATOR_URL}/scan/trigger`, {
      method: "POST",
      headers: headers(),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Scan service unreachable" }, { status: 502 });
  }
}
