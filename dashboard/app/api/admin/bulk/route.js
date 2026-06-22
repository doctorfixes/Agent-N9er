const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

export async function POST(request) {
  try {
    const body = await request.json();
    const type = body.type || "tasks";

    const resp = await fetch(`${ENTERPRISE_URL}/bulk/${type}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 502 });
  }
}
