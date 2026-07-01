const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8700";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const days = searchParams.get("days") || "30";
  const headers = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  const resp = await fetch(`${EXECUTION_URL}/analytics?days=${days}`, { headers });
  const data = await resp.json();
  return Response.json(data, { status: resp.status });
}
