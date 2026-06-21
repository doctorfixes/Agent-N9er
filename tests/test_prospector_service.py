"""Tests for the prospector service — job discovery and prospect lifecycle."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("PROSPECTOR_DB_PATH", os.path.join(_tmpdir, "test_prospector.db"))

prospector = load_service("prosp_main", "prospector_service")


@pytest.fixture(autouse=True)
async def reset_db():
    yield
    try:
        async with aiosqlite.connect(prospector.DB_PATH) as db:
            await db.execute("DELETE FROM prospects")
            await db.commit()
    except Exception:
        pass


@pytest.fixture
async def client():
    async with prospector.lifespan(prospector.app):
        transport = ASGITransport(app=prospector.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Upwork Jobs</title>
<item>
  <title>Build a React Dashboard</title>
  <link>https://upwork.com/jobs/123</link>
  <description>Need a React developer to build admin dashboard. Budget: $500 - $1,000</description>
  <guid>job-123</guid>
</item>
<item>
  <title>Fix Python Script</title>
  <link>https://upwork.com/jobs/456</link>
  <description>Small fix needed. Budget: $50</description>
  <guid>job-456</guid>
</item>
</channel></rss>"""


class TestScan:
    async def test_scan_upwork_rss(self, client):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "upwork"})

        data = resp.json()
        assert data["ok"] == 1
        assert data["discovered"] == 2
        assert data["new"] == 2

    async def test_scan_deduplicates(self, client):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            await client.post("/scan", json={"platform": "upwork"})
            resp = await client.post("/scan", json={"platform": "upwork"})

        assert resp.json()["new"] == 0

    async def test_scan_unsupported_platform(self, client):
        resp = await client.post("/scan", json={"platform": "fiverr"})
        assert resp.status_code == 400


class TestProspects:
    async def test_list_empty(self, client):
        resp = await client.get("/prospects")
        assert resp.json() == []

    async def test_list_with_data(self, client):
        await prospector._save_prospect({
            "id": "p1", "platform": "upwork", "platform_job_id": "j1",
            "title": "Test Job", "description": "Desc", "budget_min": 100,
            "budget_max": 500, "status": "discovered", "skills": "python",
        })
        resp = await client.get("/prospects")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test Job"

    async def test_filter_by_status(self, client):
        await prospector._save_prospect({
            "id": "p2", "platform": "upwork", "platform_job_id": "j2",
            "title": "Discovered", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered",
        })
        await prospector._save_prospect({
            "id": "p3", "platform": "upwork", "platform_job_id": "j3",
            "title": "Approved", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "approved",
        })
        resp = await client.get("/prospects", params={"status": "approved"})
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "approved"

    async def test_get_prospect_by_id(self, client):
        await prospector._save_prospect({
            "id": "p4", "platform": "upwork", "platform_job_id": "j4",
            "title": "Specific Job", "description": "Details",
            "budget_min": 0, "budget_max": 0, "status": "discovered",
        })
        resp = await client.get("/prospects/p4")
        assert resp.json()["title"] == "Specific Job"

    async def test_get_nonexistent_404(self, client):
        resp = await client.get("/prospects/nonexistent")
        assert resp.status_code == 404


class TestProspectLifecycle:
    async def test_update_status(self, client):
        await prospector._save_prospect({
            "id": "lc1", "platform": "upwork", "platform_job_id": "jlc1",
            "title": "Lifecycle", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered",
        })
        resp = await client.patch("/prospects/lc1", json={"status": "approved"})
        assert resp.json()["ok"] == 1

        prospect = (await client.get("/prospects/lc1")).json()
        assert prospect["status"] == "approved"

    async def test_invalid_status_rejected(self, client):
        await prospector._save_prospect({
            "id": "lc2", "platform": "upwork", "platform_job_id": "jlc2",
            "title": "Bad Status", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered",
        })
        resp = await client.patch("/prospects/lc2", json={"status": "bogus"})
        assert resp.status_code == 422

    async def test_timestamp_set_on_applied(self, client):
        await prospector._save_prospect({
            "id": "lc3", "platform": "upwork", "platform_job_id": "jlc3",
            "title": "Apply", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "approved",
        })
        await client.patch("/prospects/lc3", json={"status": "applied"})
        prospect = (await client.get("/prospects/lc3")).json()
        assert prospect["applied_at"] is not None


class TestStats:
    async def test_stats_empty(self, client):
        resp = await client.get("/stats")
        data = resp.json()
        assert data["total_prospects"] == 0
        assert data["revenue"] == 0


class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        assert resp.json()["ok"] == 1


class TestBudgetParsing:
    def test_range_budget(self):
        desc = "Budget: $500 - $1,000"
        assert prospector._extract_budget(desc, "min") > 0

    def test_single_budget(self):
        desc = "We have $250 for this project"
        assert prospector._extract_budget(desc, "min") == 250

    def test_no_budget(self):
        assert prospector._extract_budget("No money mentioned", "min") == 0
