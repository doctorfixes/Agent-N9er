const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function POST(request) {
  try {
    const body = await request.json();
    const resp = await fetch(`${ORCHESTRATOR_URL}/pipeline`, {
      method: "POST",
      headers: svcHeaders(),
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Pipeline unreachable" }, { status: 502 });
  }
}
