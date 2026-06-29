const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8400";
const SERVICE_TOKEN = process.env.SERVICE_TOKEN || "";

export async function GET(request) {
  try {
    const { searchParams } = new URL(request.url);
    const taskId = searchParams.get("task_id");
    if (!taskId) {
      return Response.json({ error: "task_id required" }, { status: 400 });
    }
    const headers = {};
    if (SERVICE_TOKEN) headers["X-Service-Token"] = SERVICE_TOKEN;
    const resp = await fetch(`${EXECUTION_URL}/executions/${taskId}/output`, { headers });
    const data = await resp.json();
    return Response.json(data, { status: resp.status });
  } catch {
    return Response.json({ error: "Execution service unreachable" }, { status: 502 });
  }
}
