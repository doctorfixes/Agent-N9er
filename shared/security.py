import os
import time
import uuid
import logging
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("security")

API_KEY = os.getenv("API_KEY", "")
SERVICE_TOKEN = os.getenv("SERVICE_TOKEN", "")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        cutoff = now - self.window_seconds

        self.requests[client_ip] = [
            t for t in self.requests[client_ip] if t > cutoff
        ]

        if len(self.requests[client_ip]) >= self.max_requests:
            logger.warning("Rate limit exceeded for %s on %s", client_ip, request.url.path)
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        self.requests[client_ip].append(now)
        response = await call_next(request)
        remaining = self.max_requests - len(self.requests[client_ip])
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Limit"] = str(self.max_requests)
        return response


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key header on external-facing endpoints."""

    OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if not API_KEY:
            return await call_next(request)

        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        key = request.headers.get("X-API-Key", "")
        token = request.headers.get("X-Service-Token", "")

        if SERVICE_TOKEN and token == SERVICE_TOKEN:
            return await call_next(request)

        if key != API_KEY:
            logger.warning("Unauthorized request to %s from %s",
                           request.url.path, request.client.host if request.client else "unknown")
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        return await call_next(request)


class ServiceTokenMiddleware(BaseHTTPMiddleware):
    """Validates X-Service-Token header on internal services."""

    OPEN_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

    async def dispatch(self, request: Request, call_next):
        if not SERVICE_TOKEN:
            return await call_next(request)

        if request.url.path in self.OPEN_PATHS:
            return await call_next(request)

        token = request.headers.get("X-Service-Token", "")
        if token != SERVICE_TOKEN:
            logger.warning("Missing service token on %s from %s",
                           request.url.path, request.client.host if request.client else "unknown")
            return JSONResponse(status_code=403, content={"detail": "Invalid service token"})

        return await call_next(request)


def get_service_headers() -> dict:
    """Returns headers to include in inter-service HTTP calls."""
    headers = {}
    if SERVICE_TOKEN:
        headers["X-Service-Token"] = SERVICE_TOKEN
    return headers
