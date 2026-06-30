"""Upwork Bid Service — the write arm of Agent N9er.

Fully documented GraphQL mutations from the Upwork API:
  - submitProposal(jobId, coverLetter, bidAmount, bidType, ...)
  - updateProposal(id, input)
  - withdrawProposal(id, reason)
  - connectsBalance

Endpoints:
  POST /bid/upwork        — generate proposal + submit to Upwork
  POST /bid/upwork/submit — submit raw proposal (no generation)
  POST /bid/upwork/{proposal_id}/withdraw
  GET  /bid/upwork/status — Connects balance + proposal stats
  GET  /health
"""

import os
import sys
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# Load .env before reading any env vars — keeps secrets out of shell history
load_dotenv()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS, QUICK_TIMEOUT
from shared.upwork_client import (
    UpworkGraphQLClient,
    BidRequest,
    RawBidRequest,
    ScoutingRequest,
    UserPlanResponse,
)
from shared.freelancer_client import (
    FreelancerClient,
    build_authorize_url,
    exchange_code_for_token,
    refresh_access_token,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("bid_service")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Docker mounts DB at /data/bid.db; local dev falls back to ./bid.db
_default_db = "/data/bid.db"
try:
    os.makedirs(os.path.dirname(_default_db), exist_ok=True)
    test_path = _default_db
except PermissionError:
    test_path = os.path.join(os.path.dirname(__file__), "bid.db")
BID_DB_PATH = os.getenv("BID_DB_PATH", test_path)
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
PROSPECTOR_URL = os.getenv("PROSPECTOR_URL", "http://localhost:8900")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

# Upwork OAuth — these MUST be set in .env or secrets_vault
UPWORK_CLIENT_ID = os.getenv("UPWORK_CLIENT_ID", "")
UPWORK_CLIENT_SECRET = os.getenv("UPWORK_CLIENT_SECRET", "")
UPWORK_ACCESS_TOKEN = os.getenv("UPWORK_ACCESS_TOKEN", "")
UPWORK_REFRESH_TOKEN = os.getenv("UPWORK_REFRESH_TOKEN", "")
UPWORK_API_URL = os.getenv("UPWORK_API_URL", "https://api.upwork.com/graphql")
UPWORK_OAUTH_URL = os.getenv("UPWORK_OAUTH_URL", "https://www.upwork.com/services/api/oauth2/token")

# Freelancer OAuth — set in .env or secrets_vault
FREELANCER_CLIENT_ID = os.getenv("FREELANCER_CLIENT_ID", "")
FREELANCER_CLIENT_SECRET = os.getenv("FREELANCER_CLIENT_SECRET", "")
FREELANCER_ACCESS_TOKEN = os.getenv("FREELANCER_ACCESS_TOKEN", "")
FREELANCER_REFRESH_TOKEN = os.getenv("FREELANCER_REFRESH_TOKEN", "")
FREELANCER_REDIRECT_URI = os.getenv(
    "FREELANCER_REDIRECT_URI",
    "http://localhost:9400/bid/freelancer/oauth/callback",
)

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pydantic models (bid_service-local)
# ---------------------------------------------------------------------------


class WithdrawRequest(BaseModel):
    reason: str = "Client requirements not aligned"


class UpdateBidRequest(BaseModel):
    cover_letter: str | None = None
    bid_amount: float | None = None
    estimated_duration: str | None = None


class OAuthTokenResponse(BaseModel):
    """Upwork OAuth token payload (local to bid_service)."""
    access_token: str
    refresh_token: str = ""
    expires_in: int = 3600
    token_type: str = "Bearer"


# ---------------------------------------------------------------------------
# Freelancer-local models
# ---------------------------------------------------------------------------


class FreelancerOAuthTokenResponse(BaseModel):
    """Freelancer OAuth token payload."""
    access_token: str
    refresh_token: str = ""
    expires_in: int = 3600
    token_type: str = "Bearer"


class FreelancerBidRequest(BaseModel):
    """Place a bid on a Freelancer project."""
    project_id: str
    bid_amount: float
    description: str = ""
    period: int = 14  # days
    bid_type: str = "fixed"


class FreelancerRawBidRequest(BaseModel):
    """Submit a pre-written Freelancer bid (no generation)."""
    project_id: str
    bid_amount: float
    description: str
    period: int = 14
    bid_type: str = "fixed"


class FreelancerSearchRequest(BaseModel):
    """Search Freelancer projects."""
    keyword: str = ""
    category: str = ""
    budget_min: float = 0
    budget_max: float = 0
    limit: int = 10


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

import aiosqlite

BIDS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bids (
    id TEXT PRIMARY KEY,
    prospect_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    proposal_id TEXT,
    platform TEXT NOT NULL DEFAULT 'upwork',
    bid_amount REAL NOT NULL,
    bid_type TEXT NOT NULL DEFAULT 'fixed',
    cover_letter TEXT,
    status TEXT NOT NULL DEFAULT 'submitted',
    connects_used INTEGER DEFAULT 0,
    remaining_connects INTEGER DEFAULT 0,
    llm_cost_usd REAL DEFAULT 0,
    error TEXT,
    submitted_at TEXT,
    updated_at TEXT
)

CREATE INDEX IF NOT EXISTS idx_bids_prospect ON bids(prospect_id)

CREATE INDEX IF NOT EXISTS idx_bids_status ON bids(status)
"""


async def _init_db():
    os.makedirs(os.path.dirname(BID_DB_PATH), exist_ok=True)
    async with aiosqlite.connect(BID_DB_PATH) as db:
        for stmt in BIDS_TABLE_SQL.strip().split("\n\n"):
            stmt = stmt.strip()
            if stmt:
                await db.execute(stmt)
        await db.commit()


async def _record_bid(db, bid_data: dict):
    async with db.execute(
        """INSERT OR REPLACE INTO bids
           (id, prospect_id, job_id, proposal_id, platform, bid_amount, bid_type,
            cover_letter, status, connects_used, remaining_connects, llm_cost_usd,
            error, submitted_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (bid_data["id"], bid_data["prospect_id"], bid_data["job_id"],
         bid_data.get("proposal_id", ""), bid_data.get("platform", "upwork"),
         bid_data["bid_amount"], bid_data["bid_type"],
         bid_data.get("cover_letter", ""), bid_data["status"],
         bid_data.get("connects_used", 0),
         bid_data.get("remaining_connects", 0),
         bid_data.get("llm_cost_usd", 0),
         bid_data.get("error", ""),
         bid_data.get("submitted_at", datetime.now(timezone.utc).isoformat()),
         datetime.now(timezone.utc).isoformat()),
    ):
        pass
    await db.commit()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

db_instance = None


@asynccontextmanager
async def lifespan(app):
    global db_instance
    await _init_db()
    db_instance = aiosqlite.connect(BID_DB_PATH)
    await db_instance.__aenter__()
    db_instance.row_factory = aiosqlite.Row
    logger.info("Bid Service ready (port 9400)")
    yield
    await db_instance.__aexit__(None, None, None)


app = FastAPI(title="Agent N9er Bid Service", lifespan=lifespan)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


def _upwork_client():
    """Get authenticated Upwork GraphQL client."""
    token = os.getenv("UPWORK_ACCESS_TOKEN", UPWORK_ACCESS_TOKEN)
    if not token:
        raise HTTPException(status_code=401,
                            detail="Upwork not authenticated. See /bid/upwork/oauth/setup")
    return UpworkGraphQLClient(token)


def _svc_headers():
    return {"Authorization": f"Bearer {SERVICE_TOKEN}"} if SERVICE_TOKEN else {}


# ---------------------------------------------------------------------------
# OAuth endpoints
# ---------------------------------------------------------------------------


@app.get("/bid/upwork/oauth/setup")
async def oauth_setup():
    """Return OAuth setup instructions for Upwork."""
    return {
        "ok": 1,
        "steps": [
            "1. Go to https://www.upwork.com/developer/keys/apply",
            "2. Create an OAuth app with the 'proposal_submit' scope",
            "3. Set UPWORK_CLIENT_ID, UPWORK_CLIENT_SECRET, UPWORK_ACCESS_TOKEN in .env",
        ],
        "oauth_url": UPWORK_OAUTH_URL,
        "token_configured": bool(UPWORK_ACCESS_TOKEN or os.getenv("UPWORK_ACCESS_TOKEN")),
    }


@app.post("/bid/upwork/oauth/token", response_model=UserPlanResponse)
async def set_oauth_token(token: OAuthTokenResponse):
    """Set/replace the Upwork OAuth access token at runtime."""
    import os as _os
    _os.environ["UPWORK_ACCESS_TOKEN"] = token.access_token
    if token.refresh_token:
        _os.environ["UPWORK_REFRESH_TOKEN"] = token.refresh_token
    logger.info("Upwork OAuth token updated (expires_in=%ds)", token.expires_in)
    # Also write to /tmp so it persists beyond this process if loaded
    try:
        with open("/tmp/upwork_token.json", "w") as f:
            json.dump(token.model_dump(), f)
    except Exception:
        pass
    return UserPlanResponse(
        action="set_oauth_token",
        detail=f"Token set. Expires in {token.expires_in}s. "
               f"Use POST /bid/upwork/oauth/refresh when needed."
    )


@app.post("/bid/upwork/oauth/refresh", response_model=UserPlanResponse)
async def refresh_oauth_token():
    """Refresh the Upwork OAuth token using refresh_token."""
    refresh = os.getenv("UPWORK_REFRESH_TOKEN", UPWORK_REFRESH_TOKEN)
    client_id = os.getenv("UPWORK_CLIENT_ID", UPWORK_CLIENT_ID)
    client_secret = os.getenv("UPWORK_CLIENT_SECRET", UPWORK_CLIENT_SECRET)

    if not refresh or not client_id or not client_secret:
        raise HTTPException(status_code=400,
                            detail="Cannot refresh: missing refresh_token, client_id, or client_secret")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(UPWORK_OAUTH_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": client_id,
            "client_secret": client_secret,
        })

    if resp.status_code != 200:
        raise HTTPException(status_code=400,
                            detail=f"Token refresh failed: {resp.text}")

    data = resp.json()
    os.environ["UPWORK_ACCESS_TOKEN"] = data["access_token"]
    if data.get("refresh_token"):
        os.environ["UPWORK_REFRESH_TOKEN"] = data["refresh_token"]

    try:
        with open("/tmp/upwork_token.json", "w") as f:
            json.dump(data, f)
    except Exception:
        pass

    logger.info("Upwork token refreshed")
    return UserPlanResponse(
        action="refresh_token",
        detail=f"Token refreshed. New access token set.",
    )


# ---------------------------------------------------------------------------
# Profile / Stats
# ---------------------------------------------------------------------------


@app.get("/bid/upwork/connects")
async def connects_balance():
    """Get current Connects balance from Upwork."""
    client = _upwork_client()
    data = await client.get_connects_balance()
    return {"ok": 1, "connects_balance": data.get("connectsBalance", {})}


@app.get("/bid/upwork/stats")
async def proposal_stats():
    """Get aggregate proposal statistics from Upwork."""
    client = _upwork_client()
    data = await client.get_proposal_stats()
    return {"ok": 1, "proposal_stats": data.get("proposalStats", {})}


@app.get("/bid/upwork/proposals")
async def list_proposals(status: str = None, limit: int = 20, offset: int = 0):
    """List submitted proposals from Upwork."""
    client = _upwork_client()
    data = await client.search_proposals(status=status, limit=limit, offset=offset)
    return {"ok": 1, "proposals": data}


# ---------------------------------------------------------------------------
# Bidding endpoints
# ---------------------------------------------------------------------------


@app.post("/bid/upwork", response_model=UserPlanResponse)
async def bid_on_prospect(req: BidRequest):
    """Full pipeline: fetch prospect details → generate proposal → submit to Upwork.

    This is the primary endpoint — connects Prospector → Agent Execution → Upwork.
    """
    import uuid

    # 1. Fetch prospect details from Prospector
    async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
        try:
            p_resp = await client.get(
                f"{PROSPECTOR_URL}/prospects/{req.prospect_id}",
                headers=_svc_headers(),
            )
            if p_resp.status_code != 200:
                raise HTTPException(status_code=404,
                                    detail=f"Prospect {req.prospect_id} not found in Prospector")
            prospect = p_resp.json()
        except httpx.RequestError as e:
            raise HTTPException(status_code=503,
                                detail=f"Prospector unreachable: {e}")

    job_id = prospect.get("platform_job_id", "")
    title = prospect.get("title", "Untitled Project")
    description = prospect.get("description", "")
    skills = prospect.get("skills", "")
    budget_max = prospect.get("budget_max", 0)

    # 2. Generate proposal via Agent Execution LLM
    proposal_text = ""
    llm_cost = 0.0
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            gen_resp = await client.post(
                f"{EXECUTION_URL}/proposal",
                json={
                    "prospect_id": req.prospect_id,
                    "title": title,
                    "description": description,
                    "platform": "upwork",
                    "budget_max": budget_max,
                    "skills": skills,
                    "tone": req.tone,
                },
                headers=_svc_headers(),
            )
            if gen_resp.status_code == 200:
                gen_data = gen_resp.json()
                proposal_text = gen_data.get("proposal",
                                             f"Experienced professional interested in {title}.")
                llm_cost = gen_data.get("cost_usd", 0)
            else:
                proposal_text = (f"I have extensive experience in the skills required for "
                                 f"'{title}' and am confident I can deliver high-quality results. "
                                 f"Looking forward to discussing the details.")
        except httpx.RequestError as e:
            proposal_text = (f"I am interested in the '{title}' project. "
                             f"My background aligns well with these requirements.")
            logger.warning("Proposal generation fallback: %s", e)

    # 3. Submit to Upwork
    client = _upwork_client()
    result = await client.submit_proposal(
        job_id=job_id,
        cover_letter=proposal_text,
        bid_amount=req.bid_amount,
        bid_type=req.bid_type,
        estimated_duration=req.estimated_duration,
        answers=req.answers if req.answers else None,
    )

    proposal = result.get("proposal", {})
    bid_id = str(uuid.uuid4())

    # 4. Record in local DB
    async with aiosqlite.connect(BID_DB_PATH) as db:
        await _record_bid(db, {
            "id": bid_id,
            "prospect_id": req.prospect_id,
            "job_id": job_id,
            "proposal_id": proposal.get("id", ""),
            "platform": "upwork",
            "bid_amount": req.bid_amount,
            "bid_type": req.bid_type,
            "cover_letter": proposal_text,
            "status": "submitted",
            "connects_used": result.get("connectsUsed", 0),
            "remaining_connects": result.get("remainingConnects", 0),
            "llm_cost_usd": llm_cost,
            "error": "",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })

    # 5. Update prospect status in Prospector
    async with httpx.AsyncClient(timeout=QUICK_TIMEOUT) as client:
        try:
            await client.patch(
                f"{PROSPECTOR_URL}/prospects/{req.prospect_id}",
                json={
                    "status": "applied",
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
                headers=_svc_headers(),
            )
        except httpx.RequestError:
            logger.warning("Could not update prospect %s status", req.prospect_id)

    logger.info(
        "Bid submitted to Upwork: job=%s amount=$%.2f connects=%d remaining=%d",
        job_id, req.bid_amount,
        result.get("connectsUsed", 0),
        result.get("remainingConnects", 0),
    )

    return UserPlanResponse(
        action="proposal_submitted",
        proposal_id=proposal.get("id", ""),
        proposal_status=proposal.get("status", "submitted"),
        connects_used=result.get("connectsUsed", 0),
        remaining_connects=result.get("remainingConnects", 0),
        cost_usd=llm_cost,
        mode=os.getenv("UPWORK_ACCESS_TOKEN", UPWORK_ACCESS_TOKEN) and "live" or "simulation",
        detail=f"Proposal submitted for '{title}' on Upwork. "
               f"Proposal ID: {proposal.get('id', 'unknown')}. "
               f"LLM cost: ${llm_cost:.6f}",
    )


@app.post("/bid/upwork/submit", response_model=UserPlanResponse)
async def submit_raw_proposal(req: RawBidRequest):
    """Submit a pre-written proposal directly to Upwork (no generation step)."""
    import uuid

    client = _upwork_client()
    result = await client.submit_proposal(
        job_id=req.job_id,
        cover_letter=req.cover_letter,
        bid_amount=req.bid_amount,
        bid_type=req.bid_type,
        estimated_duration=req.estimated_duration,
        answers=req.answers if req.answers else None,
    )

    proposal = result.get("proposal", {})

    bid_id = str(uuid.uuid4())
    async with aiosqlite.connect(BID_DB_PATH) as db:
        await _record_bid(db, {
            "id": bid_id,
            "prospect_id": "",
            "job_id": req.job_id,
            "proposal_id": proposal.get("id", ""),
            "platform": "upwork",
            "bid_amount": req.bid_amount,
            "bid_type": req.bid_type,
            "cover_letter": req.cover_letter,
            "status": "submitted",
            "connects_used": result.get("connectsUsed", 0),
            "remaining_connects": result.get("remainingConnects", 0),
            "llm_cost_usd": 0,
            "error": "",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })

    logger.info("Raw proposal submitted: job=%s amount=$%.2f connects=%d",
                req.job_id, req.bid_amount, result.get("connectsUsed", 0))

    return UserPlanResponse(
        action="raw_proposal_submitted",
        proposal_id=proposal.get("id", ""),
        proposal_status=proposal.get("status", "submitted"),
        connects_used=result.get("connectsUsed", 0),
        remaining_connects=result.get("remainingConnects", 0),
        detail=f"Raw proposal submitted. Proposal ID: {proposal.get('id', 'unknown')}",
    )


@app.post("/bid/upwork/{proposal_id}/withdraw", response_model=UserPlanResponse)
async def withdraw_proposal(proposal_id: str, req: WithdrawRequest = None):
    """Withdraw a previously submitted Upwork proposal."""
    reason = req.reason if req else "Withdrawn by Agent N9er"
    client = _upwork_client()
    result = await client.withdraw_proposal(proposal_id, reason)

    async with aiosqlite.connect(BID_DB_PATH) as db:
        await db.execute(
            "UPDATE bids SET status = 'withdrawn', updated_at = ? WHERE proposal_id = ?",
            (datetime.now(timezone.utc).isoformat(), proposal_id),
        )
        await db.commit()

    logger.info("Proposal %s withdrawn (refund=%d connects)",
                proposal_id, result.get("connectsRefunded", 0))

    return UserPlanResponse(
        action="withdrawn",
        proposal_id=proposal_id,
        proposal_status="withdrawn",
        connects_used=result.get("connectsRefunded", 0),
        detail=f"Proposal withdrawn. Refunded {result.get('connectsRefunded', 0)} Connects.",
    )


@app.patch("/bid/upwork/{proposal_id}", response_model=UserPlanResponse)
async def update_proposal(proposal_id: str, req: UpdateBidRequest):
    """Update a pending proposal (cover letter, bid amount, estimated duration)."""
    input_data = {}
    if req.cover_letter is not None:
        input_data["coverLetter"] = req.cover_letter
    if req.bid_amount is not None:
        input_data["bidAmount"] = req.bid_amount
    if req.estimated_duration is not None:
        input_data["estimatedDuration"] = req.estimated_duration

    if not input_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    client = _upwork_client()
    result = await client.update_proposal(proposal_id, input_data)

    async with aiosqlite.connect(BID_DB_PATH) as db:
        await db.execute(
            "UPDATE bids SET updated_at = ? WHERE proposal_id = ?",
            (datetime.now(timezone.utc).isoformat(), proposal_id),
        )
        await db.commit()

    return UserPlanResponse(
        action="updated",
        proposal_id=proposal_id,
        proposal_status=result.get("proposal", {}).get("status", "updated"),
        detail=f"Proposal {proposal_id} updated.",
    )


# ---------------------------------------------------------------------------
# Local bid history
# ---------------------------------------------------------------------------


@app.get("/bids")
async def list_local_bids(limit: int = 20, offset: int = 0):
    """List bid history from local database."""
    async with aiosqlite.connect(BID_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM bids ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return {"ok": 1, "total": len(rows), "bids": [dict(r) for r in rows]}


@app.get("/bids/{prospect_id}")
async def get_bid_for_prospect(prospect_id: str):
    """Get bid for a specific prospect."""
    async with aiosqlite.connect(BID_DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM bids WHERE prospect_id = ? ORDER BY submitted_at DESC LIMIT 1",
            (prospect_id,),
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No bid found for this prospect")
        return {"ok": 1, "bid": dict(row)}


@app.get("/health")
async def health():
    """Health check endpoint."""
    freelancer_token_present = _freelancer_pat_configured()
    freelancer_oauth = _freelancer_configured()
    return {
        "ok": 1,
        "service": "bid_service",
        "upwork_configured": bool(UPWORK_ACCESS_TOKEN or os.getenv("UPWORK_ACCESS_TOKEN")),
        "freelancer_configured": freelancer_token_present or freelancer_oauth,
        "freelancer_pat": freelancer_token_present,
        "freelancer_oauth_registered": freelancer_oauth,
        "execution_connected": bool(EXECUTION_URL),
        "prospector_connected": bool(PROSPECTOR_URL),
    }


# ---------------------------------------------------------------------------
# Search jobs directly via Upwork (useful for manual scouting)
# ---------------------------------------------------------------------------


@app.post("/bid/upwork/search")
async def search_upwork_jobs(req: ScoutingRequest):
    """Search Upwork jobs directly via GraphQL (not relying on RSS pre-scan)."""
    client = _upwork_client()
    data = await client.search_jobs(
        keyword=req.keyword,
        category=req.category,
        budget_min=req.budget_min or None,
        budget_max=req.budget_max or None,
        limit=min(req.limit, 50),
    )
    return {"ok": 1, "total": data.get("totalCount", 0), "jobs": data.get("edges", [])}


@app.get("/bid/upwork/job/{job_key}")
async def get_upwork_job(job_key: str):
    """Get detailed Upwork job posting information."""
    client = _upwork_client()
    job = await client.get_job_details(job_key)
    return {"ok": 1, "job": job}


# ---------------------------------------------------------------------------
# Freelancer — OAuth
# ---------------------------------------------------------------------------


def _freelancer_client() -> FreelancerClient | None:
    """Return a Freelancer client if a token is available, else None."""
    token = FREELANCER_ACCESS_TOKEN or os.getenv("FREELANCER_ACCESS_TOKEN", "")
    if not token:
        return None
    return FreelancerClient(access_token=token)


def _freelancer_client_or_raise() -> FreelancerClient:
    """Return a Freelancer client or raise 400 if unconfigured."""
    client = _freelancer_client()
    if client is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Freelancer not configured. "
                "Set FREELANCER_ACCESS_TOKEN env var first. "
                "Use /bid/freelancer/oauth/setup for OAuth flow (requires CLIENT_ID/SECRET)."
            ),
        )
    return client


def _freelancer_configured() -> bool:
    """Check whether Freelancer credentials exist."""
    return bool(FREELANCER_CLIENT_ID and FREELANCER_CLIENT_SECRET)

def _freelancer_pat_configured() -> bool:
    """Check whether a Freelancer Personal Access Token exists (sufficient for all bid operations)."""
    return bool(FREELANCER_ACCESS_TOKEN or os.getenv("FREELANCER_ACCESS_TOKEN"))


@app.get("/bid/freelancer/oauth/setup")
async def freelancer_oauth_setup():
    """Return the Freelancer OAuth authorize URL for the user to visit in a browser.

    After authorising, Freelancer redirects to our callback endpoint.
    """
    if not _freelancer_configured():
        raise HTTPException(
            status_code=400,
            detail="Set FREELANCER_CLIENT_ID and FREELANCER_CLIENT_SECRET env vars first.",
        )

    scopes = "basic,payment,projects,bids"
    auth_url = build_authorize_url(
        client_id=FREELANCER_CLIENT_ID,
        redirect_uri=FREELANCER_REDIRECT_URI,
        scope=scopes,
    )
    return {"authorize_url": auth_url}


@app.get("/bid/freelancer/oauth/callback")
async def freelancer_oauth_callback(code: str):
    """OAuth callback — exchange code for access token.

    Freelancer redirects here after the user authorizes. The code
    is exchanged for an access + refresh token.
    """
    if not _freelancer_configured():
        raise HTTPException(status_code=400, detail="Freelancer OAuth not configured.")

    token_data = await exchange_code_for_token(
        client_id=FREELANCER_CLIENT_ID,
        client_secret=FREELANCER_CLIENT_SECRET,
        code=code,
        redirect_uri=FREELANCER_REDIRECT_URI,
    )

    return FreelancerOAuthTokenResponse(
        access_token=token_data.get("access_token", ""),
        refresh_token=token_data.get("refresh_token", ""),
        expires_in=token_data.get("expires_in", 3600),
        token_type=token_data.get("token_type", "Bearer"),
    )


@app.post("/bid/freelancer/oauth/refresh")
async def freelancer_oauth_refresh():
    """Refresh the Freelancer access token using the stored refresh token."""
    if not _freelancer_configured():
        raise HTTPException(status_code=400, detail="Freelancer OAuth not configured.")
    refresh = FREELANCER_REFRESH_TOKEN or os.getenv("FREELANCER_REFRESH_TOKEN")
    if not refresh:
        raise HTTPException(status_code=400, detail="No refresh token stored.")

    token_data = await refresh_access_token(
        client_id=FREELANCER_CLIENT_ID,
        client_secret=FREELANCER_CLIENT_SECRET,
        refresh_token=refresh,
    )

    return FreelancerOAuthTokenResponse(
        access_token=token_data.get("access_token", ""),
        refresh_token=token_data.get("refresh_token", ""),
        expires_in=token_data.get("expires_in", 3600),
        token_type=token_data.get("token_type", "Bearer"),
    )


# ---------------------------------------------------------------------------
# Freelancer — bid submission
# ---------------------------------------------------------------------------


@app.post("/bid/freelancer/connect")
async def freelancer_connect():
    """Test that the Freelancer client can reach the API and return user info."""
    client = _freelancer_client_or_raise()
    try:
        stats = await client.get_stats()
        balance = await client.get_balance()
        return {
            "ok": 1,
            "connected": True,
            "user_id": stats.get("user_id"),
            "username": stats.get("username"),
            "balance": balance.get("available"),
            "currency": balance.get("currency"),
        }
    except httpx.HTTPStatusError as e:
        return {"ok": 0, "connected": False, "error": str(e)}


@app.post("/bid/freelancer/submit")
async def freelancer_submit(req: FreelancerBidRequest):
    """Submit a bid to a Freelancer project.

    Uses generated cover letter. For a pre-written version use
    /bid/freelancer/raw-submit.
    """
    client = _freelancer_client_or_raise()
    cover_letter = req.description or f"Placing bid on project {req.project_id}."
    result = await client.submit_proposal(
        job_id=req.project_id,
        cover_letter=cover_letter,
        bid_amount=req.bid_amount,
        bid_type=req.bid_type,
        estimated_duration=f"{req.period} days",
    )
    return {"ok": 1, "platform": "freelancer", "bid": result}


@app.post("/bid/freelancer/raw-submit")
async def freelancer_raw_submit(req: FreelancerRawBidRequest):
    """Submit a pre-written bid to a Freelancer project (no LLM generation)."""
    client = _freelancer_client_or_raise()
    result = await client.submit_proposal(
        job_id=req.project_id,
        cover_letter=req.description,
        bid_amount=req.bid_amount,
        bid_type=req.bid_type,
        estimated_duration=f"{req.period} days",
    )
    return {"ok": 1, "platform": "freelancer", "bid": result}


@app.post(
    "/bid/freelancer/{proposal_id}/withdraw",
    response_model=UserPlanResponse,
)
async def freelancer_withdraw(proposal_id: str, reason: str = ""):
    """Withdraw a pending Freelancer bid."""
    client = _freelancer_client_or_raise()
    result = await client.withdraw_proposal(proposal_id, reason)

    async with aiosqlite.connect(BID_DB_PATH) as db:
        await db.execute(
            "UPDATE bids SET updated_at = ?, status = ?, platform = ? "
            "WHERE proposal_id = ?",
            (datetime.now(timezone.utc).isoformat(), "withdrawn", "freelancer", proposal_id),
        )
        await db.commit()

    return UserPlanResponse(
        action="withdrawn",
        proposal_id=proposal_id,
        proposal_status="withdrawn",
        detail=f"Freelancer bid {proposal_id} withdrawn.",
    )


@app.post(
    "/bid/freelancer/{proposal_id}/update",
    response_model=UserPlanResponse,
)
async def freelancer_update(proposal_id: str, req: FreelancerBidRequest):
    """Update an existing Freelancer bid."""
    client = _freelancer_client_or_raise()
    input_data = {
        "amount": req.bid_amount,
        "description": req.description,
        "period": req.period,
    }
    result = await client.update_proposal(proposal_id, input_data)

    async with aiosqlite.connect(BID_DB_PATH) as db:
        await db.execute(
            "UPDATE bids SET updated_at = ? WHERE proposal_id = ?",
            (datetime.now(timezone.utc).isoformat(), proposal_id),
        )
        await db.commit()

    return UserPlanResponse(
        action="updated",
        proposal_id=proposal_id,
        proposal_status=result.get("status", "updated"),
        detail=f"Freelancer bid {proposal_id} updated.",
    )


# ---------------------------------------------------------------------------
# Freelancer — search & stats
# ---------------------------------------------------------------------------


@app.post("/bid/freelancer/search")
async def freelancer_search(req: FreelancerSearchRequest):
    """Search Freelancer projects."""
    client = _freelancer_client_or_raise()
    data = await client.search_jobs(
        keyword=req.keyword or None,
        category=req.category or None,
        budget_min=req.budget_min or None,
        budget_max=req.budget_max or None,
        limit=min(req.limit, 50),
    )
    projects = data.get("projects", data) if isinstance(data, dict) else data
    return {"ok": 1, "platform": "freelancer", "projects": projects}


@app.get("/bid/freelancer/stats")
async def freelancer_stats():
    """Get Freelancer account stats and balance."""
    client = _freelancer_client_or_raise()
    stats = await client.get_stats()
    balance = await client.get_balance()
    return {
        "ok": 1,
        "platform": "freelancer",
        "stats": stats,
        "balance": balance,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "9400"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")