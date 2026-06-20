import os
import textwrap

FILES = {
"docker-compose.yml": """version:\"3.9\"
services:
 orchestrator:{build:\"./orchestrator\",ports:[\"9000:9000\"]}
 normalization-service:{build:\"./normalization_service\",ports:[\"8100:8100\"]}
 ranking-engine:{build:\"./ranking_engine\",ports:[\"8200:8200\"]}
 bidding-marketplace:{build:\"./bidding_marketplace\",ports:[\"8300:8300\"]}
 agent-execution:{build:\"./agent_execution\",ports:[\"8400:8400\"]}
 reputation-ledger:{build:\"./reputation_ledger\",ports:[\"8500:8500\"]}
 recurring-engine:{build:\"./recurring_engine\",ports:[\"8600:8600\"]}
 browser-service:{build:\"./browser_service\",ports:[\"8001:8001\"]}
 simulation-engine:{build:\"./simulation\",ports:[\"9100:9100\"]}
 dashboard:{build:\"./dashboard\",ports:[\"3000:3000\"]}""",

"secrets_vault.json": """{}""",

"orchestrator/main.py": """from fastapi import FastAPI
import httpx
app=FastAPI()
@app.post(\"/pipeline\")
async def p(t):
 async with httpx.AsyncClient()as c:
  n=(await c.post(\"http://normalization-service:8100/normalize\",json=t)).json()
  r=(await c.post(\"http://ranking-engine:8200/rank\",json=n)).json()
  await c.post(\"http://bidding-marketplace:8300/publish\",json={\"id\":r[\"id\"],\"objective\":n[\"objective\"],\"priority_score\":r[\"priority_score\"]})
  return{\"status\":\"task_published\",\"normalized\":n,\"ranked\":r}""",

"normalization_service/main.py": """from fastapi import FastAPI
import uuid
app=FastAPI()
@app.post(\"/normalize\")
async def n(t):
 return{\"id\":str(uuid.uuid4()),\"objective\":t.get(\"objective\",\"\"),\"inputs\":t.get(\"inputs\",{}),\"raw\":t}""",

"ranking_engine/main.py": """from fastapi import FastAPI
app=FastAPI()
@app.post(\"/rank\")
async def r(t):
 return{\"id\":t[\"id\"],\"priority_score\":len(t[\"objective\"])*0.1}""",

"bidding_marketplace/main.py": """from fastapi import FastAPI
tasks=[]
app=FastAPI()
@app.post(\"/publish\")
async def p(t):tasks.append(t);return{\"ok\":1}
@app.get(\"/feed\")
async def f():return tasks""",

"agent_execution/main.py": """from fastapi import FastAPI
app=FastAPI()
@app.post(\"/execute\")
async def e(r):return{\"ok\":1}""",

"reputation_ledger/main.py": """from fastapi import FastAPI
ledger={}
app=FastAPI()
@app.post(\"/update\")
async def u(r):
 a=r[\"agent_id\"]
 ledger[a]=ledger.get(a,{\"success\":0,\"fail\":0})
 ledger[a][\"success\"]+=1 if r[\"success\"]else 0
 ledger[a][\"fail\"]+=0 if r[\"success\"]else 1
 return{\"ok\":1}
@app.get(\"/ledger\")
async def l():return ledger""",

"recurring_engine/main.py": """from fastapi import FastAPI
import uuid
rules=[]
app=FastAPI()
@app.get(\"/rules\")
async def r():return rules
@app.get(\"/tick\")
async def t():return[{\"id\":str(uuid.uuid4()),\"objective\":x[\"objective\"]}for x in rules]""",

"browser_service/gmail_watcher.py": """async def watch_gmail(c,a,t):return[{\"type\":\"new_unread_email\"}]""",
"browser_service/drive_watcher.py": """async def watch_drive(c,a,t):return[{\"type\":\"new_file\"}]""",
"browser_service/slack_watcher.py": """async def watch_slack(c,a,t):return[{\"type\":\"unread_message\"}]""",
"browser_service/notion_watcher.py": """async def watch_notion(c,a,t):return[{\"type\":\"page_updated\"}]""",
"browser_service/airtable_watcher.py": """async def watch_airtable(c,a,t):return[{\"type\":\"new_record\"}]""",
"browser_service/asana_watcher.py": """async def watch_asana(c,a,t):return[{\"type\":\"new_task\"}]""",
"browser_service/trello_watcher.py": """async def watch_trello(c,a,t):return[{\"type\":\"new_card\"}]""",
"browser_service/github_watcher.py": """async def watch_github(c,a,t):return[{\"type\":\"new_issue\"}]""",

"simulation/engine/task_generator.py": """import uuid
def gen():return{\"id\":str(uuid.uuid4()),\"objective\":\"Task\"}""",

"simulation/engine/market.py": """def score(b):return b[\"confidence\"]
def winner(bs):return max(bs,key=score)""",

"simulation/engine/simulator.py": """from .task_generator import gen
from .market import winner
def run(agents,n=10):
 out=[]
 for _ in range(n):
  t=gen()
  bs=[a.bid(t)for a in agents]
  w=winner(bs)
  a=[x for x in agents if x.agent_id==w[\"agent_id\"]][0]
  s,d=a.execute(t)
  a.update_reputation(s,d)
  out.append({\"task\":t,\"winner\":w,\"success\":s,\"duration\":d})
 return out""",

"simulation/agents/base_agent.py": """import uuid
class BaseAgent:
 def __init__(s,p):s.agent_id=str(uuid.uuid4());s.p=p;s.r=0.5
 def update_reputation(s,x,d):s.r=min(1,s.r+0.01)if x else max(0,s.r-0.02)""",

"simulation/agents/speed_demon.py": """from .base_agent import BaseAgent
import random
class SpeedDemon(BaseAgent):
 def bid(s,t):return{\"agent_id\":s.agent_id,\"price\":0.1,\"eta_minutes\":1,\"confidence\":0.7}
 def execute(s,t):return random.random()<0.85,2""",

"simulation/agents/precision_specialist.py": """from .base_agent import BaseAgent
import random
class PrecisionSpecialist(BaseAgent):
 def bid(s,t):return{\"agent_id\":s.agent_id,\"price\":0.4,\"eta_minutes\":6,\"confidence\":0.95}
 def execute(s,t):return random.random()<0.98,6""",

"integration/watcher_router.py": """import httpx
async def f(tc):
 async with httpx.AsyncClient()as c:await c.post(\"http://orchestrator:9000/pipeline\",json=tc)""",

"integration/pipeline_events.py": """import httpx
async def s():
 async with httpx.AsyncClient()as c:
  t=(await c.get(\"http://bidding-marketplace:8300/feed\")).json()
  a=(await c.get(\"http://reputation-ledger:8500/ledger\")).json()
  return{\"tasks\":t,\"agents\":a}""",

"dashboard/app/layout.tsx": """export default function R({children}){return<html><body><nav><a href=\"/tasks\">Tasks</a></nav><main>{children}</main></body></html>}""",

"dashboard/app/tasks/page.tsx": """\"use client\";import useSWR from\"swr\";export default function P(){const{data}=useSWR(\"/api/tasks\",u=>fetch(u).then(r=>r.json()));return<div>{JSON.stringify(data)}</div>}""",

"dashboard/app/agents/page.tsx": """\"use client\";import useSWR from\"swr\";export default function P(){const{data}=useSWR(\"/api/agents\",u=>fetch(u).then(r=>r.json()));return<div>{JSON.stringify(data)}</div>}""",
}


for path, code in FILES.items():
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(code).strip() + "\n")
    print("Wrote:", path)

print("\nVerixio monorepo generated successfully.")
