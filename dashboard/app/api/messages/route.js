import { proxyFetch, svcHeaders } from "../_proxy";

const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";

export async function GET(request) {
  const { searchParams } = new URL(request.url);
  const unread = searchParams.get("unread_only") || "false";
  const limit = searchParams.get("limit") || "20";
  return proxyFetch(
    `${PROSPECTOR_URL}/freelancer/messages?unread_only=${unread}&limit=${limit}`,
    { headers: svcHeaders() }
  );
}
