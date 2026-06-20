from fastapi import FastAPI
import uuid
app=FastAPI()
@app.post("/normalize")
async def n(t: dict):
 return{"id":str(uuid.uuid4()),"objective":t.get("objective",""),"inputs":t.get("inputs",{}),"raw":t}
