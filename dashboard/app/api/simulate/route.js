const SIMULATION_URL = process.env.SIMULATION_URL || "http://localhost:9100";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const n = searchParams.get("n") || "10";
  try {
    const resp = await fetch(`${SIMULATION_URL}/run?n=${n}`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "Simulation unreachable" }, { status: 502 });
  }
}
