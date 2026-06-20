from fastapi import FastAPI
tasks=[]
app=FastAPI()
@app.post("/publish")
async def p(t):tasks.append(t);return{"ok":1}
@app.get("/feed")
async def f():return tasks
