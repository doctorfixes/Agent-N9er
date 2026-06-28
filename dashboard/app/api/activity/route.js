import { proxyFetch, svcHeaders } from "../_proxy";

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL || "http://localhost:9000";

export async function GET(req) {
  const { searchParams } = new URL(req.url);
  const limit = searchParams.get("limit") || "50";
  const type = searchParams.get("type") || "";
  const qs = `?limit=${limit}${type ? `&event_type=${type}` : ""}`;
  return proxyFetch(
    `${ORCHESTRATOR_URL}/activity${qs}`,
    { headers: svcHeaders() }
  );
}
