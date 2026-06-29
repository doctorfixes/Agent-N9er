const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function POST(request) {
  try {
    const body = await request.json().catch(() => ({}));
    const resp = await fetch(`${ORCHESTRATOR_URL}/prospects/unstick`, {
      method: "POST",
      headers: svcHeaders(),
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Orchestrator unreachable" }, { status: 502 });
  }
}
