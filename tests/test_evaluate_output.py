"""Tests for the /evaluate-output endpoint in evaluator_service."""

import os
import tempfile

from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("EVALUATOR_DB_PATH", os.path.join(_tmpdir, "test_eval_output.db"))

evaluator = load_service("eval_main_output", "evaluator_service")


@pytest.fixture
async def client():
    async with evaluator.lifespan(evaluator.app):
        transport = ASGITransport(app=evaluator.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


class TestEvaluateOutput:
    async def test_long_relevant_structured_output(self, client):
        output = (
            "# Login Page Fix\n\n"
            "I fixed the login button issue on the login page. "
            "The problem was a missing event handler on the button element. "
            "Here are the changes:\n\n"
            "- Updated `LoginPage.tsx` to attach the onClick handler\n"
            "- Added proper form submission logic\n"
            "- Tested across Chrome, Firefox, and Safari\n\n"
            "```tsx\nconst handleLogin = () => { /* ... */ };\n```\n\n"
            "Everything is working correctly now. The login page renders properly "
            "and the button responds to clicks on both desktop and mobile."
        )
        resp = await client.post("/evaluate-output", json={
            "task_id": "t1",
            "title": "Fix login page button",
            "output_preview": output,
        })
        data = resp.json()
        assert data["quality_score"] >= 0.6
        assert data["passed"] is True

    async def test_short_output_flagged(self, client):
        resp = await client.post("/evaluate-output", json={
            "task_id": "t2",
            "title": "Build a REST API",
            "output_preview": "Done.",
        })
        data = resp.json()
        assert "output_too_short" in data["issues"]
        assert data["quality_score"] < 0.6

    async def test_error_words_flagged(self, client):
        resp = await client.post("/evaluate-output", json={
            "task_id": "t3",
            "title": "Deploy the application",
            "output_preview": (
                "I attempted to deploy the application but encountered an error. "
                "The deployment failed due to missing environment variables. "
                "I was unable to resolve the configuration issues within the time."
            ),
        })
        data = resp.json()
        assert "possible_failure" in data["issues"]
        # Score should be reduced
        assert data["quality_score"] < 0.8

    async def test_unrelated_output_low_relevance(self, client):
        resp = await client.post("/evaluate-output", json={
            "task_id": "t4",
            "title": "Implement payment gateway",
            "output_preview": (
                "The weather today is sunny with mild temperatures. "
                "Birds are singing outside the window and the garden looks lovely. "
                "I had a nice cup of coffee this morning while reading the newspaper."
            ),
        })
        data = resp.json()
        assert "low_relevance" in data["issues"]

    async def test_markdown_formatting_boosts_score(self, client):
        base_text = (
            "I completed the database migration task successfully. "
            "The database schema has been updated with new columns and indexes. "
            "All existing data was preserved during the migration process. "
            "Performance benchmarks show improved query response times overall."
        )
        # Without markdown
        resp_plain = await client.post("/evaluate-output", json={
            "task_id": "t5a",
            "title": "Database migration task",
            "output_preview": base_text,
        })
        # With markdown
        resp_md = await client.post("/evaluate-output", json={
            "task_id": "t5b",
            "title": "Database migration task",
            "output_preview": f"# Results\n\n{base_text}\n\n- Step 1 done\n- Step 2 done",
        })
        assert resp_md.json()["quality_score"] > resp_plain.json()["quality_score"]

    async def test_empty_output(self, client):
        resp = await client.post("/evaluate-output", json={
            "task_id": "t6",
            "title": "Some task",
            "output_preview": "",
        })
        data = resp.json()
        assert "output_too_short" in data["issues"]
        assert data["passed"] is False
