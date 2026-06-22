const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

export async function GET() {
  try {
    const resp = await fetch(`${ENTERPRISE_URL}/system/health`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ overall: "unreachable", services: {} }, { status: 502 });
  }
}
