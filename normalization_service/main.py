from fastapi import FastAPI
import uuid

app = FastAPI()


@app.post("/normalize")
async def normalize(task: dict):
    return {
        "id": str(uuid.uuid4()),
        "objective": task.get("objective", ""),
        "inputs": task.get("inputs", {}),
        "raw": task,
    }
