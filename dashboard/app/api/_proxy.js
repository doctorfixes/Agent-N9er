export async function proxyFetch(url, options = {}) {
  try {
    const resp = await fetch(url, options);
    const text = await resp.text();
    try {
      const data = JSON.parse(text);
      return Response.json(data, { status: resp.status });
    } catch {
      return Response.json({ error: text || "Empty response" }, { status: resp.status || 502 });
    }
  } catch (e) {
    return Response.json({ error: e.message || "Service unavailable" }, { status: 502 });
  }
}

export function svcHeaders(extra = {}) {
  const h = { ...extra };
  const token = process.env.SERVICE_TOKEN || "";
  if (token) h["X-Service-Token"] = token;
  return h;
}
