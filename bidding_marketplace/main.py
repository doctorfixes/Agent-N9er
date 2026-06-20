from fastapi import FastAPI

app = FastAPI()
tasks = []


@app.post("/publish")
async def publish(task: dict):
    tasks.append(task)
    return {"ok": 1}


@app.get("/feed")
async def feed():
    return tasks
