from fastapi import FastAPI
app=FastAPI()
@app.post("/execute")
async def e(r):return{"ok":1}
