from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "verixio_full.md"

FILES = {
    "docker-compose.yml": '''
version: "3.9"
services:
  orchestrator:
    build: ./orchestrator
    ports: ["9000:9000"]
  normalization-service:
    build: ./normalization_service
    ports: ["8100:8100"]
  ranking-engine:
    build: ./ranking_engine
    ports: ["8200:8200"]
  bidding-marketplace:
    build: ./bidding_marketplace
    ports: ["8300:8300"]
  agent-execution:
    build: ./agent_execution
    ports: ["8400:8400"]
  reputation-ledger:
    build: ./reputation_ledger
    ports: ["8500:8500"]
  recurring-engine:
    build: ./recurring_engine
    ports: ["8600:8600"]
  browser-service:
    build: ./browser_service
    ports: ["8001:8001"]
  simulation-engine:
    build: ./simulation
    ports: ["9100:9100"]
  dashboard:
    build: ./dashboard
    ports: ["3000:3000"]
''',
    "package.json": '''
{}
''',
    "orchestrator/main.py": '''
from fastapi import FastAPI
import httpx

app = FastAPI()


@app.post("/pipeline")
async def pipeline(task: dict):
    async with httpx.AsyncClient() as client:
        normalized = (
            await client.post(
                "http://normalization-service:8100/normalize",
                json=task,
            )
        ).json()
        ranked = (
            await client.post(
                "http://ranking-engine:8200/rank",
                json=normalized,
            )
        ).json()
        await client.post(
            "http://bidding-marketplace:8300/publish",
            json={
                "id": ranked["id"],
                "objective": normalized["objective"],
                "priority_score": ranked["priority_score"],
            },
        )
        return {
            "status": "task_published",
            "normalized": normalized,
            "ranked": ranked,
        }
''',
    "orchestrator/requirements.txt": '''
fastapi
uvicorn
httpx
''',
    "orchestrator/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9000"]
''',
    "normalization_service/main.py": '''
from fastapi import FastAPI
import uuid

app = FastAPI()


@app.post("/normalize")
async def normalize(task: dict):
    return {
        "id": str(uuid.uuid4()),
        "objective": task.get("objective", ""),
        "inputs": task.get("inputs", {}),
        "raw": task,
    }
''',
    "normalization_service/requirements.txt": "fastapi\nuvicorn\n",
    "normalization_service/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
''',
    "ranking_engine/main.py": '''
from fastapi import FastAPI

app = FastAPI()


@app.post("/rank")
async def rank(task: dict):
    return {
        "id": task["id"],
        "priority_score": len(task["objective"]) * 0.1,
    }
''',
    "ranking_engine/requirements.txt": "fastapi\nuvicorn\n",
    "ranking_engine/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8200"]
''',
    "bidding_marketplace/main.py": '''
from fastapi import FastAPI

app = FastAPI()
tasks = []


@app.post("/publish")
async def publish(task: dict):
    tasks.append(task)
    return {"ok": 1}


@app.get("/feed")
async def feed():
    return tasks
''',
    "bidding_marketplace/requirements.txt": "fastapi\nuvicorn\n",
    "bidding_marketplace/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8300"]
''',
    "agent_execution/main.py": '''
from fastapi import FastAPI

app = FastAPI()


@app.post("/execute")
async def execute(_request: dict):
    return {"ok": 1}
''',
    "agent_execution/requirements.txt": "fastapi\nuvicorn\n",
    "agent_execution/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8400"]
''',
    "reputation_ledger/main.py": '''
from fastapi import FastAPI

app = FastAPI()
ledger = {}


@app.post("/update")
async def update(result: dict):
    agent_id = result["agent_id"]
    ledger[agent_id] = ledger.get(agent_id, {"success": 0, "fail": 0})
    ledger[agent_id]["success"] += 1 if result["success"] else 0
    ledger[agent_id]["fail"] += 0 if result["success"] else 1
    return {"ok": 1}


@app.get("/ledger")
async def get_ledger():
    return ledger
''',
    "reputation_ledger/requirements.txt": "fastapi\nuvicorn\n",
    "reputation_ledger/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8500"]
''',
    "recurring_engine/main.py": '''
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
''',
    "recurring_engine/requirements.txt": "fastapi\nuvicorn\n",
    "recurring_engine/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8600"]
''',
    "browser_service/watchers/gmail_watcher.py": '''
async def watch_gmail(context, account, token):
    return [{"type": "new_unread_email"}]
''',
    "browser_service/watchers/drive_watcher.py": '''
async def watch_drive(context, account, token):
    return [{"type": "new_file"}]
''',
    "browser_service/watchers/slack_watcher.py": '''
async def watch_slack(context, account, token):
    return [{"type": "unread_message"}]
''',
    "browser_service/watchers/notion_watcher.py": '''
async def watch_notion(context, account, token):
    return [{"type": "page_updated"}]
''',
    "browser_service/watchers/airtable_watcher.py": '''
async def watch_airtable(context, account, token):
    return [{"type": "new_record"}]
''',
    "browser_service/watchers/asana_watcher.py": '''
async def watch_asana(context, account, token):
    return [{"type": "new_task"}]
''',
    "browser_service/watchers/trello_watcher.py": '''
async def watch_trello(context, account, token):
    return [{"type": "new_card"}]
''',
    "browser_service/watchers/github_watcher.py": '''
async def watch_github(context, account, token):
    return [{"type": "new_issue"}]
''',
    "browser_service/watchers/__init__.py": '''
from .gmail_watcher import watch_gmail
from .drive_watcher import watch_drive
from .slack_watcher import watch_slack
from .notion_watcher import watch_notion
from .airtable_watcher import watch_airtable
from .asana_watcher import watch_asana
from .trello_watcher import watch_trello
from .github_watcher import watch_github
''',
    "browser_service/main.py": '''
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health():
    return {"ok": 1}
''',
    "browser_service/requirements.txt": "fastapi\nuvicorn\n",
    "browser_service/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
''',
    "simulation/task_generator.py": '''
import uuid


def gen():
    return {"id": str(uuid.uuid4()), "objective": "Task"}
''',
    "simulation/market.py": '''
def score(bid):
    return bid["confidence"]


def winner(bids):
    return max(bids, key=score)
''',
    "simulation/agent_personalities/base_agent.py": '''
import uuid


class BaseAgent:
    def __init__(self, profile: str):
        self.agent_id = str(uuid.uuid4())
        self.profile = profile
        self.reputation = 0.5

    def update_reputation(self, success: bool, _duration: int):
        self.reputation = min(1, self.reputation + 0.01) if success else max(0, self.reputation - 0.02)
''',
    "simulation/agent_personalities/speed_demon.py": '''
import random

from .base_agent import BaseAgent


class SpeedDemon(BaseAgent):
    def bid(self, _task: dict):
        return {
            "agent_id": self.agent_id,
            "price": 0.1,
            "eta_minutes": 1,
            "confidence": 0.7,
        }

    def execute(self, _task: dict):
        return random.random() < 0.85, 2
''',
    "simulation/agent_personalities/precision_specialist.py": '''
import random

from .base_agent import BaseAgent


class PrecisionSpecialist(BaseAgent):
    def bid(self, _task: dict):
        return {
            "agent_id": self.agent_id,
            "price": 0.4,
            "eta_minutes": 6,
            "confidence": 0.95,
        }

    def execute(self, _task: dict):
        return random.random() < 0.98, 6
''',
    "simulation/agent_personalities/__init__.py": '''
from .speed_demon import SpeedDemon
from .precision_specialist import PrecisionSpecialist
''',
    "simulation/runner.py": '''
from .task_generator import gen
from .market import winner


def run(agents, n=10):
    out = []
    for _ in range(n):
        task = gen()
        bids = [agent.bid(task) for agent in agents]
        winning_bid = winner(bids)
        selected = [agent for agent in agents if agent.agent_id == winning_bid["agent_id"]][0]
        success, duration = selected.execute(task)
        selected.update_reputation(success, duration)
        out.append(
            {
                "task": task,
                "winner": winning_bid,
                "success": success,
                "duration": duration,
            }
        )
    return out
''',
    "simulation/main.py": '''
from fastapi import FastAPI

from agent_personalities import SpeedDemon, PrecisionSpecialist
from runner import run

app = FastAPI()


@app.get("/run")
async def run_simulation(n: int = 10):
    agents = [SpeedDemon("speed"), PrecisionSpecialist("precision")]
    return {"results": run(agents, n=n)}
''',
    "simulation/requirements.txt": "fastapi\nuvicorn\n",
    "simulation/Dockerfile": '''
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9100"]
''',
    "integration_layer/submit_task.py": '''
import httpx


async def forward_task(task_config: dict):
    async with httpx.AsyncClient() as client:
        await client.post("http://orchestrator:9000/pipeline", json=task_config)
''',
    "integration_layer/dashboard_summary.py": '''
import httpx


async def summary():
    async with httpx.AsyncClient() as client:
        tasks = (await client.get("http://bidding-marketplace:8300/feed")).json()
        agents = (await client.get("http://reputation-ledger:8500/ledger")).json()
        return {"tasks": tasks, "agents": agents}
''',
    "dashboard/package.json": '''
{
  "name": "verixio-dashboard",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "next": "15.3.3",
    "react": "19.1.0",
    "react-dom": "19.1.0",
    "swr": "2.3.3"
  }
}
''',
    "dashboard/next.config.js": "module.exports = {};\n",
    "dashboard/app/layout.js": '''
export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
''',
    "dashboard/app/page.js": '''
export default function HomePage() {
  return <main>Verixio Dashboard</main>;
}
''',
    "dashboard/app/tasks/page.js": '''
"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

export default function TasksPage() {
  const { data } = useSWR("/api/tasks", fetcher);
  return <pre>{JSON.stringify(data ?? [], null, 2)}</pre>;
}
''',
    "dashboard/app/agents/page.js": '''
"use client";

import useSWR from "swr";

const fetcher = (url) => fetch(url).then((res) => res.json());

export default function AgentsPage() {
  const { data } = useSWR("/api/agents", fetcher);
  return <pre>{JSON.stringify(data ?? {}, null, 2)}</pre>;
}
''',
    "dashboard/Dockerfile": '''
FROM node:22-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
''',
    ".gitignore": '''
__pycache__/
*.pyc
.pytest_cache/
node_modules/
.next/
''',
}


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"Missing source bundle: {SOURCE}")
    text = SOURCE.read_text(encoding="utf-8")
    if "VERIXIO" not in text:
        raise SystemExit("The source bundle does not look like a Verixio payload.")

    written = []
    for relative_path, content in FILES.items():
        target = ROOT / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
        written.append(relative_path)

    print(f"Expanded {len(written)} files from {SOURCE.name}")


if __name__ == "__main__":
    main()
