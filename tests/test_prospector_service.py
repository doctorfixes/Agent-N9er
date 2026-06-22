"""Tests for the prospector service — job discovery and prospect lifecycle."""

import os
import time
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


@pytest.fixture(autouse=True)
def reset_scan_cooldown():
    prospector._last_scan_time.clear()
    yield
    prospector._last_scan_time.clear()


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
            prospector._last_scan_time.clear()
            resp = await client.post("/scan", json={"platform": "upwork"})

        assert resp.json()["new"] == 0

    async def test_scan_unsupported_platform(self, client):
        resp = await client.post("/scan", json={"platform": "nonexistent_platform"})
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


class TestDeduplication:
    async def test_dedup_insert_or_ignore(self, client):
        p = {
            "id": "d1", "platform": "upwork", "platform_job_id": "dup-1",
            "title": "Dup Job", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered", "skills": "",
        }
        result1 = await prospector._save_prospect_dedup(p)
        assert result1 is True

        p2 = dict(p, id="d2")
        result2 = await prospector._save_prospect_dedup(p2)
        assert result2 is False

    async def test_dedup_different_platforms_allowed(self, client):
        p1 = {
            "id": "d3", "platform": "upwork", "platform_job_id": "same-id",
            "title": "Job 1", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered", "skills": "",
        }
        p2 = {
            "id": "d4", "platform": "freelancer", "platform_job_id": "same-id",
            "title": "Job 2", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered", "skills": "",
        }
        assert await prospector._save_prospect_dedup(p1) is True
        assert await prospector._save_prospect_dedup(p2) is True


class TestNotifications:
    async def test_send_alert_skips_without_smtp(self):
        original = prospector.SMTP_HOST
        prospector.SMTP_HOST = ""
        try:
            await prospector._send_prospect_alert([{"platform": "upwork", "title": "Test", "budget_max": 500}])
        finally:
            prospector.SMTP_HOST = original

    @patch("smtplib.SMTP")
    async def test_send_alert_with_smtp(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        original_host = prospector.SMTP_HOST
        original_email = prospector.NOTIFY_EMAIL
        prospector.SMTP_HOST = "smtp.test.com"
        prospector.NOTIFY_EMAIL = "test@test.com"
        try:
            await prospector._send_prospect_alert([
                {"platform": "upwork", "title": "High Value Job", "budget_max": 1000, "url": "https://example.com"},
            ])
            mock_smtp_class.assert_called_once()
        finally:
            prospector.SMTP_HOST = original_host
            prospector.NOTIFY_EMAIL = original_email


class TestAutoEvaluate:
    async def test_auto_evaluate_calls_evaluator(self, client):
        await prospector._save_prospect_dedup({
            "id": "ae1", "platform": "upwork", "platform_job_id": "ae-job-1",
            "title": "Auto Eval Job", "description": "Build something",
            "budget_min": 100, "budget_max": 500, "status": "discovered", "skills": "python",
        })

        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "evaluation_id": "eval-1", "viable": True,
            "quoted_price_usd": 450, "estimated_cost_usd": 150,
        })
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            count = await prospector._auto_evaluate_batch([{
                "id": "ae1", "platform": "upwork", "title": "Auto Eval Job",
                "description": "Build something", "budget_min": 100, "budget_max": 500,
                "skills": "python",
            }])

        assert count == 1

        prospect = (await client.get("/prospects/ae1")).json()
        assert prospect["status"] == "approved"
        assert prospect["quoted_price"] == 450


class TestPlatforms:
    async def test_platforms_list(self, client):
        resp = await client.get("/platforms")
        data = resp.json()
        assert len(data) == 25
        names = [p["name"] for p in data]
        assert "upwork" in names
        assert "github_bounties" in names
        assert "superteam_earn" in names
        assert "gitcoin" in names
        assert "topcoder" in names
        assert "hackerone" in names
        assert "kaggle" in names
        assert "algora" in names
        assert "onlydust" in names
        assert "freelancer" in names
        assert "web_search" in names
        assert "reddit" in names
        assert "hackernews" in names
        assert "craigslist" in names
        assert "stackoverflow" in names
        assert "custom_rss" in names

    async def test_all_platforms_have_scanners(self, client):
        resp = await client.get("/platforms")
        for p in resp.json():
            assert p["name"] in prospector.SCANNERS, f"Missing scanner for {p['name']}"

    async def test_platform_entries_have_required_fields(self, client):
        resp = await client.get("/platforms")
        for p in resp.json():
            assert "name" in p
            assert "label" in p
            assert "status" in p
            assert "type" in p
            assert "description" in p


SAMPLE_DDG_HTML = """
<div class="result">
  <a class="result__a" href="https://example.com/job1">Build me a dashboard</a>
  <a class="result__snippet">Looking for developer to build React dashboard. Budget: $500</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/job2">Python automation needed</a>
  <a class="result__snippet">Need a Python script to automate data pipeline. $200 budget</a>
</div>
"""

SAMPLE_REDDIT_JSON = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "reddit1",
                    "title": "[Hiring] Need a Python developer for web scraping project",
                    "selftext": "Looking for someone to build a web scraper. Budget $300-$500.",
                    "permalink": "/r/forhire/comments/abc123/hiring_python_developer/",
                    "link_flair_text": "Hiring",
                }
            },
            {
                "data": {
                    "id": "reddit2",
                    "title": "[Hiring] React frontend developer needed",
                    "selftext": "Building a SaaS dashboard. $1000 budget.",
                    "permalink": "/r/forhire/comments/def456/hiring_react_developer/",
                    "link_flair_text": "Hiring",
                }
            },
        ]
    }
}

SAMPLE_HN_JSON = {
    "hits": [
        {
            "objectID": "hn123",
            "title": "Ask HN: Freelance developer needed for startup",
            "story_text": "We need a backend developer for our API. Budget $2000.",
            "url": "",
        },
        {
            "objectID": "hn456",
            "title": "Show HN: Looking for contract developer",
            "story_text": "",
            "url": "https://example.com/job",
        },
    ]
}


class TestWebSearch:
    async def test_scan_web_search(self, client):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_DDG_HTML
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "web_search", "query": "freelance developer"})

        data = resp.json()
        assert data["ok"] == 1
        assert data["discovered"] >= 1

    def test_parse_ddg_html(self):
        results = prospector._parse_ddg_html(SAMPLE_DDG_HTML)
        assert len(results) == 2
        assert "dashboard" in results[0]["title"].lower()

    def test_url_to_id_deterministic(self):
        id1 = prospector._url_to_id("https://example.com/job1")
        id2 = prospector._url_to_id("https://example.com/job1")
        id3 = prospector._url_to_id("https://example.com/job2")
        assert id1 == id2
        assert id1 != id3


class TestReddit:
    async def test_scan_reddit(self, client):
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value=SAMPLE_REDDIT_JSON)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "reddit", "category": "forhire"})

        data = resp.json()
        assert data["ok"] == 1
        assert data["discovered"] >= 1


class TestHackerNews:
    async def test_scan_hackernews(self, client):
        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value=SAMPLE_HN_JSON)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "hackernews"})

        data = resp.json()
        assert data["ok"] == 1
        assert data["discovered"] == 2


class TestMultiScan:
    async def test_multi_scan_selected_platforms(self, client):
        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS
        mock_resp.json = MagicMock(return_value=SAMPLE_HN_JSON)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan/multi", json={
                "platforms": ["upwork", "hackernews"],
                "query": "python",
                "max_per_platform": 5,
            })

        data = resp.json()
        assert data["ok"] == 1
        assert data["platforms_scanned"] == 2
        assert "upwork" in data["results"]
        assert "hackernews" in data["results"]

    async def test_multi_scan_respects_cooldown(self, client):
        prospector._last_scan_time["upwork"] = time.monotonic()

        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value=SAMPLE_HN_JSON)
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan/multi", json={
                "platforms": ["upwork", "hackernews"],
                "max_per_platform": 5,
            })

        data = resp.json()
        assert data["results"]["upwork"]["skipped"] is True
        assert "hackernews" in data["results"]


class TestScanKeywords:
    async def test_get_keywords(self, client):
        resp = await client.get("/scan/keywords")
        data = resp.json()
        assert "keywords" in data
        assert len(data["keywords"]) > 0
        assert "reddit_subreddits" in data
        assert "craigslist_regions" in data
        assert "custom_rss_feeds" in data


class TestCustomRSS:
    async def test_custom_rss_empty_feeds(self, client):
        original = prospector.CUSTOM_RSS_FEEDS
        prospector.CUSTOM_RSS_FEEDS = []
        try:
            resp = await client.post("/scan", json={"platform": "custom_rss"})
            data = resp.json()
            assert data["ok"] == 1
            assert data["discovered"] == 0
        finally:
            prospector.CUSTOM_RSS_FEEDS = original
