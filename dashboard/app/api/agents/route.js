const REPUTATION_URL = process.env.REPUTATION_URL || "http://localhost:8500";

export async function GET() {
  try {
    const resp = await fetch(`${REPUTATION_URL}/ledger`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({}, { status: 502 });
  }
}
