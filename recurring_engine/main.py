from fastapi import FastAPI
import uuid

app = FastAPI()
rules = []


@app.get("/rules")
async def get_rules():
    return rules


@app.get("/tick")
async def tick():
    return [{"id": str(uuid.uuid4()), "objective": x["objective"]} for x in rules]
