import os
import sys
import uuid
import smtplib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.security import RequestIDMiddleware, ServiceTokenMiddleware, MaxBodySizeMiddleware
from shared.config import CORS_ORIGINS
from shared.logging_config import setup_logging

logger = setup_logging("delivery")

DB_PATH = os.getenv("DELIVERY_DB_PATH", "/data/delivery.db")
EXECUTION_URL = os.getenv("EXECUTION_URL", "http://localhost:8400")
BILLING_URL = os.getenv("BILLING_URL", "http://localhost:9200")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
FROM_EMAIL = os.getenv("DELIVERY_FROM_EMAIL", SMTP_USER or "delivery@agentn9er.com")
FROM_NAME = os.getenv("DELIVERY_FROM_NAME", "Agent N9er")


class DeliverRequest(BaseModel):
    task_id: str
    client_email: str
    client_name: str = ""
    subject: str = ""
    message: str = ""
    format: str = "markdown"
    include_invoice: bool = True
    invoice_id: str = ""


class DeliveryRecord(BaseModel):
    delivery_id: str
    task_id: str
    client_email: str
    method: str
    status: str
    delivered_at: str | None = None


@asynccontextmanager
async def _get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deliveries (
                delivery_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                client_email TEXT NOT NULL,
                client_name TEXT DEFAULT '',
                method TEXT DEFAULT 'email',
                status TEXT DEFAULT 'pending',
                subject TEXT DEFAULT '',
                format TEXT DEFAULT 'markdown',
                output_preview TEXT DEFAULT '',
                invoice_id TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                delivered_at TEXT
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_task ON deliveries(task_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_status ON deliveries(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_client ON deliveries(client_email)")
        await db.commit()
    logger.info("Delivery database initialized at %s", DB_PATH)


@asynccontextmanager
async def lifespan(app):
    await _init_db()
    yield


app = FastAPI(title="Agent N9er Delivery Service", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(ServiceTokenMiddleware)
app.add_middleware(MaxBodySizeMiddleware)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])


def _svc_headers():
    headers = {}
    if SERVICE_TOKEN:
        headers["X-Service-Token"] = SERVICE_TOKEN
    return headers


@app.get("/health")
async def health():
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM deliveries")
            count = (await cursor.fetchone())[0]
        return {
            "ok": 1,
            "service": "delivery",
            "total_deliveries": count,
            "email_configured": bool(SMTP_HOST and SMTP_USER),
        }
    except Exception:
        return {"ok": 0, "service": "delivery", "error": "db_unreachable"}


@app.post("/deliver")
async def deliver(req: DeliverRequest):
    delivery_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    svc = _svc_headers()
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            exec_resp = await client.get(
                f"{EXECUTION_URL}/executions/{req.task_id}/output",
                headers=svc,
            )
            exec_resp.raise_for_status()
            exec_data = exec_resp.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            raise HTTPException(status_code=404, detail=f"Could not fetch execution output: {e}")

    output = exec_data.get("output", "")
    if not output:
        raise HTTPException(status_code=404, detail="No output found for this task")

    if req.format == "html":
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                fmt_resp = await client.post(
                    f"{EXECUTION_URL}/format-deliverable",
                    json={"task_id": req.task_id, "format": "html"},
                    headers=svc,
                )
                if fmt_resp.status_code == 200:
                    output = fmt_resp.json().get("content", output)
        except httpx.RequestError:
            pass

    subject = req.subject or f"Deliverable Ready: {req.task_id}"
    client_name = req.client_name or req.client_email.split("@")[0]

    invoice_info = ""
    if req.include_invoice and req.invoice_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                inv_resp = await client.get(
                    f"{BILLING_URL}/invoices/{req.invoice_id}",
                    headers=svc,
                )
                if inv_resp.status_code == 200:
                    inv = inv_resp.json()
                    invoice_info = (
                        f"\n\n---\n\nInvoice #{inv.get('invoice_id', '')[:8]}\n"
                        f"Amount: ${inv.get('amount_usd', 0):.2f}\n"
                        f"Status: {inv.get('status', 'draft')}\n"
                    )
        except httpx.RequestError:
            pass

    custom_message = f"\n\n{req.message}\n\n" if req.message else "\n\n"

    email_body = (
        f"Hi {client_name},\n\n"
        f"Your deliverable for task {req.task_id} is ready.{custom_message}"
        f"---\n\n"
        f"{output}"
        f"{invoice_info}\n\n"
        f"---\n"
        f"Delivered by Agent N9er\n"
    )

    status = "pending"
    error = ""

    if SMTP_HOST and SMTP_USER:
        try:
            _send_email(req.client_email, subject, email_body)
            status = "delivered"
            logger.info("Deliverable sent to %s for task %s", req.client_email, req.task_id)
        except Exception as e:
            status = "failed"
            error = str(e)
            logger.error("Email delivery failed for task %s: %s", req.task_id, e)
    else:
        status = "queued"
        logger.info("Delivery queued (no SMTP configured) for task %s to %s", req.task_id, req.client_email)

    delivered_at = now if status == "delivered" else None

    async with _get_db() as db:
        await db.execute(
            """INSERT INTO deliveries
               (delivery_id, task_id, client_email, client_name, method, status,
                subject, format, output_preview, invoice_id, error, created_at, delivered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (delivery_id, req.task_id, req.client_email, client_name,
             "email", status, subject, req.format, output[:200],
             req.invoice_id, error, now, delivered_at),
        )
        await db.commit()

    return {
        "ok": 1 if status != "failed" else 0,
        "delivery_id": delivery_id,
        "task_id": req.task_id,
        "client_email": req.client_email,
        "status": status,
        "method": "email",
        "error": error or None,
    }


def _send_email(to_email: str, subject: str, body: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{FROM_NAME} <{FROM_EMAIL}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, to_email, msg.as_string())


@app.get("/deliveries")
async def list_deliveries(
    task_id: str = None,
    client_email: str = None,
    status: str = None,
    limit: int = 50,
):
    async with _get_db() as db:
        query = "SELECT * FROM deliveries WHERE 1=1"
        params = []

        if task_id:
            query += " AND task_id = ?"
            params.append(task_id)
        if client_email:
            query += " AND client_email = ?"
            params.append(client_email)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


@app.post("/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: str):
    async with _get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM deliveries WHERE delivery_id = ?", (delivery_id,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Delivery not found")

        if row["status"] == "delivered":
            return {"ok": 0, "detail": "Already delivered"}

    return await deliver(DeliverRequest(
        task_id=row["task_id"],
        client_email=row["client_email"],
        client_name=row["client_name"],
        subject=row["subject"],
        format=row["format"],
        invoice_id=row["invoice_id"],
    ))


@app.get("/analytics")
async def delivery_analytics(days: int = 30):
    async with _get_db() as db:
        cursor = await db.execute(
            """SELECT status, COUNT(*) as cnt FROM deliveries
               WHERE created_at >= datetime('now', ?) GROUP BY status""",
            (f"-{days} days",),
        )
        by_status = {row[0]: row[1] for row in await cursor.fetchall()}

        cursor = await db.execute(
            "SELECT COUNT(DISTINCT client_email) FROM deliveries WHERE created_at >= datetime('now', ?)",
            (f"-{days} days",),
        )
        unique_clients = (await cursor.fetchone())[0]

    total = sum(by_status.values())
    delivered = by_status.get("delivered", 0)

    return {
        "period_days": days,
        "total_deliveries": total,
        "by_status": by_status,
        "delivery_rate": round(delivered / total, 4) if total else 0,
        "unique_clients": unique_clients,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9400)
