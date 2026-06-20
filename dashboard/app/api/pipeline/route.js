const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";

export async function POST(request) {
  try {
    const body = await request.json();
    const resp = await fetch(`${ORCHESTRATOR_URL}/pipeline`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Pipeline unreachable" }, { status: 502 });
  }
}
