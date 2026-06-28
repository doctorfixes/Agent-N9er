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
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return Response.json(data);
  } catch {
    return Response.json([], { status: 502 });
  }
}
