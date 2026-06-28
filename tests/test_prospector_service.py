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
    def test_send_alert_skips_without_smtp(self):
        original = prospector.SMTP_HOST
        prospector.SMTP_HOST = ""
        try:
            prospector._send_prospect_alert([{"platform": "upwork", "title": "Test", "budget_max": 500}])
        finally:
            prospector.SMTP_HOST = original

    @patch("smtplib.SMTP")
    def test_send_alert_with_smtp(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

        original_host = prospector.SMTP_HOST
        original_email = prospector.NOTIFY_EMAIL
        prospector.SMTP_HOST = "smtp.test.com"
        prospector.NOTIFY_EMAIL = "test@test.com"
        try:
            prospector._send_prospect_alert([
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
        assert len(data) == 19
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


# ---------------------------------------------------------------------------
# Helper to build a mock httpx client for scanner tests
# ---------------------------------------------------------------------------

def _mock_http_get(response_json=None, response_text=None, status_code=200):
    """Build a mock httpx.AsyncClient that returns a canned response for GET."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()
    if response_json is not None:
        mock_resp.json = MagicMock(return_value=response_json)
    if response_text is not None:
        mock_resp.text = response_text

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(return_value=mock_resp)
    mock_http.post = AsyncMock(return_value=mock_resp)
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


def _mock_http_error():
    """Build a mock httpx.AsyncClient whose get/post raises RequestError."""
    import httpx as _httpx

    mock_http = AsyncMock()
    mock_http.get = AsyncMock(side_effect=_httpx.RequestError("connection failed"))
    mock_http.post = AsyncMock(side_effect=_httpx.RequestError("connection failed"))
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    return mock_http


# ---------------------------------------------------------------------------
# Scanner tests — GitHub Bounties
# ---------------------------------------------------------------------------

class TestScanGitHub:
    async def test_scan_github_success(self, client):
        fake_data = {
            "items": [
                {
                    "id": 100,
                    "title": "Fix memory leak",
                    "body": "Reward: $500 for fixing this bug",
                    "html_url": "https://github.com/org/repo/issues/1",
                    "labels": [{"name": "bounty"}, {"name": "bug"}],
                },
                {
                    "id": 101,
                    "title": "Add feature",
                    "body": "No budget info here",
                    "html_url": "https://github.com/org/repo/issues/2",
                    "labels": [],
                },
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "github_bounties"})
        data = resp.json()
        assert data["ok"] == 1
        assert data["discovered"] == 2
        assert data["platform"] == "github_bounties"

    async def test_scan_github_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "github_bounties"})
        assert resp.json()["discovered"] == 0

    async def test_scan_github_direct(self, client):
        fake_data = {
            "items": [
                {
                    "id": 200,
                    "title": "Bounty task",
                    "body": "$1,000 reward",
                    "html_url": "https://github.com/o/r/issues/3",
                    "labels": [{"name": "bounty"}],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_github("security", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "github_bounties"
        assert results[0]["budget_max"] == 1000.0
        assert "bounty" in results[0]["skills"]


# ---------------------------------------------------------------------------
# Scanner tests — Superteam Earn
# ---------------------------------------------------------------------------

class TestScanSuperteam:
    async def test_scan_superteam_success(self, client):
        fake_data = [
            {
                "id": "st-1",
                "title": "Build Solana dApp",
                "description": "Create a decentralized application",
                "rewardAmount": 2000,
                "slug": "build-solana-dapp",
                "skills": ["rust", "solana"],
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "superteam_earn"})
        assert resp.json()["discovered"] == 1

    async def test_scan_superteam_dict_response(self, client):
        fake_data = {
            "bounties": [
                {
                    "id": "st-2",
                    "title": "Design UI",
                    "description": "UI design task",
                    "rewardAmount": 500,
                    "slug": "design-ui",
                    "skills": ["figma"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_superteam("", "", 10)
        assert len(results) == 1
        assert results[0]["budget_max"] == 500.0

    async def test_scan_superteam_query_filter(self, client):
        fake_data = [
            {"id": "st-3", "title": "Rust project", "description": "", "rewardAmount": 100, "slug": "rust", "skills": []},
            {"id": "st-4", "title": "Python work", "description": "", "rewardAmount": 200, "slug": "python", "skills": []},
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_superteam("python", "", 10)
        assert len(results) == 1
        assert results[0]["title"] == "Python work"

    async def test_scan_superteam_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_superteam("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Gitcoin
# ---------------------------------------------------------------------------

class TestScanGitcoin:
    async def test_scan_gitcoin_success(self, client):
        fake_data = [
            {
                "pk": 1001,
                "title": "Smart contract audit",
                "issue_description_text": "Audit the token contract",
                "value_in_usdt": 5000,
                "url": "https://gitcoin.co/issue/1001",
                "keywords": ["solidity", "audit"],
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_gitcoin("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "gitcoin"
        assert results[0]["budget_max"] == 5000.0
        assert "solidity" in results[0]["skills"]

    async def test_scan_gitcoin_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_gitcoin("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Dework
# ---------------------------------------------------------------------------

class TestScanDework:
    async def test_scan_dework_success(self, client):
        fake_data = {
            "data": {
                "tasks": [
                    {
                        "id": "dw-1",
                        "title": "Build Discord bot",
                        "description": "A bot for our DAO",
                        "reward": {"amount": 300, "currency": "USDC"},
                        "permalink": "https://dework.xyz/task/dw-1",
                        "tags": [{"label": "discord"}, {"label": "typescript"}],
                    }
                ]
            }
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_dework("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "dework"
        assert results[0]["budget_max"] == 300.0
        assert "discord" in results[0]["skills"]

    async def test_scan_dework_query_filter(self, client):
        fake_data = {
            "data": {
                "tasks": [
                    {"id": "dw-2", "title": "Frontend work", "description": "", "reward": {}, "permalink": "", "tags": []},
                    {"id": "dw-3", "title": "Backend API", "description": "", "reward": {"amount": 100}, "permalink": "", "tags": []},
                ]
            }
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_dework("backend", "", 10)
        assert len(results) == 1

    async def test_scan_dework_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_dework("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Layer3
# ---------------------------------------------------------------------------

class TestScanLayer3:
    async def test_scan_layer3_success(self, client):
        fake_data = {
            "quests": [
                {
                    "id": "l3-1",
                    "title": "Bridge tokens quest",
                    "description": "Bridge tokens to L2",
                    "reward": {"amount": 50},
                    "url": "https://layer3.xyz/quests/l3-1",
                    "tags": ["defi", "bridge"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_layer3("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "layer3"
        assert results[0]["budget_max"] == 50.0

    async def test_scan_layer3_list_response(self, client):
        fake_data = [
            {"id": "l3-2", "name": "Swap quest", "description": "", "xp": 100, "url": "", "tags": []}
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_layer3("", "", 10)
        assert len(results) == 1
        assert results[0]["budget_max"] == 100.0

    async def test_scan_layer3_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_layer3("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Replit Bounties
# ---------------------------------------------------------------------------

class TestScanReplit:
    async def test_scan_replit_success(self, client):
        fake_data = {
            "items": [
                {
                    "id": "rp-1",
                    "title": "Build a CLI tool",
                    "description": "Create a CLI tool in Python",
                    "amount": 150,
                    "url": "https://replit.com/bounties/rp-1",
                    "tags": ["python", "cli"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_replit("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "replit_bounties"
        assert results[0]["budget_max"] == 150.0

    async def test_scan_replit_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_replit("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Zealy
# ---------------------------------------------------------------------------

class TestScanZealy:
    async def test_scan_zealy_success(self, client):
        fake_data = {
            "communities": [
                {
                    "id": "z-1",
                    "name": "Cool DAO",
                    "description": "Community quests",
                    "subdomain": "cooldao",
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_zealy("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "zealy"
        assert "Zealy Quest:" in results[0]["title"]

    async def test_scan_zealy_query_filter(self, client):
        fake_data = {
            "communities": [
                {"id": "z-2", "name": "Alpha DAO", "description": "", "subdomain": "alpha"},
                {"id": "z-3", "name": "Beta Protocol", "description": "", "subdomain": "beta"},
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_zealy("beta", "", 10)
        assert len(results) == 1
        assert "Beta" in results[0]["title"]

    async def test_scan_zealy_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_zealy("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Galxe
# ---------------------------------------------------------------------------

class TestScanGalxe:
    async def test_scan_galxe_success(self, client):
        fake_data = {
            "data": {
                "campaigns": {
                    "list": [
                        {
                            "id": "gx-1",
                            "name": "NFT Campaign",
                            "description": "Mint an NFT",
                            "loyaltyPoints": 200,
                            "chain": "ETH",
                        }
                    ]
                }
            }
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_galxe("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "galxe"
        assert results[0]["budget_max"] == 200.0

    async def test_scan_galxe_query_filter(self, client):
        fake_data = {
            "data": {
                "campaigns": {
                    "list": [
                        {"id": "gx-2", "name": "Airdrop", "description": "", "loyaltyPoints": 0},
                        {"id": "gx-3", "name": "Staking quest", "description": "", "loyaltyPoints": 50},
                    ]
                }
            }
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_galxe("staking", "", 10)
        assert len(results) == 1

    async def test_scan_galxe_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_galxe("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Questbook
# ---------------------------------------------------------------------------

class TestScanQuestbook:
    async def test_scan_questbook_success(self, client):
        fake_data = {
            "grants": [
                {
                    "id": "qb-1",
                    "title": "DeFi Grant",
                    "description": "Build a DeFi protocol",
                    "reward": 10000,
                    "url": "https://questbook.app/grants/qb-1",
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_questbook("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "questbook"
        assert results[0]["budget_max"] == 10000.0

    async def test_scan_questbook_query_filter(self, client):
        fake_data = {
            "grants": [
                {"id": "qb-2", "title": "NFT Grant", "description": "", "reward": 5000, "url": ""},
                {"id": "qb-3", "title": "DeFi Innovation", "description": "", "reward": 8000, "url": ""},
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_questbook("defi", "", 10)
        assert len(results) == 1
        assert results[0]["title"] == "DeFi Innovation"

    async def test_scan_questbook_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_questbook("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — OnlyDust
# ---------------------------------------------------------------------------

class TestScanOnlyDust:
    async def test_scan_onlydust_success(self, client):
        fake_data = {
            "projects": [
                {
                    "id": "od-1",
                    "name": "Web3 Toolkit",
                    "shortDescription": "A toolkit for web3 devs",
                    "slug": "web3-toolkit",
                    "technologies": ["rust", "typescript"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_onlydust("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "onlydust"
        assert "OnlyDust:" in results[0]["title"]
        assert "rust" in results[0]["skills"]

    async def test_scan_onlydust_query_filter(self, client):
        fake_data = {
            "projects": [
                {"id": "od-2", "name": "ZK Prover", "shortDescription": "", "slug": "zk", "technologies": []},
                {"id": "od-3", "name": "Token Bridge", "shortDescription": "", "slug": "bridge", "technologies": []},
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_onlydust("bridge", "", 10)
        assert len(results) == 1

    async def test_scan_onlydust_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_onlydust("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Freelancer.com
# ---------------------------------------------------------------------------

class TestScanFreelancer:
    async def test_scan_freelancer_success(self, client):
        fake_data = {
            "result": {
                "projects": [
                    {
                        "id": 9001,
                        "title": "Build a WordPress site",
                        "preview_description": "Need a WordPress developer",
                        "budget": {"minimum": 200, "maximum": 800},
                        "seo_url": "build-wordpress-site",
                        "jobs": [{"name": "WordPress"}, {"name": "PHP"}],
                    }
                ]
            }
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_freelancer("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "freelancer"
        assert results[0]["budget_min"] == 200.0
        assert results[0]["budget_max"] == 800.0
        assert "WordPress" in results[0]["skills"]

    async def test_scan_freelancer_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_freelancer("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Fiverr
# ---------------------------------------------------------------------------

class TestScanFiverr:
    async def test_scan_fiverr_success(self, client):
        fake_data = {
            "buyer_requests": [
                {
                    "id": "fv-1",
                    "title": "Logo Design",
                    "description": "Need a modern logo",
                    "budget_min": 50,
                    "budget_max": 200,
                    "url": "https://fiverr.com/requests/fv-1",
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_fiverr("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "fiverr"
        assert results[0]["budget_max"] == 200.0

    async def test_scan_fiverr_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_fiverr("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Topcoder
# ---------------------------------------------------------------------------

class TestScanTopcoder:
    async def test_scan_topcoder_success(self, client):
        fake_data = [
            {
                "id": "tc-1",
                "name": "Algorithm Challenge",
                "description": "Solve a dynamic programming problem",
                "prizeSets": [
                    {"prizes": [{"value": 1000}, {"value": 500}]}
                ],
                "tags": ["algorithms", "python"],
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_topcoder("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "topcoder"
        assert results[0]["budget_max"] == 1500.0  # 1000 + 500
        assert "algorithms" in results[0]["skills"]

    async def test_scan_topcoder_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_topcoder("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — HackerOne
# ---------------------------------------------------------------------------

class TestScanHackerOne:
    async def test_scan_hackerone_success(self, client):
        fake_data = {
            "data": [
                {
                    "id": "h1-1",
                    "attributes": {
                        "name": "Acme Corp",
                        "policy": "Report vulnerabilities in our platform",
                        "handle": "acme",
                        "meta": {
                            "bounty_range": {"min": 100, "max": 10000}
                        },
                    },
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_hackerone("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "hackerone"
        assert results[0]["budget_min"] == 100.0
        assert results[0]["budget_max"] == 10000.0
        assert "Bug Bounty:" in results[0]["title"]

    async def test_scan_hackerone_query_filter(self, client):
        fake_data = {
            "data": [
                {"id": "h1-2", "attributes": {"name": "Alpha Corp", "policy": "", "handle": "alpha", "meta": {}}},
                {"id": "h1-3", "attributes": {"name": "Beta Inc", "policy": "", "handle": "beta", "meta": {}}},
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_hackerone("beta", "", 10)
        assert len(results) == 1

    async def test_scan_hackerone_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_hackerone("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Bugcrowd
# ---------------------------------------------------------------------------

class TestScanBugcrowd:
    async def test_scan_bugcrowd_success(self, client):
        fake_data = {
            "programs": [
                {
                    "id": "bc-1",
                    "name": "MegaCorp Bug Bounty",
                    "description": "Find bugs in MegaCorp",
                    "max_payout": 25000,
                    "code": "megacorp",
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_bugcrowd("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "bugcrowd"
        assert results[0]["budget_max"] == 25000.0
        assert "Bug Bounty:" in results[0]["title"]

    async def test_scan_bugcrowd_list_response(self, client):
        fake_data = [
            {
                "id": "bc-2",
                "name": "SmallCo",
                "tagline": "Security program",
                "max_reward": 5000,
                "code": "smallco",
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_bugcrowd("", "", 10)
        assert len(results) == 1
        assert results[0]["budget_max"] == 5000.0

    async def test_scan_bugcrowd_query_filter(self, client):
        fake_data = {
            "programs": [
                {"id": "bc-3", "name": "Alpha Program", "description": "", "max_payout": 1000, "code": "alpha"},
                {"id": "bc-4", "name": "Beta Program", "description": "", "max_payout": 2000, "code": "beta"},
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_bugcrowd("beta", "", 10)
        assert len(results) == 1

    async def test_scan_bugcrowd_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_bugcrowd("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Kaggle
# ---------------------------------------------------------------------------

class TestScanKaggle:
    async def test_scan_kaggle_success(self, client):
        fake_data = [
            {
                "id": "kg-1",
                "title": "Titanic Survival Prediction",
                "description": "Predict survival on Titanic",
                "reward": "$10,000",
                "ref": "titanic-survival",
                "tags": ["classification", "beginner"],
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_kaggle("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "kaggle"
        assert results[0]["budget_max"] == 10000.0
        assert "classification" in results[0]["skills"]

    async def test_scan_kaggle_no_reward(self, client):
        fake_data = [
            {
                "id": "kg-2",
                "title": "Knowledge competition",
                "description": "Learn ML",
                "reward": "",
                "ref": "knowledge",
                "tags": [],
            }
        ]
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_kaggle("", "", 10)
        assert len(results) == 1
        assert results[0]["budget_max"] == 0

    async def test_scan_kaggle_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_kaggle("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — IssueHunt
# ---------------------------------------------------------------------------

class TestScanIssueHunt:
    async def test_scan_issuehunt_success(self, client):
        fake_data = {
            "issues": [
                {
                    "id": "ih-1",
                    "title": "Fix login bug",
                    "body": "Login fails on mobile",
                    "total_amount": 250,
                    "html_url": "https://issuehunt.io/r/org/repo/issues/1",
                    "labels": ["bug", "react-native"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_issuehunt("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "issuehunt"
        assert results[0]["budget_max"] == 250.0
        assert "bug" in results[0]["skills"]

    async def test_scan_issuehunt_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_issuehunt("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Scanner tests — Algora
# ---------------------------------------------------------------------------

class TestScanAlgora:
    async def test_scan_algora_success(self, client):
        fake_data = {
            "bounties": [
                {
                    "id": "al-1",
                    "title": "Implement OAuth",
                    "description": "Add OAuth2 support",
                    "reward_amount": 500,
                    "url": "https://algora.io/bounties/al-1",
                    "labels": ["auth", "go"],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_algora("", "", 10)
        assert len(results) == 1
        assert results[0]["platform"] == "algora"
        assert results[0]["budget_max"] == 500.0
        assert "auth" in results[0]["skills"]

    async def test_scan_algora_error(self, client):
        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            results = await prospector._scan_algora("", "", 10)
        assert results == []


# ---------------------------------------------------------------------------
# Endpoint tests — POST /prospects/{id}/evaluate
# ---------------------------------------------------------------------------

class TestEvaluateEndpoint:
    async def test_evaluate_success_approved(self, client):
        await prospector._save_prospect({
            "id": "ev1", "platform": "github_bounties", "platform_job_id": "ev-j1",
            "title": "Evaluate Me", "description": "Some task", "budget_min": 100,
            "budget_max": 500, "status": "discovered", "skills": "python,rust",
        })

        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "evaluation_id": "eval-100",
            "viable": True,
            "quoted_price_usd": 400,
            "estimated_cost_usd": 120,
        })
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/prospects/ev1/evaluate")

        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["status"] == "approved"

        prospect = (await client.get("/prospects/ev1")).json()
        assert prospect["status"] == "approved"
        assert prospect["quoted_price"] == 400

    async def test_evaluate_success_rejected(self, client):
        await prospector._save_prospect({
            "id": "ev2", "platform": "upwork", "platform_job_id": "ev-j2",
            "title": "Low Value", "description": "Not viable", "budget_min": 0,
            "budget_max": 10, "status": "discovered", "skills": "",
        })

        mock_resp = MagicMock()
        mock_resp.json = MagicMock(return_value={
            "evaluation_id": "eval-101",
            "viable": False,
            "quoted_price_usd": 0,
            "estimated_cost_usd": 0,
        })
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/prospects/ev2/evaluate")

        data = resp.json()
        assert data["status"] == "rejected"

    async def test_evaluate_nonexistent_404(self, client):
        resp = await client.post("/prospects/nonexistent/evaluate")
        assert resp.status_code == 404

    async def test_evaluate_network_error_503(self, client):
        await prospector._save_prospect({
            "id": "ev3", "platform": "upwork", "platform_job_id": "ev-j3",
            "title": "Network Fail", "description": "", "budget_min": 0,
            "budget_max": 100, "status": "discovered", "skills": "",
        })

        mock_http = _mock_http_error()
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/prospects/ev3/evaluate")

        assert resp.status_code == 503

        # status should be reverted back to discovered
        prospect = (await client.get("/prospects/ev3")).json()
        assert prospect["status"] == "discovered"


# ---------------------------------------------------------------------------
# Test _make_prospect helper
# ---------------------------------------------------------------------------

class TestMakeProspect:
    def test_make_prospect_fields(self):
        p = prospector._make_prospect(
            platform="test",
            job_id="j-1",
            title="Test Job",
            description="A test job",
            budget_min=100,
            budget_max=500,
            url="https://example.com",
            skills="python,go",
        )
        assert p["platform"] == "test"
        assert p["platform_job_id"] == "j-1"
        assert p["title"] == "Test Job"
        assert p["description"] == "A test job"
        assert p["budget_min"] == 100
        assert p["budget_max"] == 500
        assert p["url"] == "https://example.com"
        assert p["skills"] == "python,go"
        assert p["status"] == "discovered"
        assert "id" in p

    def test_make_prospect_defaults(self):
        p = prospector._make_prospect(
            platform="x",
            job_id="j",
            title="T",
            description="D",
        )
        assert p["budget_min"] == 0
        assert p["budget_max"] == 0
        assert p["url"] == ""
        assert p["skills"] == ""


# ---------------------------------------------------------------------------
# Test scan via endpoint for each platform (integration-style)
# ---------------------------------------------------------------------------

class TestScanEndpointAllPlatforms:
    """Test that scanning via the /scan endpoint works for every registered platform."""

    async def test_scan_github_via_endpoint(self, client):
        fake = {"items": [{"id": 1, "title": "T", "body": "$100", "html_url": "", "labels": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "github_bounties"})
        assert resp.json()["ok"] == 1

    async def test_scan_gitcoin_via_endpoint(self, client):
        fake = [{"pk": 1, "title": "T", "issue_description_text": "", "value_in_usdt": 100, "url": "", "keywords": []}]
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "gitcoin"})
        assert resp.json()["ok"] == 1

    async def test_scan_dework_via_endpoint(self, client):
        fake = {"data": {"tasks": [{"id": "1", "title": "T", "description": "", "reward": {}, "permalink": "", "tags": []}]}}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "dework"})
        assert resp.json()["ok"] == 1

    async def test_scan_layer3_via_endpoint(self, client):
        fake = {"quests": [{"id": "1", "title": "T", "description": "", "reward": {}, "url": "", "tags": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "layer3"})
        assert resp.json()["ok"] == 1

    async def test_scan_replit_via_endpoint(self, client):
        fake = {"items": [{"id": "1", "title": "T", "description": "", "amount": 50, "url": "", "tags": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "replit_bounties"})
        assert resp.json()["ok"] == 1

    async def test_scan_zealy_via_endpoint(self, client):
        fake = {"communities": [{"id": "1", "name": "T", "description": "", "subdomain": "t"}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "zealy"})
        assert resp.json()["ok"] == 1

    async def test_scan_galxe_via_endpoint(self, client):
        fake = {"data": {"campaigns": {"list": [{"id": "1", "name": "T", "description": "", "loyaltyPoints": 0}]}}}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "galxe"})
        assert resp.json()["ok"] == 1

    async def test_scan_questbook_via_endpoint(self, client):
        fake = {"grants": [{"id": "1", "title": "T", "description": "", "reward": 100, "url": ""}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "questbook"})
        assert resp.json()["ok"] == 1

    async def test_scan_onlydust_via_endpoint(self, client):
        fake = {"projects": [{"id": "1", "name": "T", "shortDescription": "", "slug": "t", "technologies": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "onlydust"})
        assert resp.json()["ok"] == 1

    async def test_scan_freelancer_via_endpoint(self, client):
        fake = {"result": {"projects": [{"id": 1, "title": "T", "preview_description": "", "budget": {"minimum": 10, "maximum": 50}, "seo_url": "t", "jobs": []}]}}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "freelancer"})
        assert resp.json()["ok"] == 1

    async def test_scan_fiverr_via_endpoint(self, client):
        fake = {"buyer_requests": [{"id": "1", "title": "T", "description": "", "budget": 100, "url": ""}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "fiverr"})
        assert resp.json()["ok"] == 1

    async def test_scan_topcoder_via_endpoint(self, client):
        fake = [{"id": "1", "name": "T", "description": "", "prizeSets": [], "tags": []}]
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "topcoder"})
        assert resp.json()["ok"] == 1

    async def test_scan_hackerone_via_endpoint(self, client):
        fake = {"data": [{"id": "1", "attributes": {"name": "T", "policy": "", "handle": "t", "meta": {}}}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "hackerone"})
        assert resp.json()["ok"] == 1

    async def test_scan_bugcrowd_via_endpoint(self, client):
        fake = {"programs": [{"id": "1", "name": "T", "description": "", "max_payout": 100, "code": "t"}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "bugcrowd"})
        assert resp.json()["ok"] == 1

    async def test_scan_kaggle_via_endpoint(self, client):
        fake = [{"id": "1", "title": "T", "description": "", "reward": "$100", "ref": "t", "tags": []}]
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "kaggle"})
        assert resp.json()["ok"] == 1

    async def test_scan_issuehunt_via_endpoint(self, client):
        fake = {"issues": [{"id": "1", "title": "T", "body": "", "total_amount": 50, "html_url": "", "labels": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "issuehunt"})
        assert resp.json()["ok"] == 1

    async def test_scan_algora_via_endpoint(self, client):
        fake = {"bounties": [{"id": "1", "title": "T", "description": "", "reward_amount": 100, "url": "", "labels": []}]}
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "algora"})
        assert resp.json()["ok"] == 1

    async def test_scan_superteam_via_endpoint(self, client):
        fake = [{"id": "1", "title": "T", "description": "", "rewardAmount": 100, "slug": "t", "skills": []}]
        mock_http = _mock_http_get(response_json=fake)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http):
            resp = await client.post("/scan", json={"platform": "superteam_earn"})
        assert resp.json()["ok"] == 1


# ---------------------------------------------------------------------------
# Test update_prospect for nonexistent prospect
# ---------------------------------------------------------------------------

class TestUpdateProspectEdgeCases:
    async def test_update_nonexistent_prospect(self, client):
        resp = await client.patch("/prospects/no-such-id", json={"status": "approved"})
        assert resp.status_code == 404

    async def test_update_multiple_timestamp_statuses(self, client):
        """Test that hired, delivered, paid also set timestamps."""
        await prospector._save_prospect({
            "id": "ts1", "platform": "upwork", "platform_job_id": "ts-j1",
            "title": "Timestamp Test", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "approved",
        })
        await client.patch("/prospects/ts1", json={"status": "hired"})
        prospect = (await client.get("/prospects/ts1")).json()
        assert prospect["hired_at"] is not None

        await client.patch("/prospects/ts1", json={"status": "delivered"})
        prospect = (await client.get("/prospects/ts1")).json()
        assert prospect["delivered_at"] is not None

        await client.patch("/prospects/ts1", json={"status": "paid"})
        prospect = (await client.get("/prospects/ts1")).json()
        assert prospect["paid_at"] is not None


# ---------------------------------------------------------------------------
# Test RSS parsing edge cases
# ---------------------------------------------------------------------------

class TestParseRss:
    def test_parse_valid_rss(self):
        xml = """<?xml version="1.0"?><rss><channel>
        <item><title>Job A</title><link>http://a.com</link><guid>a1</guid></item>
        </channel></rss>"""
        items = prospector._parse_rss(xml)
        assert len(items) == 1
        assert items[0]["title"] == "Job A"

    def test_parse_invalid_rss(self):
        items = prospector._parse_rss("not xml at all <<<>>>")
        assert items == []

    def test_parse_empty_rss(self):
        xml = """<?xml version="1.0"?><rss><channel></channel></rss>"""
        items = prospector._parse_rss(xml)
        assert items == []


# ---------------------------------------------------------------------------
# Test _svc_headers
# ---------------------------------------------------------------------------

class TestSvcHeaders:
    def test_headers_without_token(self):
        original = prospector.SERVICE_TOKEN
        prospector.SERVICE_TOKEN = ""
        try:
            h = prospector._svc_headers()
            assert "Content-Type" in h
            assert "X-Service-Token" not in h
        finally:
            prospector.SERVICE_TOKEN = original

    def test_headers_with_token(self):
        original = prospector.SERVICE_TOKEN
        prospector.SERVICE_TOKEN = "test-token-123"
        try:
            h = prospector._svc_headers()
            assert h["X-Service-Token"] == "test-token-123"
        finally:
            prospector.SERVICE_TOKEN = original


# ---------------------------------------------------------------------------
# Test scan with notifications triggered
# ---------------------------------------------------------------------------

class TestScanWithNotifications:
    async def test_scan_triggers_notification_for_high_value(self, client):
        fake_data = {
            "items": [
                {
                    "id": 300,
                    "title": "Expensive job",
                    "body": "Pay: $5,000 for this work",
                    "html_url": "https://github.com/org/repo/issues/300",
                    "labels": [{"name": "bounty"}],
                }
            ]
        }
        mock_http = _mock_http_get(response_json=fake_data)
        with patch.object(prospector.httpx, "AsyncClient", return_value=mock_http), \
             patch.object(prospector, "_send_prospect_alert") as mock_alert:
            resp = await client.post("/scan", json={"platform": "github_bounties"})
        assert resp.json()["ok"] == 1
        mock_alert.assert_called_once()
        # The high-value prospect should have been passed
        alerted = mock_alert.call_args[0][0]
        assert len(alerted) == 1
        assert alerted[0]["budget_max"] >= 100


# ---------------------------------------------------------------------------
# Test list_prospects filter by platform
# ---------------------------------------------------------------------------

class TestListProspectsByPlatform:
    async def test_filter_by_platform(self, client):
        await prospector._save_prospect({
            "id": "fp1", "platform": "github_bounties", "platform_job_id": "fp-j1",
            "title": "GitHub Job", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered",
        })
        await prospector._save_prospect({
            "id": "fp2", "platform": "freelancer", "platform_job_id": "fp-j2",
            "title": "Freelancer Job", "description": "", "budget_min": 0,
            "budget_max": 0, "status": "discovered",
        })
        resp = await client.get("/prospects", params={"platform": "github_bounties"})
        data = resp.json()
        assert len(data) == 1
        assert data[0]["platform"] == "github_bounties"
