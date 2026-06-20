from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

orch = load_service("orch_main", "orchestrator")


@pytest.fixture
def client():
    transport = ASGITransport(app=orch.app)
    return AsyncClient(transport=transport, base_url="http://test")


def _make_response(data):
    resp = MagicMock()
    resp.json.return_value = data
    return resp


def _mock_responses():
    normalized = {"id": "n1", "objective": "test task", "inputs": {}, "raw": {}}
    ranked = {"id": "n1", "priority_score": 0.9}

    async def mock_post(url, **kwargs):
        if "normalize" in url:
            return _make_response(normalized)
        elif "rank" in url:
            return _make_response(ranked)
        elif "publish" in url:
            return _make_response({"ok": 1})

    return mock_post, normalized, ranked


async def test_pipeline_calls_all_services(client):
    mock_post, normalized, ranked = _mock_responses()

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        resp = await client.post("/pipeline", json={"objective": "test task"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "task_published"
    assert data["normalized"] == normalized
    assert data["ranked"] == ranked


async def test_pipeline_passes_normalized_to_ranking(client):
    calls = []

    async def tracking_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        if "normalize" in url:
            return _make_response({"id": "n1", "objective": "x", "inputs": {}, "raw": {}})
        elif "rank" in url:
            return _make_response({"id": "n1", "priority_score": 0.1})
        elif "publish" in url:
            return _make_response({"ok": 1})

    mock_client = AsyncMock()
    mock_client.post = tracking_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(orch.httpx, "AsyncClient", return_value=mock_client):
        await client.post("/pipeline", json={"objective": "x"})

    rank_call = [c for c in calls if "rank" in c[0]][0]
    assert rank_call[1]["id"] == "n1"

    publish_call = [c for c in calls if "publish" in c[0]][0]
    assert publish_call[1]["priority_score"] == 0.1
