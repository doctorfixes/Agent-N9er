const BROWSER_SERVICE_URL = process.env.BROWSER_SERVICE_URL || "http://localhost:8001";

export async function POST(request, { params }) {
  const { name } = await params;
  const body = await request.json().catch(() => ({}));
  const action = body.action === "deactivate" ? "deactivate" : "activate";
  try {
    const resp = await fetch(`${BROWSER_SERVICE_URL}/watchers/${name}/${action}`, {
      method: "POST",
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.ok ? 200 : resp.status });
  } catch {
    return Response.json({ error: "Browser service unreachable" }, { status: 502 });
  }
}
