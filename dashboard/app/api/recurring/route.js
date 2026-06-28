const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";
const RECURRING_URL = process.env.RECURRING_URL || "http://localhost:8600";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = { "Content-Type": "application/json" };
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET() {
  try {
    const resp = await fetch(`${RECURRING_URL}/rules`, { headers: svcHeaders() });
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return Response.json(data);
  } catch {
    return Response.json([], { status: 502 });
  }
}

export async function POST(request) {
  try {
    const body = await request.json();

    if (body.action === "trigger") {
      const resp = await fetch(`${ORCHESTRATOR_URL}/process-recurring`, {
        method: "POST",
        headers: svcHeaders(),
      });
      let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
      return Response.json(data);
    }

    const resp = await fetch(`${RECURRING_URL}/rules`, {
      method: "POST",
      headers: svcHeaders(),
      body: JSON.stringify(body),
    });
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return Response.json(data);
  } catch {
    return Response.json({ error: "Recurring engine unreachable" }, { status: 502 });
  }
}
