import { proxyFetch, svcHeaders } from "../../_proxy";

const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";

export async function GET(request, { params }) {
  const { threadId } = await params;
  return proxyFetch(
    `${PROSPECTOR_URL}/freelancer/thread/${threadId}?limit=50`,
    { headers: svcHeaders() }
  );
}

export async function POST(request, { params }) {
  const { threadId } = await params;
  const body = await request.json();
  return proxyFetch(
    `${PROSPECTOR_URL}/freelancer/thread/${threadId}/reply`,
    { method: "POST", headers: { ...svcHeaders(), "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
}
