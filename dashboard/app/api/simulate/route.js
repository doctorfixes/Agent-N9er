const SIMULATION_URL = process.env.SIMULATION_URL || "http://localhost:9100";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

function svcHeaders() {
  const h = {};
  if (SERVICE_TOKEN) h["X-Service-Token"] = SERVICE_TOKEN;
  return h;
}

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const n = searchParams.get("n") || "10";
  try {
    const resp = await fetch(`${SIMULATION_URL}/run?n=${n}`, { headers: svcHeaders() });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Simulation unreachable" }, { status: 502 });
  }
}

export async function POST(request) {
  const { searchParams } = new URL(request.url);
  const n = searchParams.get("n") || "5";
  try {
    const resp = await fetch(`${SIMULATION_URL}/run/live?n=${n}`, {
      method: "POST",
      headers: svcHeaders(),
    });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Live simulation unreachable" }, { status: 502 });
  }
}
