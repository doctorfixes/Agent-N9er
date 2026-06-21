const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET() {
  const headers = {};
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  const resp = await fetch(`${PROSPECTOR_URL}/platforms`, { headers });
  const data = await resp.json();
  return Response.json(data);
}
