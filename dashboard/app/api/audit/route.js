const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const params = new URLSearchParams();
    for (const [key, value] of searchParams.entries()) {
      params.set(key, value);
    }
    if (!params.has("limit")) params.set("limit", "50");

    const resp = await fetch(`${ENTERPRISE_URL}/audit/logs?${params.toString()}`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ total: 0, entries: [] }, { status: 502 });
  }
}
