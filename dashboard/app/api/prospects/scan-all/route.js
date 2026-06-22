const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function POST(request) {
  const body = await request.json().catch(() => ({}));
  const headers = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  const resp = await fetch(`${PROSPECTOR_URL}/scan/multi`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  return Response.json(data, { status: resp.status });
}
