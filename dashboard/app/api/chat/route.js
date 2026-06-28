const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8400";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function POST(request) {
  try {
    const body = await request.json();
    const resp = await fetch(`${EXECUTION_URL}/quote`, {
      method: "POST",
      headers: svcHeaders(),
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Execution service unreachable" }, { status: 502 });
  }
}
