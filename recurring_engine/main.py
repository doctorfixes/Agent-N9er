from fastapi import FastAPI
import uuid
rules=[]
app=FastAPI()
@app.get("/rules")
async def r():return rules
@app.get("/tick")
async def t():return[{"id":str(uuid.uuid4()),"objective":x["objective"]}for x in rules]
