import { proxyFetch, svcHeaders } from "../_proxy";

const PROSPECTOR_URL = process.env.PROSPECTOR_URL || "http://localhost:8900";

export async function POST(request) {
  const body = await request.json();
  return proxyFetch(
    `${PROSPECTOR_URL}/freelancer/bid`,
    { method: "POST", headers: { ...svcHeaders(), "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
}
