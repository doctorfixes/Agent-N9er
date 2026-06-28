const BILLING_URL = process.env.BILLING_URL || "http://localhost:9200";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const status = searchParams.get("status");
    const qs = status ? `?status=${status}` : "";
    const resp = await fetch(`${BILLING_URL}/invoices${qs}`, { headers: svcHeaders() });
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return Response.json(data);
  } catch (e) {
    return Response.json({ error: e.message || "Service unavailable" }, { status: 502 });
  }
}
