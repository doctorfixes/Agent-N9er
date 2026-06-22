const ENTERPRISE_URL = process.env.ENTERPRISE_URL || "http://localhost:9300";

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const type = searchParams.get("type") || "audit";
    const params = new URLSearchParams();
    for (const [key, value] of searchParams.entries()) {
      if (key !== "type") params.set(key, value);
    }

    const resp = await fetch(`${ENTERPRISE_URL}/export/${type}?${params.toString()}`);

    if (!resp.ok) {
      return Response.json({ error: "Export failed" }, { status: resp.status });
    }

    const csv = await resp.text();
    return new Response(csv, {
      headers: {
        "Content-Type": "text/csv",
        "Content-Disposition": `attachment; filename=${type}_export.csv`,
      },
    });
  } catch (e) {
    return Response.json({ error: e.message }, { status: 502 });
  }
}
