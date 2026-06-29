import os
import sys
import re
import json
import uuid
import logging
import smtplib
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("prospector")

DB_PATH = os.getenv("PROSPECTOR_DB_PATH", "/data/prospector.db")
EVALUATOR_URL = os.getenv("EVALUATOR_URL", "http://localhost:8800")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
NOTIFY_MIN_BUDGET = float(os.getenv("NOTIFY_MIN_BUDGET", "100"))
AUTO_EVALUATE = os.getenv("AUTO_EVALUATE", "false").lower() == "true"

UPWORK_RSS_BASE = "https://www.upwork.com/ab/feed/jobs/rss"
UPWORK_SEARCH_CATEGORIES = os.getenv(
    "UPWORK_SEARCH_CATEGORIES",
    "web-development,data-science,ai-ml,writing,software-development"
).split(",")

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

FREELANCER_API_BASE = "https://www.freelancer.com/api"
FREELANCER_TOKEN = os.getenv("FREELANCER_TOKEN", "")
FREELANCER_ID = os.getenv("FREELANCER_ID", "")
BID_REQUIRE_APPROVAL = os.getenv("BID_REQUIRE_APPROVAL", "true").lower() == "true"

PROSPECT_STATUSES = [
    "discovered", "evaluating", "approved", "applied",
    "hired", "executing", "delivered", "paid", "rated", "rejected",
]


# ---------------------------------------------------------------------------
# Platform registry
# ---------------------------------------------------------------------------

PLATFORMS = {
    "upwork": {
        "label": "Upwork",
        "status": "active",
        "type": "rss",
        "description": "Freelance marketplace — all digital work",
    },
    "github_bounties": {
        "label": "GitHub Bounties",
        "status": "active",
        "type": "api",
        "description": "Open-source issue bounties on GitHub",
    },
    "superteam_earn": {
        "label": "Superteam Earn",
        "status": "active",
        "type": "scrape",
        "description": "Solana ecosystem bounties — dev, content, design",
    },
    "gitcoin": {
        "label": "Gitcoin",
        "status": "active",
        "type": "api",
        "description": "Ethereum/multi-chain open-source bounties",
    },
    "dework": {
        "label": "Dework",
        "status": "active",
        "type": "api",
        "description": "DAO task boards — dev, design, community",
    },
    "layer3": {
        "label": "Layer3",
        "status": "active",
        "type": "api",
        "description": "Multi-chain quests and bounties",
    },
    "replit_bounties": {
        "label": "Replit Bounties",
        "status": "active",
        "type": "api",
        "description": "Code bounties on Replit",
    },
    "zealy": {
        "label": "Zealy",
        "status": "active",
        "type": "api",
        "description": "Community quests — content, growth tasks",
    },
    "galxe": {
        "label": "Galxe",
        "status": "active",
        "type": "api",
        "description": "Multi-chain campaign quests and tasks",
    },
    "questbook": {
        "label": "Questbook",
        "status": "active",
        "type": "api",
        "description": "Protocol-funded developer grants",
    },
    "onlydust": {
        "label": "OnlyDust",
        "status": "active",
        "type": "api",
        "description": "GitHub-linked bounties for web3 projects",
    },
    "freelancer": {
        "label": "Freelancer.com",
        "status": "active",
        "type": "api",
        "description": "Freelance contests and fixed/hourly projects",
    },
    "fiverr": {
        "label": "Fiverr",
        "status": "active",
        "type": "scrape",
        "description": "Task-based gigs across all categories",
    },
    "topcoder": {
        "label": "Topcoder",
        "status": "active",
        "type": "api",
        "description": "Algorithm, development, and design challenges",
    },
    "hackerone": {
        "label": "HackerOne",
        "status": "active",
        "type": "api",
        "description": "Security vulnerability bounties",
    },
    "bugcrowd": {
        "label": "Bugcrowd",
        "status": "active",
        "type": "api",
        "description": "Enterprise bug bounty programs",
    },
    "kaggle": {
        "label": "Kaggle",
        "status": "active",
        "type": "api",
        "description": "Data science and ML competitions",
    },
    "issuehunt": {
        "label": "IssueHunt",
        "status": "active",
        "type": "api",
        "description": "Fund and solve GitHub issues",
    },
    "algora": {
        "label": "Algora",
        "status": "active",
        "type": "api",
        "description": "Open-source bounties with Stripe payouts",
    },
}


class ScanRequest(BaseModel):
    platform: str = "upwork"
    query: str = ""
    category: str = ""
    max_results: int = 20


class ProspectUpdate(BaseModel):
    status: str
    notes: str = ""


class BidSubmission(BaseModel):
    prospect_id: str
    amount: float
    period: int = 7
    milestone_percentage: float = 100
    description: str = ""


def _svc_headers():
    h = {"Content-Type": "application/json"}
    if SERVICE_TOKEN:
        h["X-Service-Token"] = SERVICE_TOKEN
    return h


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS prospects (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                platform_job_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                budget_min REAL DEFAULT 0,
                budget_max REAL DEFAULT 0,
                client_rating REAL DEFAULT 0,
                skills TEXT DEFAULT '',
                status TEXT DEFAULT 'discovered',
                evaluation_id TEXT,
                quoted_price REAL DEFAULT 0,
                estimated_cost REAL DEFAULT 0,
                actual_cost REAL DEFAULT 0,
                url TEXT,
                applied_at TIMESTAMP,
                hired_at TIMESTAMP,
                delivered_at TIMESTAMP,
                paid_at TIMESTAMP,
                rating INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_prospect_dedup
            ON prospects (platform, platform_job_id)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_prospect_status
            ON prospects (status)
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_prospect_platform
            ON prospects (platform, created_at DESC)
        """)
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Prospector", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM prospects")
            count = (await cursor.fetchone())[0]
        return {"ok": 1, "service": "prospector", "prospects": count}
    except Exception:
        return {"ok": 0, "service": "prospector", "error": "db_unreachable"}


# ---------------------------------------------------------------------------
# Scan dispatcher
# ---------------------------------------------------------------------------

SCANNERS = {}


def scanner(platform_name):
    def decorator(fn):
        SCANNERS[platform_name] = fn
        return fn
    return decorator


@app.post("/scan")
async def scan(req: ScanRequest):
    if req.platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {req.platform}")

    scan_fn = SCANNERS.get(req.platform)
    if not scan_fn:
        raise HTTPException(status_code=400, detail=f"No scanner implemented for: {req.platform}")

    prospects = await scan_fn(req.query, req.category, req.max_results)

    saved = 0
    new_prospects = []
    for p in prospects:
        if await _save_prospect_dedup(p):
            saved += 1
            new_prospects.append(p)

    high_value = [p for p in new_prospects if p.get("budget_max", 0) >= NOTIFY_MIN_BUDGET]
    if high_value:
        _send_prospect_alert(high_value)

    if AUTO_EVALUATE and new_prospects:
        evaluated = await _auto_evaluate_batch(new_prospects)
        logger.info("Auto-evaluated %d/%d new prospects", evaluated, len(new_prospects))

    logger.info("Scan complete: %d discovered, %d new on %s", len(prospects), saved, req.platform)
    return {"ok": 1, "discovered": len(prospects), "new": saved, "platform": req.platform}


# ---------------------------------------------------------------------------
# Platform scanners
# ---------------------------------------------------------------------------

def _make_prospect(platform: str, job_id: str, title: str, description: str,
                   budget_min: float = 0, budget_max: float = 0,
                   url: str = "", skills: str = "") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "platform": platform,
        "platform_job_id": job_id,
        "title": title,
        "description": description,
        "budget_min": budget_min,
        "budget_max": budget_max,
        "url": url,
        "skills": skills,
        "status": "discovered",
    }


@scanner("upwork")
async def _scan_upwork(query: str, category: str, max_results: int) -> list[dict]:
    params = {"sort": "recency", "paging": f"0;{max_results}"}
    if query:
        params["q"] = query
    if category:
        params["subcategory2"] = category

    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(UPWORK_RSS_BASE, params=params)
            resp.raise_for_status()
            items = _parse_rss(resp.text)

            for item in items[:max_results]:
                desc = item.get("description", "")
                prospects.append(_make_prospect(
                    platform="upwork",
                    job_id=item.get("guid", str(uuid.uuid4())),
                    title=item.get("title", "Untitled"),
                    description=desc,
                    budget_min=_extract_budget(desc, "min"),
                    budget_max=_extract_budget(desc, "max"),
                    url=item.get("link", ""),
                    skills=item.get("skills", ""),
                ))
    except httpx.RequestError as e:
        logger.warning("Upwork RSS fetch failed: %s", e)

    return prospects


@scanner("github_bounties")
async def _scan_github(query: str, category: str, max_results: int) -> list[dict]:
    search_query = query or "label:bounty state:open"
    if "label:" not in search_query:
        search_query += " label:bounty"
    if "state:" not in search_query:
        search_query += " state:open"

    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"

    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GITHUB_API}/search/issues",
                params={"q": search_query, "sort": "created", "order": "desc", "per_page": max_results},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

            for issue in data.get("items", [])[:max_results]:
                body = issue.get("body", "") or ""
                budget = _extract_budget(body, "max")
                prospects.append(_make_prospect(
                    platform="github_bounties",
                    job_id=str(issue["id"]),
                    title=issue.get("title", ""),
                    description=body[:2000],
                    budget_min=0,
                    budget_max=budget,
                    url=issue.get("html_url", ""),
                    skills=",".join(l["name"] for l in issue.get("labels", [])),
                ))
    except httpx.RequestError as e:
        logger.warning("GitHub search failed: %s", e)

    return prospects


@scanner("superteam_earn")
async def _scan_superteam(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://earn.superteam.fun/api/listings",
                params={"take": max_results, "type": "bounty"},
            )
            resp.raise_for_status()
            listings = resp.json()
            if isinstance(listings, dict):
                listings = listings.get("bounties", listings.get("listings", []))

            for item in listings[:max_results]:
                title = item.get("title", "")
                if query and query.lower() not in title.lower():
                    continue
                reward = item.get("rewardAmount", 0) or item.get("usdValue", 0) or 0
                prospects.append(_make_prospect(
                    platform="superteam_earn",
                    job_id=str(item.get("id", uuid.uuid4())),
                    title=title,
                    description=item.get("description", "")[:2000],
                    budget_min=0,
                    budget_max=float(reward),
                    url=item.get("url", f"https://earn.superteam.fun/listings/{item.get('slug', '')}"),
                    skills=",".join(item.get("skills", [])) if isinstance(item.get("skills"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Superteam Earn fetch failed: %s", e)

    return prospects


@scanner("gitcoin")
async def _scan_gitcoin(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://gitcoin.co/api/v0.1/bounties/",
                params={"is_open": "true", "order_by": "-web3_created", "limit": max_results,
                        **({"keyword": query} if query else {})},
            )
            resp.raise_for_status()
            bounties = resp.json()

            for b in bounties[:max_results]:
                prospects.append(_make_prospect(
                    platform="gitcoin",
                    job_id=str(b.get("pk", uuid.uuid4())),
                    title=b.get("title", ""),
                    description=(b.get("issue_description_text", "") or "")[:2000],
                    budget_min=0,
                    budget_max=float(b.get("value_in_usdt", 0) or 0),
                    url=b.get("url", ""),
                    skills=",".join(b.get("keywords", [])) if isinstance(b.get("keywords"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Gitcoin fetch failed: %s", e)

    return prospects


@scanner("dework")
async def _scan_dework(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        gql_query = {
            "query": """query { tasks(filter: { status: TODO }, pagination: { limit: %d }) {
                id title description reward { amount currency } permalink tags { label }
            }}""" % max_results
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://api.dework.xyz/graphql", json=gql_query)
            resp.raise_for_status()
            data = resp.json()

            for task in (data.get("data", {}).get("tasks", []))[:max_results]:
                title = task.get("title", "")
                if query and query.lower() not in title.lower():
                    continue
                reward = task.get("reward", {}) or {}
                amount = float(reward.get("amount", 0) or 0)
                prospects.append(_make_prospect(
                    platform="dework",
                    job_id=str(task.get("id", uuid.uuid4())),
                    title=title,
                    description=(task.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=amount,
                    url=task.get("permalink", ""),
                    skills=",".join(t.get("label", "") for t in task.get("tags", [])),
                ))
    except httpx.RequestError as e:
        logger.warning("Dework fetch failed: %s", e)

    return prospects


@scanner("layer3")
async def _scan_layer3(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.layer3.xyz/v1/quests",
                params={"limit": max_results, "status": "active",
                        **({"search": query} if query else {})},
            )
            resp.raise_for_status()
            quests = resp.json()
            if isinstance(quests, dict):
                quests = quests.get("quests", quests.get("data", []))

            for q in quests[:max_results]:
                reward = q.get("reward", {}) or {}
                amount = float(reward.get("amount", 0) or q.get("xp", 0) or 0)
                prospects.append(_make_prospect(
                    platform="layer3",
                    job_id=str(q.get("id", uuid.uuid4())),
                    title=q.get("title", q.get("name", "")),
                    description=(q.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=amount,
                    url=q.get("url", ""),
                    skills=",".join(q.get("tags", [])) if isinstance(q.get("tags"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Layer3 fetch failed: %s", e)

    return prospects


@scanner("replit_bounties")
async def _scan_replit(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://replit.com/api/v1/bounties",
                params={"status": "open", "limit": max_results,
                        **({"query": query} if query else {})},
            )
            resp.raise_for_status()
            bounties = resp.json()
            if isinstance(bounties, dict):
                bounties = bounties.get("items", bounties.get("bounties", []))

            for b in bounties[:max_results]:
                prospects.append(_make_prospect(
                    platform="replit_bounties",
                    job_id=str(b.get("id", uuid.uuid4())),
                    title=b.get("title", ""),
                    description=(b.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=float(b.get("amount", 0) or b.get("cycles", 0) or 0),
                    url=b.get("url", ""),
                    skills=",".join(b.get("tags", [])) if isinstance(b.get("tags"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Replit bounties fetch failed: %s", e)

    return prospects


@scanner("zealy")
async def _scan_zealy(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.zealy.io/public/communities",
                params={"limit": max_results},
            )
            resp.raise_for_status()
            communities = resp.json()
            if isinstance(communities, dict):
                communities = communities.get("communities", communities.get("data", []))

            for c in communities[:max_results]:
                name = c.get("name", "")
                if query and query.lower() not in name.lower():
                    continue
                prospects.append(_make_prospect(
                    platform="zealy",
                    job_id=str(c.get("id", uuid.uuid4())),
                    title=f"Zealy Quest: {name}",
                    description=(c.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=0,
                    url=c.get("url", f"https://zealy.io/c/{c.get('subdomain', '')}"),
                ))
    except httpx.RequestError as e:
        logger.warning("Zealy fetch failed: %s", e)

    return prospects


@scanner("galxe")
async def _scan_galxe(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        gql = {
            "query": """query { campaigns(input: { chains: [], status: Active, first: %d }) {
                list { id name description numNFTMinted loyaltyPoints chain }
            }}""" % max_results
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://graphigo.prd.galaxy.eco/query", json=gql)
            resp.raise_for_status()
            data = resp.json()

            campaigns = data.get("data", {}).get("campaigns", {}).get("list", [])
            for c in campaigns[:max_results]:
                title = c.get("name", "")
                if query and query.lower() not in title.lower():
                    continue
                prospects.append(_make_prospect(
                    platform="galxe",
                    job_id=str(c.get("id", uuid.uuid4())),
                    title=title,
                    description=(c.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=float(c.get("loyaltyPoints", 0) or 0),
                    url=f"https://galxe.com/campaign/{c.get('id', '')}",
                ))
    except httpx.RequestError as e:
        logger.warning("Galxe fetch failed: %s", e)

    return prospects


@scanner("questbook")
async def _scan_questbook(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.questbook.app/api/grants",
                params={"status": "open", "limit": max_results},
            )
            resp.raise_for_status()
            grants = resp.json()
            if isinstance(grants, dict):
                grants = grants.get("grants", grants.get("data", []))

            for g in grants[:max_results]:
                title = g.get("title", "")
                if query and query.lower() not in title.lower():
                    continue
                reward = float(g.get("reward", 0) or g.get("funding", 0) or 0)
                prospects.append(_make_prospect(
                    platform="questbook",
                    job_id=str(g.get("id", uuid.uuid4())),
                    title=title,
                    description=(g.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=reward,
                    url=g.get("url", ""),
                ))
    except httpx.RequestError as e:
        logger.warning("Questbook fetch failed: %s", e)

    return prospects


@scanner("onlydust")
async def _scan_onlydust(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.onlydust.com/api/v1/projects",
                params={"pageSize": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            projects = data.get("projects", data.get("data", []))

            for p in projects[:max_results]:
                title = p.get("name", "")
                if query and query.lower() not in title.lower():
                    continue
                prospects.append(_make_prospect(
                    platform="onlydust",
                    job_id=str(p.get("id", uuid.uuid4())),
                    title=f"OnlyDust: {title}",
                    description=(p.get("shortDescription", p.get("description", "")) or "")[:2000],
                    budget_min=0,
                    budget_max=0,
                    url=p.get("htmlUrl", f"https://app.onlydust.com/p/{p.get('slug', '')}"),
                    skills=",".join(p.get("technologies", [])) if isinstance(p.get("technologies"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("OnlyDust fetch failed: %s", e)

    return prospects


@scanner("freelancer")
async def _scan_freelancer(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"compact": "true", "limit": max_results, "sort_field": "time_updated",
                      "project_types[]": "fixed"}
            if query:
                params["query"] = query
            resp = await client.get("https://www.freelancer.com/api/projects/0.1/projects/active/", params=params)
            resp.raise_for_status()
            data = resp.json()

            for proj in data.get("result", {}).get("projects", [])[:max_results]:
                budget = proj.get("budget", {}) or {}
                prospects.append(_make_prospect(
                    platform="freelancer",
                    job_id=str(proj.get("id", uuid.uuid4())),
                    title=proj.get("title", ""),
                    description=(proj.get("preview_description", "") or "")[:2000],
                    budget_min=float(budget.get("minimum", 0) or 0),
                    budget_max=float(budget.get("maximum", 0) or 0),
                    url=f"https://www.freelancer.com/projects/{proj.get('seo_url', '')}",
                    skills=",".join(j.get("name", "") for j in proj.get("jobs", [])),
                ))
    except httpx.RequestError as e:
        logger.warning("Freelancer.com fetch failed: %s", e)

    return prospects


@scanner("fiverr")
async def _scan_fiverr(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"query": query or "python developer", "limit": max_results}
            resp = await client.get("https://www.fiverr.com/api/v1/buyer_requests", params=params)
            resp.raise_for_status()
            data = resp.json()
            requests = data.get("buyer_requests", data.get("data", []))

            for br in requests[:max_results]:
                prospects.append(_make_prospect(
                    platform="fiverr",
                    job_id=str(br.get("id", uuid.uuid4())),
                    title=br.get("title", br.get("description", "")[:80]),
                    description=(br.get("description", "") or "")[:2000],
                    budget_min=float(br.get("budget_min", 0) or 0),
                    budget_max=float(br.get("budget_max", br.get("budget", 0)) or 0),
                    url=br.get("url", ""),
                ))
    except httpx.RequestError as e:
        logger.warning("Fiverr fetch failed: %s", e)

    return prospects


@scanner("topcoder")
async def _scan_topcoder(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {"status": "Active", "perPage": max_results, "sortBy": "startDate", "sortOrder": "desc"}
            if query:
                params["name"] = query
            resp = await client.get("https://api.topcoder.com/v5/challenges", params=params)
            resp.raise_for_status()
            challenges = resp.json()

            for ch in challenges[:max_results]:
                prizes = ch.get("prizeSets", [])
                total_prize = 0
                for ps in prizes:
                    for p in ps.get("prizes", []):
                        total_prize += float(p.get("value", 0) or 0)
                prospects.append(_make_prospect(
                    platform="topcoder",
                    job_id=str(ch.get("id", uuid.uuid4())),
                    title=ch.get("name", ""),
                    description=(ch.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=total_prize,
                    url=f"https://www.topcoder.com/challenges/{ch.get('id', '')}",
                    skills=",".join(ch.get("tags", [])) if isinstance(ch.get("tags"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Topcoder fetch failed: %s", e)

    return prospects


@scanner("hackerone")
async def _scan_hackerone(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.hackerone.com/v1/hackers/programs",
                params={"page[size]": max_results},
                auth=("", ""),
            )
            resp.raise_for_status()
            data = resp.json()

            for prog in data.get("data", [])[:max_results]:
                attrs = prog.get("attributes", {})
                title = attrs.get("name", "")
                if query and query.lower() not in title.lower():
                    continue
                bounty_range = attrs.get("meta", {}).get("bounty_range", {}) or {}
                prospects.append(_make_prospect(
                    platform="hackerone",
                    job_id=str(prog.get("id", uuid.uuid4())),
                    title=f"Bug Bounty: {title}",
                    description=(attrs.get("policy", "") or "")[:2000],
                    budget_min=float(bounty_range.get("min", 0) or 0),
                    budget_max=float(bounty_range.get("max", 0) or 0),
                    url=attrs.get("url", f"https://hackerone.com/{attrs.get('handle', '')}"),
                ))
    except httpx.RequestError as e:
        logger.warning("HackerOne fetch failed: %s", e)

    return prospects


@scanner("bugcrowd")
async def _scan_bugcrowd(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://bugcrowd.com/programs.json",
                params={"sort[]": "promoted-desc", "hidden[]": "false", "page": 1},
            )
            resp.raise_for_status()
            programs = resp.json()
            if isinstance(programs, dict):
                programs = programs.get("programs", [])

            for prog in programs[:max_results]:
                title = prog.get("name", "")
                if query and query.lower() not in title.lower():
                    continue
                max_reward = float(prog.get("max_payout", 0) or prog.get("max_reward", 0) or 0)
                prospects.append(_make_prospect(
                    platform="bugcrowd",
                    job_id=str(prog.get("id", prog.get("code", uuid.uuid4()))),
                    title=f"Bug Bounty: {title}",
                    description=(prog.get("description", prog.get("tagline", "")) or "")[:2000],
                    budget_min=0,
                    budget_max=max_reward,
                    url=prog.get("url", f"https://bugcrowd.com/{prog.get('code', '')}"),
                ))
    except httpx.RequestError as e:
        logger.warning("Bugcrowd fetch failed: %s", e)

    return prospects


@scanner("kaggle")
async def _scan_kaggle(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://www.kaggle.com/api/v1/competitions/list",
                params={"sortBy": "latestDeadline", "page": 1, "group": "general",
                        **({"search": query} if query else {})},
            )
            resp.raise_for_status()
            comps = resp.json()

            for c in comps[:max_results]:
                reward = c.get("reward", "")
                amount = 0
                if reward:
                    match = re.search(r"\$?([\d,]+)", str(reward))
                    if match:
                        amount = float(match.group(1).replace(",", ""))
                prospects.append(_make_prospect(
                    platform="kaggle",
                    job_id=str(c.get("id", c.get("ref", uuid.uuid4()))),
                    title=c.get("title", ""),
                    description=(c.get("description", "") or "")[:2000],
                    budget_min=0,
                    budget_max=amount,
                    url=c.get("url", f"https://www.kaggle.com/competitions/{c.get('ref', '')}"),
                    skills=",".join(c.get("tags", [])) if isinstance(c.get("tags"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Kaggle fetch failed: %s", e)

    return prospects


@scanner("issuehunt")
async def _scan_issuehunt(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.issuehunt.io/v1/issues",
                params={"limit": max_results, "sort": "newest",
                        **({"q": query} if query else {})},
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", data.get("data", []))

            for issue in issues[:max_results]:
                amount = float(issue.get("total_amount", 0) or issue.get("bounty_amount", 0) or 0)
                prospects.append(_make_prospect(
                    platform="issuehunt",
                    job_id=str(issue.get("id", uuid.uuid4())),
                    title=issue.get("title", ""),
                    description=(issue.get("body", "") or "")[:2000],
                    budget_min=0,
                    budget_max=amount,
                    url=issue.get("html_url", issue.get("url", "")),
                    skills=",".join(issue.get("labels", [])) if isinstance(issue.get("labels"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("IssueHunt fetch failed: %s", e)

    return prospects


@scanner("algora")
async def _scan_algora(query: str, category: str, max_results: int) -> list[dict]:
    prospects = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.algora.io/bounties",
                params={"status": "open", "limit": max_results,
                        **({"search": query} if query else {})},
            )
            resp.raise_for_status()
            data = resp.json()
            bounties = data.get("bounties", data.get("data", []))

            for b in bounties[:max_results]:
                amount = float(b.get("reward_amount", 0) or b.get("amount", 0) or 0)
                prospects.append(_make_prospect(
                    platform="algora",
                    job_id=str(b.get("id", uuid.uuid4())),
                    title=b.get("title", ""),
                    description=(b.get("description", b.get("body", "")) or "")[:2000],
                    budget_min=0,
                    budget_max=amount,
                    url=b.get("url", b.get("html_url", "")),
                    skills=",".join(b.get("labels", [])) if isinstance(b.get("labels"), list) else "",
                ))
    except httpx.RequestError as e:
        logger.warning("Algora fetch failed: %s", e)

    return prospects


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def _send_prospect_alert(prospects: list[dict]):
    if not SMTP_HOST or not NOTIFY_EMAIL:
        logger.info("Skipping email alert: SMTP not configured (%d high-value prospects)", len(prospects))
        return

    subject = f"Agent N9er: {len(prospects)} high-value prospect(s) discovered"

    lines = []
    for p in prospects[:20]:
        budget = f"${p.get('budget_max', 0):,.0f}" if p.get("budget_max") else "TBD"
        lines.append(f"  [{p['platform']}] {p['title'][:80]}  —  {budget}")
        if p.get("url"):
            lines.append(f"    {p['url']}")
        lines.append("")

    body = (
        f"Agent N9er discovered {len(prospects)} prospect(s) above ${NOTIFY_MIN_BUDGET:,.0f}:\n\n"
        + "\n".join(lines)
        + "\n\nLogin to the command center to review and evaluate."
    )

    msg = MIMEMultipart()
    msg["From"] = SMTP_USER or "agent-n9er@noreply.com"
    msg["To"] = NOTIFY_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        logger.info("Sent prospect alert to %s (%d prospects)", NOTIFY_EMAIL, len(prospects))
    except Exception as e:
        logger.warning("Failed to send prospect alert: %s", e)


async def _auto_evaluate_batch(prospects: list[dict]) -> int:
    evaluated = 0
    for p in prospects:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{EVALUATOR_URL}/evaluate",
                    json={
                        "title": p["title"],
                        "description": p.get("description", ""),
                        "platform": p["platform"],
                        "budget_min": p.get("budget_min", 0),
                        "budget_max": p.get("budget_max", 0),
                        "skills_required": p.get("skills", "").split(",") if p.get("skills") else [],
                    },
                    headers=_svc_headers(),
                )
                resp.raise_for_status()
                evaluation = resp.json()

            new_status = "approved" if evaluation.get("viable") else "rejected"
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE prospects SET status = ?, evaluation_id = ?, quoted_price = ?, estimated_cost = ? WHERE id = ?",
                    (new_status, evaluation.get("evaluation_id", ""), evaluation.get("quoted_price_usd", 0),
                     evaluation.get("estimated_cost_usd", 0), p["id"]),
                )
                await db.commit()
            evaluated += 1
        except Exception as e:
            logger.warning("Auto-evaluate failed for %s: %s", p["id"][:8], e)
    return evaluated


async def _save_prospect_dedup(p: dict) -> bool:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT OR IGNORE INTO prospects (id, platform, platform_job_id, title, description, budget_min, budget_max, skills, status, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p["id"], p["platform"], p["platform_job_id"], p["title"], p["description"],
                 p["budget_min"], p["budget_max"], p.get("skills", ""), p["status"], p.get("url", "")),
            )
            await db.commit()
            return db.total_changes > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_rss(xml_text: str) -> list[dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            entry = {}
            for child in item:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                entry[tag] = child.text or ""
            items.append(entry)
    except ET.ParseError:
        logger.warning("Failed to parse RSS feed")
    return items


def _extract_budget(description: str, which: str) -> float:
    patterns = [
        r"\$(\d[\d,]*(?:\.\d{2})?)",
        r"Budget:\s*\$(\d[\d,]*(?:\.\d{2})?)\s*-\s*\$(\d[\d,]*(?:\.\d{2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, description)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                val = groups[0] if which == "min" else groups[1]
                return float(val.replace(",", ""))
            elif len(groups) == 1:
                return float(groups[0].replace(",", ""))
    return 0


# ---------------------------------------------------------------------------
# Prospect CRUD
# ---------------------------------------------------------------------------

@app.get("/prospects")
async def list_prospects(status: str = "", platform: str = "", limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM prospects WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if platform:
            query += " AND platform = ?"
            params.append(platform)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.get("/prospects/{prospect_id}")
async def get_prospect(prospect_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Prospect not found")
        return dict(row)


@app.post("/prospects/{prospect_id}/evaluate")
async def evaluate_prospect(prospect_id: str):
    prospect = await _get_prospect(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    await _update_status(prospect_id, "evaluating")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{EVALUATOR_URL}/evaluate",
                json={
                    "title": prospect["title"],
                    "description": prospect["description"],
                    "platform": prospect["platform"],
                    "budget_min": prospect["budget_min"],
                    "budget_max": prospect["budget_max"],
                    "skills_required": prospect["skills"].split(",") if prospect["skills"] else [],
                },
                headers=_svc_headers(),
            )
            resp.raise_for_status()
            evaluation = resp.json()

        new_status = "approved" if evaluation.get("viable") else "rejected"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE prospects SET status = ?, evaluation_id = ?, quoted_price = ?, estimated_cost = ? WHERE id = ?",
                (new_status, evaluation["evaluation_id"], evaluation.get("quoted_price_usd", 0),
                 evaluation.get("estimated_cost_usd", 0), prospect_id),
            )
            await db.commit()

        logger.info("Prospect %s evaluated: %s (quote=$%.2f)",
                     prospect_id[:8], new_status, evaluation.get("quoted_price_usd", 0))
        return {"ok": 1, "status": new_status, "evaluation": evaluation}

    except httpx.RequestError as e:
        await _update_status(prospect_id, "discovered")
        raise HTTPException(status_code=503, detail=f"Evaluator unreachable: {e}")


@app.patch("/prospects/{prospect_id}")
async def update_prospect(prospect_id: str, update: ProspectUpdate):
    if update.status not in PROSPECT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {update.status}")

    prospect = await _get_prospect(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    timestamp_field = {
        "applied": "applied_at",
        "hired": "hired_at",
        "delivered": "delivered_at",
        "paid": "paid_at",
    }.get(update.status)

    async with aiosqlite.connect(DB_PATH) as db:
        if timestamp_field:
            await db.execute(
                f"UPDATE prospects SET status = ?, {timestamp_field} = ? WHERE id = ?",
                (update.status, datetime.utcnow().isoformat(), prospect_id),
            )
        else:
            await db.execute(
                "UPDATE prospects SET status = ? WHERE id = ?",
                (update.status, prospect_id),
            )
        await db.commit()

    logger.info("Prospect %s → %s", prospect_id[:8], update.status)
    return {"ok": 1, "prospect_id": prospect_id, "status": update.status}


# ---------------------------------------------------------------------------
# Freelancer bid submission
# ---------------------------------------------------------------------------

_pending_bids = {}


SUPPORTED_BID_PLATFORMS = {"freelancer", "github_bounties"}


@app.post("/prospects/{prospect_id}/bid")
async def submit_bid(prospect_id: str, bid: BidSubmission):
    prospect = await _get_prospect(prospect_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    platform = prospect["platform"]
    if platform not in SUPPORTED_BID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Bid submission not supported for platform: {platform}")

    if platform == "freelancer" and not FREELANCER_TOKEN:
        raise HTTPException(status_code=503, detail="FREELANCER_TOKEN not configured")
    if platform == "github_bounties" and not GITHUB_TOKEN:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN not configured")

    project_id = prospect.get("platform_job_id")
    if not project_id:
        raise HTTPException(status_code=400, detail="No platform job ID for this prospect")

    bid_data = {
        "prospect_id": prospect_id,
        "project_id": project_id,
        "platform": platform,
        "title": prospect["title"],
        "url": prospect.get("url", ""),
        "amount": bid.amount,
        "period": bid.period,
        "milestone_percentage": bid.milestone_percentage,
        "description": bid.description,
    }

    if BID_REQUIRE_APPROVAL:
        bid_id = str(uuid.uuid4())
        _pending_bids[bid_id] = bid_data
        logger.info("Bid %s pending approval: %s ($%.2f) [%s]", bid_id[:8], prospect["title"][:40], bid.amount, platform)
        return {
            "ok": 1,
            "status": "pending_approval",
            "bid_id": bid_id,
            "detail": "Bid requires approval. Use POST /bids/{bid_id}/approve to submit.",
            **bid_data,
        }

    if platform == "github_bounties":
        return await _submit_github_comment(prospect_id, prospect, bid.description, bid.amount)
    return await _submit_freelancer_bid(prospect_id, project_id, bid, bid.description)


@app.get("/bids/pending")
async def list_pending_bids():
    return [{"bid_id": bid_id, **data} for bid_id, data in _pending_bids.items()]


@app.post("/bids/{bid_id}/approve")
async def approve_bid(bid_id: str):
    bid_data = _pending_bids.pop(bid_id, None)
    if not bid_data:
        raise HTTPException(status_code=404, detail="Pending bid not found or already processed")

    prospect_id = bid_data["prospect_id"]
    project_id = bid_data["project_id"]
    platform = bid_data.get("platform", "freelancer")

    if platform == "github_bounties":
        prospect = await _get_prospect(prospect_id)
        if not prospect:
            raise HTTPException(status_code=404, detail="Prospect not found")
        return await _submit_github_comment(
            prospect_id, prospect, bid_data["description"], bid_data["amount"]
        )

    bid_req = BidSubmission(
        prospect_id=prospect_id,
        amount=bid_data["amount"],
        period=bid_data["period"],
        milestone_percentage=bid_data["milestone_percentage"],
        description=bid_data["description"],
    )

    return await _submit_freelancer_bid(prospect_id, project_id, bid_req, bid_data["description"])


@app.post("/bids/{bid_id}/reject")
async def reject_bid(bid_id: str):
    bid_data = _pending_bids.pop(bid_id, None)
    if not bid_data:
        raise HTTPException(status_code=404, detail="Pending bid not found or already processed")
    logger.info("Bid rejected: %s", bid_data.get("title", "")[:40])
    return {"ok": 1, "status": "rejected", "bid_id": bid_id}


async def _submit_freelancer_bid(prospect_id: str, project_id: str, bid: BidSubmission, description: str) -> dict:
    headers = {
        "Freelancer-OAuth-V1": FREELANCER_TOKEN,
        "Content-Type": "application/json",
    }

    if not FREELANCER_ID:
        raise HTTPException(status_code=503, detail="FREELANCER_ID not configured")

    payload = {
        "project_id": int(project_id),
        "bidder_id": int(FREELANCER_ID),
        "amount": bid.amount,
        "period": bid.period,
        "milestone_percentage": bid.milestone_percentage,
        "description": description,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{FREELANCER_API_BASE}/projects/0.1/bids/",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

            await _update_status(prospect_id, "applied")

            logger.info("Bid submitted for prospect %s: project=%s amount=$%.2f",
                        prospect_id[:8], project_id, bid.amount)

            return {
                "ok": 1,
                "status": "submitted",
                "prospect_id": prospect_id,
                "project_id": project_id,
                "amount": bid.amount,
                "period": bid.period,
                "freelancer_response": result.get("result", {}),
            }

    except httpx.HTTPStatusError as e:
        error_body = {}
        try:
            error_body = e.response.json()
        except Exception:
            pass
        logger.error("Freelancer bid submission failed: %s %s", e.response.status_code, error_body)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Freelancer API error: {error_body.get('message', str(e))}",
        )
    except httpx.RequestError as e:
        logger.error("Freelancer API unreachable: %s", e)
        raise HTTPException(status_code=503, detail=f"Freelancer API unreachable: {e}")


def _parse_github_issue_url(url: str) -> tuple[str, str, int] | None:
    """Extract (owner, repo, issue_number) from a GitHub issue URL."""
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url or "")
    if match:
        return match.group(1), match.group(2), int(match.group(3))
    return None


async def _submit_github_comment(prospect_id: str, prospect: dict, description: str, amount: float) -> dict:
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=503, detail="GITHUB_TOKEN not configured")

    parsed = _parse_github_issue_url(prospect.get("url", ""))
    if not parsed:
        raise HTTPException(status_code=400, detail="Cannot parse GitHub issue URL from prospect")

    owner, repo, issue_number = parsed

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments",
                json={"body": description},
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

            await _update_status(prospect_id, "applied")

            logger.info("GitHub comment posted for prospect %s: %s/%s#%d",
                        prospect_id[:8], owner, repo, issue_number)

            return {
                "ok": 1,
                "status": "submitted",
                "platform": "github_bounties",
                "prospect_id": prospect_id,
                "issue": f"{owner}/{repo}#{issue_number}",
                "comment_url": result.get("html_url", ""),
                "amount": amount,
            }

    except httpx.HTTPStatusError as e:
        error_body = {}
        try:
            error_body = e.response.json()
        except Exception:
            pass
        logger.error("GitHub comment failed: %s %s", e.response.status_code, error_body)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"GitHub API error: {error_body.get('message', str(e))}",
        )
    except httpx.RequestError as e:
        logger.error("GitHub API unreachable: %s", e)
        raise HTTPException(status_code=503, detail=f"GitHub API unreachable: {e}")


async def _update_status(prospect_id: str, status: str):
    timestamp_field = {
        "applied": "applied_at",
        "hired": "hired_at",
        "delivered": "delivered_at",
        "paid": "paid_at",
    }.get(status)

    async with aiosqlite.connect(DB_PATH) as db:
        if timestamp_field:
            await db.execute(
                f"UPDATE prospects SET status = ?, {timestamp_field} = ? WHERE id = ?",
                (status, datetime.utcnow().isoformat(), prospect_id),
            )
        else:
            await db.execute(
                "UPDATE prospects SET status = ? WHERE id = ?",
                (status, prospect_id),
            )
        await db.commit()


@app.get("/stats")
async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) as count FROM prospects GROUP BY status"
        )
        rows = await cursor.fetchall()
        by_status = {row[0]: row[1] for row in rows}

        cursor = await db.execute(
            "SELECT SUM(quoted_price), SUM(estimated_cost), SUM(actual_cost) FROM prospects WHERE status = 'paid'"
        )
        row = await cursor.fetchone()
        revenue = row[0] or 0
        costs = row[1] or 0
        actual_costs = row[2] or 0

    return {
        "by_status": by_status,
        "total_prospects": sum(by_status.values()),
        "revenue": round(revenue, 2),
        "estimated_costs": round(costs, 2),
        "actual_costs": round(actual_costs, 2),
        "estimated_profit": round(revenue - costs, 2),
    }


@app.get("/platforms")
async def platforms():
    return [
        {"name": key, "label": val["label"], "status": val["status"],
         "type": val["type"], "description": val["description"]}
        for key, val in PLATFORMS.items()
    ]


async def _get_prospect(prospect_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _get_by_platform_id(platform: str, platform_job_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM prospects WHERE platform = ? AND platform_job_id = ?",
            (platform, platform_job_id),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def _save_prospect(p: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO prospects (id, platform, platform_job_id, title, description, budget_min, budget_max, skills, status, url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["id"], p["platform"], p["platform_job_id"], p["title"], p["description"],
             p["budget_min"], p["budget_max"], p.get("skills", ""), p["status"], p.get("url", "")),
        )
        await db.commit()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8900)
