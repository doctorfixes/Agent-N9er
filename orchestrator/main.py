from fastapi import FastAPI
import httpx
app=FastAPI()
@app.post("/pipeline")
async def p(t: dict):
 async with httpx.AsyncClient()as c:
  n=(await c.post("http://normalization-service:8100/normalize",json=t)).json()
  r=(await c.post("http://ranking-engine:8200/rank",json=n)).json()
  await c.post("http://bidding-marketplace:8300/publish",json={"id":r["id"],"objective":n["objective"],"priority_score":r["priority_score"]})
  return{"status":"task_published","normalized":n,"ranked":r}
