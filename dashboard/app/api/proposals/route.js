import { proxyFetch, svcHeaders } from "../_proxy";

const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8400";

export async function POST(request) {
  const body = await request.json();
  return proxyFetch(`${EXECUTION_URL}/proposal`, {
    method: "POST",
    headers: svcHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
}
