from fastapi import FastAPI
ledger={}
app=FastAPI()
@app.post("/update")
async def u(r: dict):
 a=r["agent_id"]
 ledger[a]=ledger.get(a,{"success":0,"fail":0})
 ledger[a]["success"]+=1 if r["success"]else 0
 ledger[a]["fail"]+=0 if r["success"]else 1
 return{"ok":1}
@app.get("/ledger")
async def l():return ledger
