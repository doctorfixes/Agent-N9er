const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET() {
  try {
    const headers = {};
    if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
    const resp = await fetch(`${PROSPECTOR_URL}/stats`, { headers });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ total: 0, by_status: {} }, { status: 502 });
  }
}
