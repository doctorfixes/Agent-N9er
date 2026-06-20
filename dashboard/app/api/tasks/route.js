const MARKETPLACE_URL = process.env.MARKETPLACE_URL || "http://localhost:8300";

export async function GET() {
  try {
    const resp = await fetch(`${MARKETPLACE_URL}/feed`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json([], { status: 502 });
  }
}
