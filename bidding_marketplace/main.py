import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("marketplace")

app = FastAPI(title="Verixio Bidding Marketplace")

tasks = []
bids = {}


@app.get("/health")
async def health():
    return {"ok": 1, "service": "marketplace", "task_count": len(tasks)}


@app.post("/publish")
async def publish(task: dict):
    task["status"] = "open"
    task["published_at"] = datetime.now(timezone.utc).isoformat()
    tasks.append(task)
    bids[task["id"]] = []
    logger.info("Published task %s", task.get("id"))
    return {"ok": 1, "task_id": task.get("id")}


@app.get("/feed")
async def feed(status: str = None):
    if status:
        return [t for t in tasks if t.get("status") == status]
    return tasks


@app.post("/bid")
async def submit_bid(bid: dict):
    task_id = bid.get("task_id")
    if not task_id or task_id not in bids:
        raise HTTPException(status_code=404, detail="Task not found")

    bid["submitted_at"] = datetime.now(timezone.utc).isoformat()
    bids[task_id].append(bid)
    logger.info("Bid from agent %s on task %s (confidence=%.2f)",
                bid.get("agent_id"), task_id, bid.get("confidence", 0))
    return {"ok": 1}


@app.get("/bids/{task_id}")
async def get_bids(task_id: str):
    if task_id not in bids:
        raise HTTPException(status_code=404, detail="Task not found")
    return bids[task_id]


@app.post("/award/{task_id}")
async def award_task(task_id: str):
    if task_id not in bids or not bids[task_id]:
        raise HTTPException(status_code=404, detail="No bids for task")

    winning_bid = max(bids[task_id], key=lambda b: b.get("confidence", 0))
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = "awarded"
            t["awarded_to"] = winning_bid["agent_id"]
            break

    logger.info("Task %s awarded to agent %s", task_id, winning_bid["agent_id"])
    return {"ok": 1, "winner": winning_bid}
