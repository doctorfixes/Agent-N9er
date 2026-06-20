import logging

from fastapi import FastAPI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("browser_service")

app = FastAPI(title="Verixio Browser Service")


@app.get("/health")
async def health():
    return {"ok": 1, "service": "browser"}


@app.get("/watchers")
async def list_watchers():
    return {
        "available": [
            "gmail", "drive", "slack", "notion",
            "airtable", "asana", "trello", "github",
        ],
        "active": [],
    }
