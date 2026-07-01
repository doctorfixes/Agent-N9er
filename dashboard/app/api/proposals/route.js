const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8700";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function POST(request) {
  const body = await request.json();
  const headers = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  const resp = await fetch(`${EXECUTION_URL}/proposal`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  return Response.json(data, { status: resp.status });
}
