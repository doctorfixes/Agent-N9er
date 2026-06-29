const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function POST(request) {
  try {
    const body = await request.json();
    const { bid_id } = body;
    if (!bid_id) {
      return Response.json({ error: "bid_id required" }, { status: 400 });
    }
    const resp = await fetch(`${PROSPECTOR_URL}/bids/${bid_id}/approve`, {
      method: "POST",
      headers: svcHeaders(),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Prospector service unreachable" }, { status: 502 });
  }
}
