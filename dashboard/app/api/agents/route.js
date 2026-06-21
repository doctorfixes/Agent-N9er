const REPUTATION_URL = process.env.REPUTATION_URL || "http://localhost:8500";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  try {
    const resp = await fetch(`${REPUTATION_URL}/ledger`, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({}, { status: 502 });
  }
}
