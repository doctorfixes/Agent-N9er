import os
import tempfile
from unittest.mock import patch, AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
import pytest

_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test_execution.db")

from conftest import load_service

execution = load_service("execution_main", "agent_execution")


@pytest.fixture
async def client():
    async with execution.lifespan(execution.app):
        transport = ASGITransport(app=execution.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _mock_reputation():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    return patch.object(execution, "retry_request", AsyncMock(return_value=mock_resp))


async def test_execute_returns_result(client):
    with _mock_reputation():
        resp = await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": 0.9})
    data = resp.json()
    assert data["ok"] == 1
    assert "success" in data
    assert "duration" in data


async def test_execute_missing_fields_returns_422(client):
    resp = await client.post("/execute", json={"task_id": "t1"})
    assert resp.status_code == 422


async def test_history_endpoint(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "h1", "agent_id": "a1", "confidence": 0.9})
    history = (await client.get("/history")).json()
    assert any(e["task_id"] == "h1" for e in history)


async def test_history_filter_by_agent(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "fa1", "agent_id": "agent_x", "confidence": 0.9})
        await client.post("/execute", json={"task_id": "fa2", "agent_id": "agent_y", "confidence": 0.8})
    history = (await client.get("/history", params={"agent_id": "agent_x"})).json()
    assert all(e["agent_id"] == "agent_x" for e in history)


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.json()["ok"] == 1


# --- Pydantic validation tests ---

async def test_execute_invalid_confidence_returns_422(client):
    resp = await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": 2.0})
    assert resp.status_code == 422


async def test_execute_negative_confidence_returns_422(client):
    resp = await client.post("/execute", json={"task_id": "t1", "agent_id": "a1", "confidence": -0.5})
    assert resp.status_code == 422


# --- Pagination tests ---

async def test_history_pagination(client):
    with _mock_reputation():
        for i in range(5):
            await client.post("/execute", json={"task_id": f"pg{i}", "agent_id": "a1", "confidence": 0.9})
    history = (await client.get("/history", params={"limit": 2})).json()
    assert len(history) == 2
    history2 = (await client.get("/history", params={"limit": 2, "offset": 2})).json()
    assert len(history2) == 2


# --- Simulation vs live mode tests ---

async def test_simulation_mode_when_no_api_key(client):
    with _mock_reputation():
        resp = await client.post("/execute", json={"task_id": "sim1", "agent_id": "a1", "confidence": 0.9})
    data = resp.json()
    assert data["mode"] == "simulation"


async def test_health_shows_mode(client):
    resp = await client.get("/health")
    data = resp.json()
    assert data["mode"] in ("live", "simulation")


async def test_execution_with_objective_but_no_key(client):
    with _mock_reputation():
        resp = await client.post("/execute", json={
            "task_id": "obj1", "agent_id": "a1", "confidence": 0.9,
            "objective": "Write a hello world in Python",
        })
    data = resp.json()
    assert data["mode"] == "simulation"


async def test_execution_live_mode_with_direct_provider(client):
    llm_result = MagicMock(
        content="done",
        model="claude-3-5-haiku-latest",
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.001,
        latency_ms=50.0,
        finish_reason="stop",
    )
    with _mock_reputation(), \
            patch.object(execution, "has_available_provider", return_value=True), \
            patch.object(execution, "complete", AsyncMock(return_value=llm_result)):
        resp = await client.post("/execute", json={
            "task_id": "live1", "agent_id": "a1", "objective": "Write a hello world in Python",
        })
    data = resp.json()
    assert data["ok"] == 1
    assert data["mode"] == "live"
    assert data["model"] == "claude-3-5-haiku-latest"
    assert data["output_preview"] == "done"


async def test_get_execution_output(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "out1", "agent_id": "a1", "confidence": 0.9})
    resp = await client.get("/executions/out1/output")
    data = resp.json()
    assert data["task_id"] == "out1"
    assert "success" in data


async def test_get_missing_execution_output(client):
    resp = await client.get("/executions/nonexistent/output")
    assert resp.status_code == 404


# --- Proposal generation tests ---

async def test_proposal_simulation_mode(client):
    resp = await client.post("/proposal", json={
        "title": "Build a React Dashboard",
        "description": "Need a React developer",
        "platform": "upwork",
    })
    data = resp.json()
    assert data["ok"] == 1
    assert data["mode"] == "simulation"
    assert len(data["proposal"]) > 0


async def test_proposal_with_all_fields(client):
    resp = await client.post("/proposal", json={
        "prospect_id": "p123",
        "title": "Fix Python Script",
        "description": "Small fix needed in data pipeline",
        "platform": "github_bounties",
        "budget_max": 500,
        "skills": "python,pandas",
        "tone": "technical",
    })
    data = resp.json()
    assert data["ok"] == 1
    assert data["prospect_id"] == "p123"


async def test_proposal_missing_title_returns_422(client):
    resp = await client.post("/proposal", json={"description": "no title"})
    assert resp.status_code == 422


# --- Deliverable formatting tests ---

async def test_format_deliverable_no_output(client):
    with _mock_reputation():
        await client.post("/execute", json={
            "task_id": "fmt1", "agent_id": "a1", "confidence": 0.9,
        })
    resp = await client.post("/format-deliverable", json={
        "task_id": "fmt1", "format": "markdown",
    })
    data = resp.json()
    assert data["ok"] == 0


async def test_format_deliverable_with_output(client):
    import aiosqlite
    async with aiosqlite.connect(execution.DB_PATH) as db:
        await db.execute(
            "INSERT INTO executions (task_id, agent_id, success, duration, executed_at, mode, model, cost_usd, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fmt_live", "a1", True, 2.5, "2025-01-01T00:00:00", "live", "test-model", 0.01, "Here is the deliverable content."),
        )
        await db.commit()
    resp = await client.post("/format-deliverable", json={
        "task_id": "fmt_live", "format": "markdown",
    })
    data = resp.json()
    assert data["ok"] == 1
    assert data["task_id"] == "fmt_live"
    assert "word_count" in data
    assert "Deliverable" in data["content"]


async def test_format_deliverable_html(client):
    import aiosqlite
    async with aiosqlite.connect(execution.DB_PATH) as db:
        await db.execute(
            "INSERT INTO executions (task_id, agent_id, success, duration, executed_at, mode, model, cost_usd, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fmt_html", "a1", True, 1.0, "2025-01-01T00:00:00", "live", "test-model", 0.005, "HTML output test"),
        )
        await db.commit()
    resp = await client.post("/format-deliverable", json={
        "task_id": "fmt_html", "format": "html",
    })
    data = resp.json()
    assert data["ok"] == 1
    assert "<div" in data["content"]


async def test_format_nonexistent_returns_404(client):
    resp = await client.post("/format-deliverable", json={
        "task_id": "nonexistent", "format": "markdown",
    })
    assert resp.status_code == 404


# --- Analytics tests ---

async def test_analytics_endpoint(client):
    with _mock_reputation():
        await client.post("/execute", json={"task_id": "an1", "agent_id": "a1", "confidence": 0.9})
        await client.post("/execute", json={"task_id": "an2", "agent_id": "a2", "confidence": 0.8})
    resp = await client.get("/analytics")
    data = resp.json()
    assert data["total_executions"] >= 2
    assert "success_rate" in data
    assert "by_agent" in data
    assert isinstance(data["by_agent"], list)


async def test_analytics_with_days_param(client):
    resp = await client.get("/analytics", params={"days": 7})
    data = resp.json()
    assert data["period_days"] == 7


# --- _clean_proposal tests ---

class TestCleanProposal:
    def test_removes_dear_bracket(self):
        text = "Dear [Client Name],\nHello there."
        assert execution._clean_proposal(text) == "Hello there."

    def test_replaces_client_name_with_you(self):
        text = "I can help [Client Name] with this."
        assert "you" in execution._clean_proposal(text)
        assert "[Client" not in execution._clean_proposal(text)

    def test_replaces_client_with_you(self):
        text = "Dear [Client], I can deliver."
        result = execution._clean_proposal(text)
        assert "[Client]" not in result

    def test_replaces_your_name_with_rj(self):
        text = "Best regards,\n[Your Name]"
        assert "RJ" in execution._clean_proposal(text)
        assert "[Your Name]" not in execution._clean_proposal(text)

    def test_replaces_x_with_days(self):
        text = "I can deliver in [X] days."
        assert "5-7" in execution._clean_proposal(text)

    def test_removes_other_brackets(self):
        text = "Using [specific technology] and [framework]."
        result = execution._clean_proposal(text)
        assert "[" not in result

    def test_strips_whitespace(self):
        text = "  \n  Hello world.  \n  "
        assert execution._clean_proposal(text) == "Hello world."

    def test_empty_string(self):
        assert execution._clean_proposal("") == ""

    def test_no_brackets(self):
        text = "This is a clean proposal with no placeholders."
        assert execution._clean_proposal(text) == text


# --- _estimate_quote_price tests ---

class TestEstimateQuotePrice:
    def test_low_complexity(self):
        req = execution.QuoteRequest(title="Fix typo", description="Small fix")
        pricing = execution._estimate_quote_price(req)
        assert pricing["complexity"] == "low"
        assert pricing["multiplier"] == 7.0
        assert pricing["estimated_output_tokens"] == 2000
        assert pricing["price"] > 0

    def test_medium_complexity(self):
        req = execution.QuoteRequest(
            title="Build REST API",
            description="x" * 600,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["complexity"] == "medium"
        assert pricing["multiplier"] == 8.5

    def test_high_complexity(self):
        req = execution.QuoteRequest(
            title="Full stack app",
            description="x" * 2100,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["complexity"] == "high"
        assert pricing["multiplier"] == 10.0

    def test_high_budget_increases_multiplier(self):
        req = execution.QuoteRequest(
            title="Big project",
            description="Details",
            budget_max=600,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["multiplier"] > 7.0

    def test_medium_budget_increases_multiplier(self):
        req = execution.QuoteRequest(
            title="Medium project",
            description="Details",
            budget_max=300,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["multiplier"] >= 7.0

    def test_price_clamped_to_budget_max(self):
        req = execution.QuoteRequest(
            title="Tiny fix",
            description="x" * 2500,
            budget_max=10,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["price"] <= 10 * 1.1

    def test_price_respects_budget_min(self):
        req = execution.QuoteRequest(
            title="Job",
            description="task",
            budget_min=100,
            budget_max=500,
        )
        pricing = execution._estimate_quote_price(req)
        assert pricing["price"] >= 100 * 0.7

    def test_minimum_quote_applied(self):
        req = execution.QuoteRequest(title="A", description="B")
        pricing = execution._estimate_quote_price(req)
        assert pricing["price"] >= 5.0


# --- /quote endpoint tests ---

async def test_quote_simulation_mode(client):
    resp = await client.post("/quote", json={
        "title": "Build a chatbot",
        "description": "Chatbot for customer support",
        "platform": "freelancer",
        "budget_min": 100,
        "budget_max": 500,
    })
    data = resp.json()
    assert data["ok"] == 1
    assert data["mode"] == "simulation"
    assert data["suggested_price"] > 0
    assert "pricing" in data
    assert "reply" in data


async def test_quote_includes_pricing_metadata(client):
    resp = await client.post("/quote", json={
        "title": "Data pipeline",
        "description": "Build an ETL pipeline for analytics",
        "platform": "upwork",
        "budget_max": 800,
    })
    data = resp.json()
    pricing = data.get("pricing", {})
    assert "complexity" in pricing
    assert "multiplier" in pricing
    assert "estimated_token_cost" in pricing


async def test_quote_with_conversation(client):
    resp = await client.post("/quote", json={
        "title": "API Integration",
        "description": "Connect to third-party API",
        "platform": "freelancer",
        "client_message": "Can you also add error handling?",
        "conversation": [
            {"role": "user", "content": "What's your timeline?"},
            {"role": "assistant", "content": "5-7 business days."},
        ],
    })
    data = resp.json()
    assert data["ok"] == 1
