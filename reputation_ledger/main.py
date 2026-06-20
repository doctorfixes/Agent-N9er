import logging

from fastapi import FastAPI, HTTPException

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reputation")

app = FastAPI(title="Verixio Reputation Ledger")

ledger = {}


@app.get("/health")
async def health():
    return {"ok": 1, "service": "reputation", "agent_count": len(ledger)}


@app.post("/update")
async def update(record: dict):
    agent_id = record.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="Missing agent_id")

    if agent_id not in ledger:
        ledger[agent_id] = {"success": 0, "fail": 0, "score": 0.5}

    entry = ledger[agent_id]
    if record.get("success"):
        entry["success"] += 1
        entry["score"] = min(1.0, entry["score"] + 0.01)
    else:
        entry["fail"] += 1
        entry["score"] = max(0.0, entry["score"] - 0.02)

    logger.info("Agent %s reputation: %.2f (W:%d L:%d)",
                agent_id, entry["score"], entry["success"], entry["fail"])
    return {"ok": 1, "agent_id": agent_id, "reputation": entry}


@app.get("/ledger")
async def get_ledger():
    return ledger


@app.get("/agent/{agent_id}")
async def get_agent(agent_id: str):
    if agent_id not in ledger:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_id": agent_id, **ledger[agent_id]}
