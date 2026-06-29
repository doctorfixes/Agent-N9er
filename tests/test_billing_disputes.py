"""Tests for billing dispute and profitability endpoints."""

import os
import tempfile

import aiosqlite
from httpx import ASGITransport, AsyncClient
import pytest

from conftest import load_service

_tmpdir = tempfile.mkdtemp()
os.environ.setdefault("BILLING_DB_PATH", os.path.join(_tmpdir, "test_billing.db"))

billing = load_service("bill_main", "billing_service")


@pytest.fixture(autouse=True)
async def reset_db():
    yield
    try:
        async with aiosqlite.connect(billing.DB_PATH) as db:
            await db.execute("DELETE FROM invoices")
            await db.execute("DELETE FROM revenue_log")
            await db.commit()
    except Exception:
        pass


@pytest.fixture
async def client():
    async with billing.lifespan(billing.app):
        transport = ASGITransport(app=billing.app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


SAMPLE_INVOICE = {
    "prospect_id": "prospect-001",
    "client_email": "client@example.com",
    "description": "Build REST API with auth",
    "amount_usd": 100.00,
    "token_cost_usd": 20.00,
    "platform": "upwork",
}


class TestDisputeFullRefund:
    async def test_full_refund_status_becomes_refunded(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.post(f"/invoices/{invoice_id}/dispute", json={
            "reason": "Not satisfied",
            "requested_refund_pct": 100.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] == 1
        assert data["status"] == "refunded"
        assert data["refund_amount_usd"] == 100.00
        assert data["reason"] == "Not satisfied"


class TestDisputePartialRefund:
    async def test_partial_refund_status_disputed(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.post(f"/invoices/{invoice_id}/dispute", json={
            "reason": "Partial issue",
            "requested_refund_pct": 50.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disputed"
        assert data["refund_amount_usd"] == 50.00


class TestDisputeErrors:
    async def test_dispute_nonexistent_invoice_404(self, client):
        resp = await client.post("/invoices/nonexistent/dispute", json={
            "reason": "test",
            "requested_refund_pct": 100.0,
        })
        assert resp.status_code == 404

    async def test_dispute_already_refunded_409(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        # First dispute - full refund
        await client.post(f"/invoices/{invoice_id}/dispute", json={
            "reason": "first",
            "requested_refund_pct": 100.0,
        })

        # Second dispute on refunded invoice
        resp = await client.post(f"/invoices/{invoice_id}/dispute", json={
            "reason": "again",
            "requested_refund_pct": 100.0,
        })
        assert resp.status_code == 409

    async def test_dispute_already_cancelled_409(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        await client.patch(f"/invoices/{invoice_id}", json={"status": "cancelled"})

        resp = await client.post(f"/invoices/{invoice_id}/dispute", json={
            "reason": "cancelled invoice",
            "requested_refund_pct": 50.0,
        })
        assert resp.status_code == 409


class TestProfitability:
    async def test_profitability_with_invoices(self, client):
        await client.post("/invoices", json=SAMPLE_INVOICE)
        await client.post("/invoices", json={**SAMPLE_INVOICE, "prospect_id": "p2", "platform": "fiverr"})

        resp = await client.get("/profitability")
        assert resp.status_code == 200
        data = resp.json()
        assert "upwork" in data
        assert "fiverr" in data
        assert data["upwork"]["jobs"] == 1
        assert data["upwork"]["revenue_usd"] == 100.00
        assert data["upwork"]["profit_usd"] == 80.00

    async def test_profitability_empty(self, client):
        resp = await client.get("/profitability")
        assert resp.status_code == 200
        assert resp.json() == {}
