const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function PATCH(request) {
  try {
    const body = await request.json();
    const { prospect_id, status } = body;
    if (!prospect_id || !status) {
      return Response.json({ error: "prospect_id and status required" }, { status: 400 });
    }
    const resp = await fetch(`${PROSPECTOR_URL}/prospects/${prospect_id}`, {
      method: "PATCH",
      headers: svcHeaders(),
      body: JSON.stringify({ status }),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Prospector service unreachable" }, { status: 502 });
  }
}
