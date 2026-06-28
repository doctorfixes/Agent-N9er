import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

# Point DB at a temp file before importing the module
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test_marketplace.db")

from conftest import load_service

marketplace = load_service("marketplace_main", "bidding_marketplace")


@pytest.fixture
async def client():
    async with marketplace.lifespan(marketplace.app):
        transport = ASGITransport(app=marketplace.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_feed_initially_empty(client):
    resp = await client.get("/feed")
    assert resp.json() == []


async def test_publish_adds_task(client):
    task = {"id": "t1", "objective": "test", "priority_score": 0.5}
    resp = await client.post("/publish", json=task)
    assert resp.json()["ok"] == 1


async def test_feed_returns_published_tasks(client):
    await client.post("/publish", json={"id": "t10", "objective": "first"})
    await client.post("/publish", json={"id": "t11", "objective": "second"})
    feed = (await client.get("/feed")).json()
    ids = [t["id"] for t in feed]
    assert "t10" in ids
    assert "t11" in ids


async def test_publish_sets_status_open(client):
    await client.post("/publish", json={"id": "t20", "objective": "x"})
    feed = (await client.get("/feed")).json()
    task = next(t for t in feed if t["id"] == "t20")
    assert task["status"] == "open"


async def test_submit_bid(client):
    await client.post("/publish", json={"id": "t30", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "t30", "agent_id": "a1", "confidence": 0.8})
    assert resp.json()["ok"] == 1


async def test_get_bids(client):
    await client.post("/publish", json={"id": "t40", "objective": "x"})
    await client.post("/bid", json={"task_id": "t40", "agent_id": "a1", "confidence": 0.8})
    await client.post("/bid", json={"task_id": "t40", "agent_id": "a2", "confidence": 0.9})
    bids = (await client.get("/bids/t40")).json()
    assert len(bids) == 2


async def test_award_task(client):
    await client.post("/publish", json={"id": "t50", "objective": "x"})
    await client.post("/bid", json={"task_id": "t50", "agent_id": "a1", "confidence": 0.6, "require_approval": False})
    await client.post("/bid", json={"task_id": "t50", "agent_id": "a2", "confidence": 0.9, "require_approval": False})
    result = (await client.post("/award/t50")).json()
    assert result["winner"]["agent_id"] == "a2"


async def test_complete_task(client):
    await client.post("/publish", json={"id": "t60", "objective": "x"})
    await client.post("/complete/t60", json={"success": True})
    feed = (await client.get("/feed")).json()
    task = next(t for t in feed if t["id"] == "t60")
    assert task["status"] == "completed"


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


# --- Pydantic validation tests ---

async def test_publish_missing_id_returns_422(client):
    resp = await client.post("/publish", json={"objective": "no id"})
    assert resp.status_code == 422


async def test_bid_invalid_confidence_returns_422(client):
    await client.post("/publish", json={"id": "tv1", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "tv1", "agent_id": "a1", "confidence": 1.5})
    assert resp.status_code == 422


async def test_bid_negative_price_returns_422(client):
    await client.post("/publish", json={"id": "tv2", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "tv2", "agent_id": "a1", "price": -1.0})
    assert resp.status_code == 422


# --- Pagination tests ---

async def test_feed_pagination(client):
    for i in range(5):
        await client.post("/publish", json={"id": f"pg{i}", "objective": f"task {i}"})
    feed = (await client.get("/feed", params={"limit": 2})).json()
    assert len(feed) == 2
    feed2 = (await client.get("/feed", params={"limit": 2, "offset": 2})).json()
    assert len(feed2) == 2
    assert feed[0]["id"] != feed2[0]["id"]


# --- Unique bid constraint ---

async def test_duplicate_bid_replaces(client):
    await client.post("/publish", json={"id": "ub1", "objective": "x"})
    await client.post("/bid", json={"task_id": "ub1", "agent_id": "a1", "confidence": 0.5})
    await client.post("/bid", json={"task_id": "ub1", "agent_id": "a1", "confidence": 0.9})
    bids = (await client.get("/bids/ub1")).json()
    agent_bids = [b for b in bids if b["agent_id"] == "a1"]
    assert len(agent_bids) == 1
    assert agent_bids[0]["confidence"] == 0.9


# --- Human-in-the-loop approval tests ---

async def test_bid_defaults_to_pending_approval(client):
    await client.post("/publish", json={"id": "ap1", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "ap1", "agent_id": "a1", "confidence": 0.7})
    data = resp.json()
    assert data["status"] == "pending_approval"


async def test_bid_skip_approval(client):
    await client.post("/publish", json={"id": "ap2", "objective": "x"})
    resp = await client.post("/bid", json={"task_id": "ap2", "agent_id": "a1", "confidence": 0.7, "require_approval": False})
    data = resp.json()
    assert data["status"] == "submitted"


async def test_list_pending_bids(client):
    await client.post("/publish", json={"id": "ap3", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap3", "agent_id": "a1", "confidence": 0.7})
    await client.post("/bid", json={"task_id": "ap3", "agent_id": "a2", "confidence": 0.8})
    pending = (await client.get("/bids/pending")).json()
    pending_for_task = [b for b in pending if b["task_id"] == "ap3"]
    assert len(pending_for_task) == 2


async def test_approve_bid(client):
    await client.post("/publish", json={"id": "ap4", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap4", "agent_id": "a1", "confidence": 0.7})
    pending = (await client.get("/bids/pending")).json()
    bid = next(b for b in pending if b["task_id"] == "ap4")

    resp = await client.post(f"/bids/{bid['id']}/approve")
    assert resp.json()["status"] == "submitted"

    result = (await client.post("/award/ap4")).json()
    assert result["winner"]["agent_id"] == "a1"


async def test_reject_bid(client):
    await client.post("/publish", json={"id": "ap5", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap5", "agent_id": "a1", "confidence": 0.7})
    pending = (await client.get("/bids/pending")).json()
    bid = next(b for b in pending if b["task_id"] == "ap5")

    resp = await client.post(f"/bids/{bid['id']}/reject")
    assert resp.json()["status"] == "rejected"

    award_resp = await client.post("/award/ap5")
    assert award_resp.status_code == 404


async def test_approve_all_bids_for_task(client):
    await client.post("/publish", json={"id": "ap6", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap6", "agent_id": "a1", "confidence": 0.6})
    await client.post("/bid", json={"task_id": "ap6", "agent_id": "a2", "confidence": 0.9})

    resp = await client.post("/bids/approve-all/ap6")
    data = resp.json()
    assert data["approved_count"] == 2

    result = (await client.post("/award/ap6")).json()
    assert result["winner"]["agent_id"] == "a2"


async def test_cannot_approve_already_submitted_bid(client):
    await client.post("/publish", json={"id": "ap7", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap7", "agent_id": "a1", "confidence": 0.7, "require_approval": False})
    bids = (await client.get("/bids/ap7")).json()
    bid = bids[0]

    resp = await client.post(f"/bids/{bid['id']}/approve")
    assert resp.status_code == 409


async def test_approve_nonexistent_bid_returns_404(client):
    resp = await client.post("/bids/99999/approve")
    assert resp.status_code == 404


async def test_reject_nonexistent_bid_returns_404(client):
    resp = await client.post("/bids/99999/reject")
    assert resp.status_code == 404


async def test_cannot_reject_already_submitted_bid(client):
    await client.post("/publish", json={"id": "ap8", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap8", "agent_id": "a1", "confidence": 0.7, "require_approval": False})
    bids = (await client.get("/bids/ap8")).json()
    bid = bids[0]

    resp = await client.post(f"/bids/{bid['id']}/reject")
    assert resp.status_code == 409


async def test_get_bids_nonexistent_task_returns_404(client):
    resp = await client.get("/bids/nonexistent-task-xyz")
    assert resp.status_code == 404


async def test_feed_filter_by_status(client):
    await client.post("/publish", json={"id": "fs1", "objective": "x"})
    await client.post("/publish", json={"id": "fs2", "objective": "y"})
    await client.post("/complete/fs1", json={"success": True})
    open_feed = (await client.get("/feed", params={"status": "open"})).json()
    completed_feed = (await client.get("/feed", params={"status": "completed"})).json()
    assert all(t["status"] == "open" for t in open_feed)
    assert all(t["status"] == "completed" for t in completed_feed)


async def test_award_no_submitted_bids_returns_404(client):
    await client.post("/publish", json={"id": "ap9", "objective": "x"})
    await client.post("/bid", json={"task_id": "ap9", "agent_id": "a1", "confidence": 0.7})
    resp = await client.post("/award/ap9")
    assert resp.status_code == 404


async def test_bid_status_included_in_response(client):
    await client.post("/publish", json={"id": "bs1", "objective": "x"})
    await client.post("/bid", json={"task_id": "bs1", "agent_id": "a1", "confidence": 0.7})
    bids = (await client.get("/bids/bs1")).json()
    assert bids[0]["status"] == "pending_approval"
    assert "reviewed_at" in bids[0]


async def test_approve_sets_reviewed_at(client):
    await client.post("/publish", json={"id": "rv1", "objective": "x"})
    await client.post("/bid", json={"task_id": "rv1", "agent_id": "a1", "confidence": 0.7})
    pending = (await client.get("/bids/pending")).json()
    bid = next(b for b in pending if b["task_id"] == "rv1")

    await client.post(f"/bids/{bid['id']}/approve")
    bids = (await client.get("/bids/rv1")).json()
    assert bids[0]["reviewed_at"] is not None


async def test_reject_sets_reviewed_at(client):
    await client.post("/publish", json={"id": "rv2", "objective": "x"})
    await client.post("/bid", json={"task_id": "rv2", "agent_id": "a1", "confidence": 0.7})
    pending = (await client.get("/bids/pending")).json()
    bid = next(b for b in pending if b["task_id"] == "rv2")

    await client.post(f"/bids/{bid['id']}/reject")
    bids = (await client.get("/bids/rv2")).json()
    assert bids[0]["status"] == "rejected"
    assert bids[0]["reviewed_at"] is not None


async def test_approve_all_with_no_pending_bids(client):
    await client.post("/publish", json={"id": "aa1", "objective": "x"})
    resp = await client.post("/bids/approve-all/aa1")
    data = resp.json()
    assert data["approved_count"] == 0


async def test_pending_bids_pagination(client):
    await client.post("/publish", json={"id": "pp1", "objective": "x"})
    for i in range(5):
        await client.post("/bid", json={"task_id": "pp1", "agent_id": f"agent-pg-{i}", "confidence": 0.5})
    page1 = (await client.get("/bids/pending", params={"limit": 2})).json()
    page2 = (await client.get("/bids/pending", params={"limit": 2, "offset": 2})).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]
