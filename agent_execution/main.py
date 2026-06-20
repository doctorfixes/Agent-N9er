from fastapi import FastAPI

app = FastAPI()


@app.post("/execute")
async def execute(_request: dict):
    return {"ok": 1}
