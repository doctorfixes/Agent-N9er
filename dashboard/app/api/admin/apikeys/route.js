const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

export async function GET() {
  try {
    const resp = await fetch(`${ENTERPRISE_URL}/admin/apikeys`);
    const data = await resp.json();
    return Response.json(data);
  } catch {
    return Response.json([], { status: 502 });
  }
}

export async function POST(request) {
  try {
    const body = await request.json();
    const resp = await fetch(`${ENTERPRISE_URL}/admin/apikeys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 502 });
  }
}

export async function DELETE(request) {
  try {
    const { searchParams } = new URL(request.url);
    const keyId = searchParams.get("key_id");
    if (!keyId) {
      return Response.json({ error: "key_id required" }, { status: 400 });
    }
    const resp = await fetch(`${ENTERPRISE_URL}/admin/apikeys/${keyId}`, {
      method: "DELETE",
    });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 502 });
  }
}
