const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8400";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function POST(request) {
  try {
    const body = await request.json();
    const headers = { "Content-Type": "application/json" };
    if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
    const resp = await fetch(`${EXECUTION_URL}/proposal`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch (e) {
    return Response.json({ ok: 0, error: e.message || "Proposal generation failed" }, { status: 502 });
  }
}
