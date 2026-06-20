from fastapi import FastAPI

app = FastAPI()


@app.post("/rank")
async def rank(task: dict):
    return {
        "id": task["id"],
        "priority_score": len(task["objective"]) * 0.1,
    }
