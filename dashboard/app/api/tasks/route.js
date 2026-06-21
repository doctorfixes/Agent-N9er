const MARKETPLACE_URL = process.env.MARKETPLACE_URL || "http://localhost:8300";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  try {
    const resp = await fetch(`${MARKETPLACE_URL}/feed`, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json([], { status: 502 });
  }
}
