const BROWSER_SERVICE_URL = process.env.BROWSER_SERVICE_URL || "http://localhost:8001";

export async function GET() {
  try {
    const resp = await fetch(`${BROWSER_SERVICE_URL}/watchers`);
    let data; try { data = JSON.parse(await resp.text()); } catch { data = { error: "Empty response" }; }
    return Response.json(data);
  } catch {
    return Response.json({ available: [], active: [] }, { status: 502 });
  }
}
