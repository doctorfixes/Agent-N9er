import { proxyFetch, svcHeaders } from "../_proxy";

const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const status = searchParams.get("status");
  const qs = status ? `?status=${status}` : "";
  return proxyFetch(`${PROSPECTOR_URL}/prospects${qs}`, { headers: svcHeaders() });
}
