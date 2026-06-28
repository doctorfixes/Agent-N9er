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


class TestPlatformField:
    async def test_default_platform(self, client):
        resp = await client.post("/invoices", json={
            "prospect_id": "p-plat",
            "client_email": "plat@example.com",
            "description": "Test platform",
            "amount_usd": 10.00,
            "token_cost_usd": 2.00,
        })
        data = resp.json()
        assert data["platform"] == "direct"

    async def test_custom_platform(self, client):
        resp = await client.post("/invoices", json={
            "prospect_id": "p-plat2",
            "client_email": "plat2@example.com",
            "description": "Test platform",
            "amount_usd": 10.00,
            "token_cost_usd": 2.00,
            "platform": "fiverr",
        })
        data = resp.json()
        assert data["platform"] == "fiverr"


class TestUpdateInvoiceStatuses:
    async def test_mark_sent(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]
        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "sent"})
        assert resp.json()["ok"] == 1
        invoice = (await client.get(f"/invoices/{invoice_id}")).json()
        assert invoice["status"] == "sent"

    async def test_mark_failed(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]
        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "failed"})
        assert resp.json()["ok"] == 1

    async def test_mark_refunded(self, client):
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]
        resp = await client.patch(f"/invoices/{invoice_id}", json={"status": "refunded"})
        assert resp.json()["ok"] == 1


class TestStripeInvoiceCreation:
    async def test_create_invoice_with_stripe(self, client):
        """Test invoice creation when stripe is configured."""
        from unittest.mock import MagicMock, patch

        mock_stripe = MagicMock()
        mock_customer = MagicMock()
        mock_customer.id = "cus_123"
        mock_stripe.Customer.list.return_value = MagicMock(data=[mock_customer])

        mock_invoice = MagicMock()
        mock_invoice.id = "inv_stripe_123"
        mock_stripe.Invoice.create.return_value = mock_invoice

        original_stripe = billing.stripe
        try:
            billing.stripe = mock_stripe

            resp = await client.post("/invoices", json={
                "prospect_id": "p-stripe",
                "client_email": "stripe@example.com",
                "description": "Stripe test",
                "amount_usd": 50.00,
                "token_cost_usd": 10.00,
            })

            data = resp.json()
            assert resp.status_code == 200
            assert data["status"] == "sent"
            assert data["stripe_invoice_id"] == "inv_stripe_123"
        finally:
            billing.stripe = original_stripe

    async def test_create_invoice_stripe_new_customer(self, client):
        """Test invoice creation when stripe creates new customer."""
        from unittest.mock import MagicMock

        mock_stripe = MagicMock()
        # No existing customer
        mock_stripe.Customer.list.return_value = MagicMock(data=[])
        mock_new_customer = MagicMock()
        mock_new_customer.id = "cus_new"
        mock_stripe.Customer.create.return_value = mock_new_customer

        mock_invoice = MagicMock()
        mock_invoice.id = "inv_new_123"
        mock_stripe.Invoice.create.return_value = mock_invoice

        original_stripe = billing.stripe
        try:
            billing.stripe = mock_stripe

            resp = await client.post("/invoices", json={
                "prospect_id": "p-new",
                "client_email": "new@example.com",
                "description": "New customer test",
                "amount_usd": 25.00,
                "token_cost_usd": 5.00,
            })

            data = resp.json()
            assert resp.status_code == 200
            assert data["stripe_invoice_id"] == "inv_new_123"
            mock_stripe.Customer.create.assert_called_once()
        finally:
            billing.stripe = original_stripe

    async def test_create_invoice_stripe_failure(self, client):
        """Test invoice creation when stripe raises an error."""
        from unittest.mock import MagicMock

        mock_stripe = MagicMock()
        mock_stripe.Customer.list.side_effect = Exception("Stripe API error")

        original_stripe = billing.stripe
        try:
            billing.stripe = mock_stripe

            resp = await client.post("/invoices", json={
                "prospect_id": "p-err",
                "client_email": "err@example.com",
                "description": "Stripe error test",
                "amount_usd": 30.00,
                "token_cost_usd": 5.00,
            })

            data = resp.json()
            assert resp.status_code == 200
            # Should fall back to draft status when stripe fails
            assert data["status"] == "draft"
            assert data["stripe_invoice_id"] is None
        finally:
            billing.stripe = original_stripe


class TestStripeWebhookEvents:
    async def test_stripe_webhook_invoice_paid(self, client):
        """Test stripe webhook for invoice.paid event."""
        from unittest.mock import MagicMock

        # First create a local invoice
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        mock_stripe = MagicMock()
        mock_event = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "metadata": {"invoice_id": invoice_id},
                    "amount_paid": 3000,
                }
            }
        }
        mock_stripe.Webhook.construct_event.return_value = mock_event

        original_stripe = billing.stripe
        original_secret = billing.STRIPE_WEBHOOK_SECRET
        try:
            billing.stripe = mock_stripe
            billing.STRIPE_WEBHOOK_SECRET = "whsec_test"

            resp = await client.post(
                "/webhooks/stripe",
                content=b'{"type": "invoice.paid"}',
                headers={"stripe-signature": "t=123,v1=abc"},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] == 1

            # Verify invoice was marked as paid
            inv = (await client.get(f"/invoices/{invoice_id}")).json()
            assert inv["status"] == "paid"
            assert inv["paid_at"] is not None
        finally:
            billing.stripe = original_stripe
            billing.STRIPE_WEBHOOK_SECRET = original_secret

    async def test_stripe_webhook_invoice_payment_failed(self, client):
        """Test stripe webhook for invoice.payment_failed event."""
        from unittest.mock import MagicMock

        # Create a local invoice
        r = await client.post("/invoices", json=SAMPLE_INVOICE)
        invoice_id = r.json()["invoice_id"]

        mock_stripe = MagicMock()
        mock_event = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "metadata": {"invoice_id": invoice_id},
                }
            }
        }
        mock_stripe.Webhook.construct_event.return_value = mock_event

        original_stripe = billing.stripe
        original_secret = billing.STRIPE_WEBHOOK_SECRET
        try:
            billing.stripe = mock_stripe
            billing.STRIPE_WEBHOOK_SECRET = "whsec_test"

            resp = await client.post(
                "/webhooks/stripe",
                content=b'{"type": "invoice.payment_failed"}',
                headers={"stripe-signature": "t=123,v1=abc"},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] == 1

            # Verify invoice was marked as failed
            inv = (await client.get(f"/invoices/{invoice_id}")).json()
            assert inv["status"] == "failed"
        finally:
            billing.stripe = original_stripe
            billing.STRIPE_WEBHOOK_SECRET = original_secret

    async def test_stripe_webhook_invalid_signature(self, client):
        """Test stripe webhook with invalid signature."""
        from unittest.mock import MagicMock

        mock_stripe = MagicMock()
        mock_stripe.Webhook.construct_event.side_effect = Exception("Invalid signature")

        original_stripe = billing.stripe
        original_secret = billing.STRIPE_WEBHOOK_SECRET
        try:
            billing.stripe = mock_stripe
            billing.STRIPE_WEBHOOK_SECRET = "whsec_test"

            resp = await client.post(
                "/webhooks/stripe",
                content=b'{}',
                headers={"stripe-signature": "invalid"},
            )
            assert resp.status_code == 400
        finally:
            billing.stripe = original_stripe
            billing.STRIPE_WEBHOOK_SECRET = original_secret


class TestStripeWebhook:
    async def test_webhook_disabled(self, client):
        resp = await client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": ""})
        assert resp.status_code == 501
