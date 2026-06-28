import { proxyFetch, svcHeaders } from "../../_proxy";

const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";

export async function GET() {
  return proxyFetch(`${PROSPECTOR_URL}/platforms`, { headers: svcHeaders() });
}
