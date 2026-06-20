from fastapi import FastAPI
app=FastAPI()
@app.post("/execute")
async def e(r: dict):return{"ok":1}
