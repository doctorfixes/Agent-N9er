const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const prospectId = searchParams.get("prospect_id");
    if (!prospectId) return Response.json({ error: "prospect_id required" }, { status: 400 });
    const resp = await fetch(`${PROSPECTOR_URL}/prospects/${prospectId}/milestones`, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Prospector unreachable" }, { status: 502 });
  }
}
