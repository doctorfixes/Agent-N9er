"""Tests for the billing service — invoicing, payments, and revenue tracking."""

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
    "amount_usd": 30.00,
    "token_cost_usd": 10.00,
    "platform": "upwork",
}


class TestCreateInvoice:
    async def test_create_basic(self, client):
        resp = await client.post("/invoices", json=SAMPLE_INVOICE)
        data = resp.json()
        assert resp.status_code == 200
        assert data["invoice_id"]
        assert data["amount_usd"] == 30.00
        assert data["token_cost_usd"] == 10.00
        assert data["profit_usd"] == 20.00
        assert data["status"] == "draft"
        assert data["platform"] == "upwork"

    async def test_profit_calculation(self, client):
        resp = await client.post("/invoices", json={
            **SAMPLE_INVOICE,
            "amount_usd": 45.00,
            "token_cost_usd": 15.00,
        })
        data = resp.json()
        assert data["profit_usd"] == 30.00

    async def test_zero_cost_invoice(self, client):
        resp = await client.post("/invoices", json={
            **SAMPLE_INVOICE,
            "token_cost_usd": 0,
        })
        data = resp.json()
        assert data["profit_usd"] == 30.00


class TestListInvoices:
    async def test_list_empty(self, client):
        resp = await client.get("/invoices")
        assert resp.json() == []

    async def test_list_with_data(self, client):
        await client.post("/invoices", json=SAMPLE_INVOICE)
        await client.post("/invoices", json={**SAMPLE_INVOICE, "prospect_id": "p2"})
        resp = await client.get("/invoices")
        assert len(resp.json()) == 2

    async def test_filter_by_status(self, client):
        r1 = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r1.json()["invoice_id"]
        await client.patch(f"/invoices/{invoice_id}", json={"status": "paid"})

        await client.post("/invoices", json={**SAMPLE_INVOICE, "prospect_id": "p2"})

        paid = await client.get("/invoices", params={"status": "paid"})
        assert len(paid.json()) == 1
        assert paid.json()[0]["status"] == "paid"


class TestGetInvoice:
    async def test_get_by_id(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.get(f"/invoices/{invoice_id}")
        assert resp.status_code == 200
        assert resp.json()["invoice_id"] == invoice_id

    async def test_not_found(self, client):
        resp = await client.get("/invoices/nonexistent")
        assert resp.status_code == 404


class TestUpdateInvoice:
    async def test_mark_paid(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "paid"})
        assert resp.json()["ok"] == 1

        invoice = (await client.get(f"/invoices/{invoice_id}")).json()
        assert invoice["status"] == "paid"
        assert invoice["paid_at"] is not None

    async def test_mark_cancelled(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "cancelled"})
        assert resp.json()["ok"] == 1

    async def test_invalid_status(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "bogus"})
        assert resp.status_code == 422

    async def test_update_nonexistent(self, client):
        resp = await client.patch("/invoices/fake", json={"status": "paid"})
        assert resp.status_code == 404


class TestRevenue:
    async def test_revenue_empty(self, client):
        resp = await client.get("/revenue")
        data = resp.json()
        assert data["total_invoices"] == 0
        assert data["total_revenue_usd"] == 0
        assert data["total_profit_usd"] == 0

    async def test_revenue_with_paid_invoices(self, client):
        r1 = await client.post("/invoices", json=SAMPLE_INVOICE)
        await client.patch(f"/invoices/{r1.json()['invoice_id']}", json={"status": "paid"})

        r2 = await client.post("/invoices", json={
            **SAMPLE_INVOICE, "prospect_id": "p2", "amount_usd": 60.00, "token_cost_usd": 20.00,
        })
        await client.patch(f"/invoices/{r2.json()['invoice_id']}", json={"status": "paid"})

        resp = await client.get("/revenue")
        data = resp.json()
        assert data["total_invoices"] == 2
        assert data["paid_invoices"] == 2
        assert data["total_revenue_usd"] == 90.00
        assert data["total_profit_usd"] == 60.00
        assert data["total_token_cost_usd"] == 30.00
        assert data["profit_margin_pct"] > 0

    async def test_outstanding_calculation(self, client):
        await client.post("/invoices", json=SAMPLE_INVOICE)
        resp = await client.get("/revenue")
        assert resp.json()["outstanding_usd"] == 30.00


class TestHealth:
    async def test_health_ok(self, client):
        resp = await client.get("/health")
        data = resp.json()
        assert data["ok"] == 1
        assert data["service"] == "billing"


class TestConversionFunnel:
    async def test_funnel_empty(self, client):
        resp = await client.get("/funnel")
        data = resp.json()
        assert data["invoiced"] == 0
        assert data["paid"] == 0
        assert data["payment_rate_pct"] == 0
        assert data["by_platform"] == []

    async def test_funnel_with_data(self, client):
        r1 = await client.post("/invoices", json=SAMPLE_INVOICE)
        await client.patch(f"/invoices/{r1.json()['invoice_id']}", json={"status": "paid"})

        r2 = await client.post("/invoices", json={**SAMPLE_INVOICE, "prospect_id": "p2"})
        await client.patch(f"/invoices/{r2.json()['invoice_id']}", json={"status": "sent"})

        await client.post("/invoices", json={
            **SAMPLE_INVOICE, "prospect_id": "p3", "platform": "freelancer",
        })

        resp = await client.get("/funnel")
        data = resp.json()
        assert data["invoiced"] == 3
        assert data["paid"] == 1
        assert data["sent"] == 1
        assert data["period_days"] == 30
        assert len(data["by_platform"]) == 2

    async def test_funnel_custom_days(self, client):
        resp = await client.get("/funnel", params={"days": 7})
        data = resp.json()
        assert data["period_days"] == 7

    async def test_funnel_platform_breakdown(self, client):
        r1 = await client.post("/invoices", json=SAMPLE_INVOICE)
        await client.patch(f"/invoices/{r1.json()['invoice_id']}", json={"status": "paid"})

        resp = await client.get("/funnel")
        platforms = resp.json()["by_platform"]
        assert len(platforms) == 1
        assert platforms[0]["platform"] == "upwork"
        assert platforms[0]["paid"] == 1
        assert platforms[0]["revenue_usd"] == 30.00
        assert platforms[0]["conversion_pct"] == 100.0


class TestStripeWebhook:
    async def test_webhook_disabled(self, client):
        resp = await client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": ""})
        assert resp.status_code == 501
