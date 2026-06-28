import { proxyFetch, svcHeaders } from "../../_proxy";

const EXECUTION_URL = process.env.EXECUTION_URL || "http://localhost:8400";

export async function GET(request, { params }) {
  const { taskId } = await params;
  return proxyFetch(
    `${EXECUTION_URL}/executions/${taskId}/output`,
    { headers: svcHeaders() }
  );
}
