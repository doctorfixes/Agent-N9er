const BILLING_URL = process.env.BILLING_URL || "http://localhost:9200";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET() {
  const headers = {};
  if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
  const resp = await fetch(`${BILLING_URL}/revenue`, { headers });
  const data = await resp.json();
  return Response.json(data);
}
