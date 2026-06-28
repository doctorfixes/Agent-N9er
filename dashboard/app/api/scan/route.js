import { proxyFetch, svcHeaders } from "../_proxy";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";

export async function GET() {
  return proxyFetch(`${ORCHESTRATOR_URL}/scan/status`, { headers: svcHeaders() });
}

export async function POST() {
  return proxyFetch(`${ORCHESTRATOR_URL}/scan/trigger`, {
    method: "POST",
    headers: svcHeaders(),
  });
}
