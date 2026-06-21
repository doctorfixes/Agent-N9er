const BILLING_URL = process.env.BILLING_URL || "http://localhost:9200";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const days = searchParams.get("days") || "30";
  const headers = {};
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  try {
    const resp = await fetch(`${BILLING_URL}/funnel?days=${days}`, { headers });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "billing service unreachable" }, { status: 502 });
  }
}
