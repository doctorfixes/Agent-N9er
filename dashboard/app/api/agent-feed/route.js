const REGISTRY_URL = process.env.REGISTRY_URL || "http://localhost:9900";
const POLL_INTERVAL = 3000; // ms between polls
const SNAPSHOT_INTERVAL = 30000; // ms between full snapshots

let lastState = {};
let pollCount = 0;

export async function GET() {
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      const sendEvent = (event) => {
        const data = `data: ${JSON.stringify(event)}\n\n`;
        try {
          controller.enqueue(encoder.encode(data));
        } catch {
          // stream closed
        }
      };

      // Initial snapshot
      try {
        const resp = await fetch(`${REGISTRY_URL}/list?limit=200`, {
          signal: AbortSignal.timeout(5000),
        });
        if (resp.ok) {
          const agents = await resp.json();
          const index = {};
          for (const a of agents) index[a.agent_id] = a;
          lastState = index;
          sendEvent({ type: "snapshot", agents, ts: new Date().toISOString() });
          sendEvent({ type: "info", message: `Connected — ${agents.length} agents registered` });
        }
      } catch {
        sendEvent({ type: "error", message: "Cannot reach Agent Registry" });
      }

      const interval = setInterval(async () => {
        pollCount++;

        try {
          const resp = await fetch(`${REGISTRY_URL}/list?limit=200`, {
            signal: AbortSignal.timeout(5000),
          });
          if (!resp.ok) return;

          const agents = await resp.json();
          const newIndex = {};
          for (const a of agents) newIndex[a.agent_id] = a;

          // Detect new agents
          for (const a of agents) {
            if (!lastState[a.agent_id]) {
              sendEvent({
                type: "agent_registered",
                agent_id: a.agent_id,
                agent_type: a.agent_type,
                capabilities: a.capabilities,
                price_per_hour: a.price_per_hour,
                ts: new Date().toISOString(),
              });
            }
          }

          // Detect state changes
          for (const [id, prev] of Object.entries(lastState)) {
            const cur = newIndex[id];
            if (!cur) {
              sendEvent({
                type: "agent_deregistered",
                agent_id: id,
                ts: new Date().toISOString(),
              });
            } else if (cur.state !== prev.state) {
              sendEvent({
                type: "agent_state_change",
                agent_id: id,
                agent_type: cur.agent_type,
                old_state: prev.state,
                new_state: cur.state,
                current_load: cur.current_load,
                ts: new Date().toISOString(),
              });
            } else if (cur.current_load !== prev.current_load) {
              sendEvent({
                type: "agent_load_change",
                agent_id: id,
                agent_type: cur.agent_type,
                state: cur.state,
                load: cur.current_load,
                ts: new Date().toISOString(),
              });
            }
          }

          lastState = newIndex;

          // Periodic full snapshot
          if (pollCount % Math.round(SNAPSHOT_INTERVAL / POLL_INTERVAL) === 0) {
            sendEvent({ type: "snapshot", agents, ts: new Date().toISOString() });
          }
        } catch {
          sendEvent({ type: "error", message: "Poll failed" });
        }
      }, POLL_INTERVAL);

      // Keepalive
      const keepalive = setInterval(() => {
        sendEvent({ type: "keepalive" });
      }, 15000);

      // Cleanup on client disconnect
      controller.signal.addEventListener("abort", () => {
        clearInterval(interval);
        clearInterval(keepalive);
      });
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}