from fastapi import FastAPI

app = FastAPI()
ledger = {}


@app.post("/update")
async def update(result: dict):
    agent_id = result["agent_id"]
    ledger[agent_id] = ledger.get(agent_id, {"success": 0, "fail": 0})
    ledger[agent_id]["success"] += 1 if result["success"] else 0
    ledger[agent_id]["fail"] += 0 if result["success"] else 1
    return {"ok": 1}


@app.get("/ledger")
async def get_ledger():
    return ledger
