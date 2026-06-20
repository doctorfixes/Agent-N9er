from fastapi import FastAPI
app=FastAPI()
@app.post("/rank")
async def r(t):
 return{"id":t["id"],"priority_score":len(t["objective"])*0.1}
