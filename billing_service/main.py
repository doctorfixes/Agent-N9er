import os
import sys
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware
from shared.config import CORS_ORIGINS
from shared.events import emit, EVENT_INVOICE_CREATED

os.environ.setdefault("SERVICE_NAME", "billing")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("billing")

DB_PATH = os.getenv("BILLING_DB_PATH", "/data/billing.db")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

stripe = None
if STRIPE_SECRET_KEY:
    try:
        import stripe as _stripe
        _stripe.api_key = STRIPE_SECRET_KEY
        stripe = _stripe
    except ImportError:
        logger.warning("stripe package not installed — billing in mock mode")


class InvoiceRequest(BaseModel):
    prospect_id: str
    client_email: str
    description: str
    amount_usd: float
    token_cost_usd: float = 0
    platform: str = "direct"
    metadata: dict = Field(default_factory=dict)


class InvoiceRecord(BaseModel):
    invoice_id: str
    prospect_id: str
    client_email: str
    description: str
    amount_usd: float
    token_cost_usd: float
    profit_usd: float
    platform: str
    status: str
    stripe_invoice_id: str | None = None
    created_at: str | None = None
    paid_at: str | None = None


class PaymentUpdate(BaseModel):
    status: str


VALID_STATUSES = {"draft", "sent", "paid", "failed", "refunded", "cancelled"}


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                prospect_id TEXT,
                client_email TEXT,
                description TEXT,
                amount_usd REAL,
                token_cost_usd REAL,
                profit_usd REAL,
                platform TEXT,
                status TEXT DEFAULT 'draft',
                stripe_invoice_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS revenue_log (
                id TEXT PRIMARY KEY,
                invoice_id TEXT,
                event TEXT,
                amount_usd REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
            )
        """)
        await db.commit()


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Billing", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST", "PATCH"], allow_headers=["*"])


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM invoices")
            count = (await cursor.fetchone())[0]
        return {
            "ok": 1,
            "service": "billing",
            "invoices": count,
            "stripe_connected": stripe is not None,
        }
    except Exception:
        return {"ok": 0, "service": "billing", "error": "db_unreachable"}


@app.post("/invoices")
async def create_invoice(req: InvoiceRequest) -> InvoiceRecord:
    invoice_id = str(uuid.uuid4())
    profit = round(req.amount_usd - req.token_cost_usd, 4)

    stripe_invoice_id = None
    if stripe and req.client_email:
        try:
            stripe_invoice_id = await _create_stripe_invoice(req, invoice_id)
        except Exception as e:
            logger.error("Stripe invoice creation failed: %s", e)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO invoices
               (invoice_id, prospect_id, client_email, description, amount_usd,
                token_cost_usd, profit_usd, platform, status, stripe_invoice_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (invoice_id, req.prospect_id, req.client_email, req.description,
             req.amount_usd, req.token_cost_usd, profit, req.platform,
             "sent" if stripe_invoice_id else "draft", stripe_invoice_id),
        )
        await _log_event(db, invoice_id, "created", req.amount_usd)
        await db.commit()

    logger.info(
        "Invoice %s created: $%.2f for %s (profit $%.2f)",
        invoice_id, req.amount_usd, req.prospect_id, profit,
    )

    await emit(EVENT_INVOICE_CREATED, {
        "invoice_id": invoice_id,
        "prospect_id": req.prospect_id,
        "amount_usd": req.amount_usd,
        "profit_usd": profit,
        "platform": req.platform,
    })

    return InvoiceRecord(
        invoice_id=invoice_id, prospect_id=req.prospect_id,
        client_email=req.client_email, description=req.description,
        amount_usd=req.amount_usd, token_cost_usd=req.token_cost_usd,
        profit_usd=profit, platform=req.platform,
        status="sent" if stripe_invoice_id else "draft",
        stripe_invoice_id=stripe_invoice_id,
    )


async def _create_stripe_invoice(req: InvoiceRequest, invoice_id: str) -> str:
    customers = stripe.Customer.list(email=req.client_email, limit=1)
    if customers.data:
        customer = customers.data[0]
    else:
        customer = stripe.Customer.create(
            email=req.client_email,
            metadata={"source": "agent-n9er", "prospect_id": req.prospect_id},
        )

    inv = stripe.Invoice.create(
        customer=customer.id,
        collection_method="send_invoice",
        days_until_due=7,
        metadata={"invoice_id": invoice_id, "prospect_id": req.prospect_id},
    )

    stripe.InvoiceItem.create(
        customer=customer.id,
        invoice=inv.id,
        amount=int(req.amount_usd * 100),
        currency="usd",
        description=req.description,
    )

    stripe.Invoice.finalize_invoice(inv.id)
    stripe.Invoice.send_invoice(inv.id)

    return inv.id


@app.get("/invoices")
async def list_invoices(status: str | None = None, limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM invoices WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM invoices ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in await cursor.fetchall()]


@app.get("/invoices/{invoice_id}")
async def get_invoice(invoice_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return dict(row)


@app.patch("/invoices/{invoice_id}")
async def update_invoice_status(invoice_id: str, update: PaymentUpdate):
    if update.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be one of: {VALID_STATUSES}")

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT invoice_id, amount_usd FROM invoices WHERE invoice_id = ?", (invoice_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Invoice not found")

        paid_clause = ""
        params = [update.status, invoice_id]
        if update.status == "paid":
            paid_clause = ", paid_at = ?"
            params = [update.status, datetime.now(timezone.utc).isoformat(), invoice_id]

        await db.execute(
            f"UPDATE invoices SET status = ?{paid_clause} WHERE invoice_id = ?",
            params,
        )
        await _log_event(db, invoice_id, f"status_{update.status}", row[1])
        await db.commit()

    return {"ok": 1, "invoice_id": invoice_id, "status": update.status}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    if not stripe or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook: {e}")

    if event["type"] == "invoice.paid":
        invoice_data = event["data"]["object"]
        our_invoice_id = invoice_data.get("metadata", {}).get("invoice_id")
        if our_invoice_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE invoices SET status = 'paid', paid_at = ? WHERE invoice_id = ?",
                    (datetime.now(timezone.utc).isoformat(), our_invoice_id),
                )
                await _log_event(db, our_invoice_id, "stripe_paid", invoice_data.get("amount_paid", 0) / 100)
                await db.commit()
            logger.info("Stripe payment received for invoice %s", our_invoice_id)

    elif event["type"] == "invoice.payment_failed":
        invoice_data = event["data"]["object"]
        our_invoice_id = invoice_data.get("metadata", {}).get("invoice_id")
        if our_invoice_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE invoices SET status = 'failed' WHERE invoice_id = ?",
                    (our_invoice_id,),
                )
                await _log_event(db, our_invoice_id, "stripe_failed", 0)
                await db.commit()

    return {"ok": 1}


@app.get("/revenue")
async def revenue_summary():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM invoices")
        total = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COUNT(*) FROM invoices WHERE status = 'paid'")
        paid_count = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COALESCE(SUM(amount_usd), 0) FROM invoices WHERE status = 'paid'")
        total_revenue = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COALESCE(SUM(profit_usd), 0) FROM invoices WHERE status = 'paid'")
        total_profit = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COALESCE(SUM(token_cost_usd), 0) FROM invoices WHERE status = 'paid'")
        total_token_cost = (await cursor.fetchone())[0]

        cursor = await db.execute("SELECT COALESCE(SUM(amount_usd), 0) FROM invoices WHERE status IN ('draft', 'sent')")
        outstanding = (await cursor.fetchone())[0]

    return {
        "total_invoices": total,
        "paid_invoices": paid_count,
        "total_revenue_usd": round(total_revenue, 2),
        "total_profit_usd": round(total_profit, 2),
        "total_token_cost_usd": round(total_token_cost, 2),
        "outstanding_usd": round(outstanding, 2),
        "profit_margin_pct": round((total_profit / total_revenue * 100) if total_revenue > 0 else 0, 1),
    }


async def _log_event(db, invoice_id: str, event: str, amount: float):
    await db.execute(
        "INSERT INTO revenue_log (id, invoice_id, event, amount_usd) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), invoice_id, event, amount),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9200)
