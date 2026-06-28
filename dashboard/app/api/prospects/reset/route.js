import { proxyFetch, svcHeaders } from "../../_proxy";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";

export async function POST(request) {
  const body = await request.json();
  return proxyFetch(
    `${ORCHESTRATOR_URL}/reset-prospect`,
    { method: "POST", headers: { ...svcHeaders(), "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
}
