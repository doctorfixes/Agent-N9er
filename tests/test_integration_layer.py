from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from integration_layer.submit_task import forward_task
from integration_layer.dashboard_summary import summary


async def test_forward_task_posts_to_orchestrator():
    mock_client = AsyncMock()
    mock_client.post = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("integration_layer.submit_task.httpx.AsyncClient", return_value=mock_client):
        await forward_task({"objective": "test"})

    mock_client.post.assert_called_once_with(
        "http://orchestrator:9000/pipeline",
        json={"objective": "test"},
    )


async def test_summary_fetches_tasks_and_agents():
    mock_tasks_resp = MagicMock()
    mock_tasks_resp.json.return_value = [{"id": "t1"}]
    mock_agents_resp = MagicMock()
    mock_agents_resp.json.return_value = {"a1": {"success": 5, "fail": 1}}

    async def mock_get(url):
        if "feed" in url:
            return mock_tasks_resp
        if "ledger" in url:
            return mock_agents_resp

    mock_client = AsyncMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("integration_layer.dashboard_summary.httpx.AsyncClient", return_value=mock_client):
        result = await summary()

    assert result["tasks"] == [{"id": "t1"}]
    assert result["agents"] == {"a1": {"success": 5, "fail": 1}}
