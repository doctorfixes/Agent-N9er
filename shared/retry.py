import asyncio
import logging

import httpx

from shared.config import MAX_RETRIES, RETRY_BACKOFF

logger = logging.getLogger("retry")


async def retry_post(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = None,
    backoff: float = None,
    **kwargs,
):
    retries = max_retries if max_retries is not None else MAX_RETRIES
    backoff_base = backoff if backoff is not None else RETRY_BACKOFF
    last_exc = None
    for attempt in range(retries):
        try:
            resp = await client.post(url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code >= 500 and attempt < retries - 1:
                wait = backoff_base * (2 ** attempt)
                logger.warning("Retry %d/%d for %s (HTTP %d): %s",
                               attempt + 1, retries, url, e.response.status_code, e)
                await asyncio.sleep(wait)
            elif e.response.status_code < 500:
                raise
        except httpx.RequestError as e:
            last_exc = e
            if attempt < retries - 1:
                wait = backoff_base * (2 ** attempt)
                logger.warning("Retry %d/%d for %s: %s", attempt + 1, retries, url, e)
                await asyncio.sleep(wait)
    raise last_exc


async def retry_request(
    method: str,
    url: str,
    timeout: float = 10.0,
    max_retries: int = None,
    backoff: float = None,
    headers: dict = None,
    **kwargs,
):
    retries = max_retries if max_retries is not None else MAX_RETRIES
    backoff_base = backoff if backoff is not None else RETRY_BACKOFF
    last_exc = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.request(method, url, headers=headers, **kwargs)
                resp.raise_for_status()
                return resp
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code >= 500 and attempt < retries - 1:
                wait = backoff_base * (2 ** attempt)
                logger.warning("Retry %d/%d for %s %s (HTTP %d): %s",
                               attempt + 1, retries, method, url, e.response.status_code, e)
                await asyncio.sleep(wait)
            elif e.response.status_code < 500:
                raise
        except httpx.RequestError as e:
            last_exc = e
            if attempt < retries - 1:
                wait = backoff_base * (2 ** attempt)
                logger.warning("Retry %d/%d for %s %s: %s", attempt + 1, retries, method, url, e)
                await asyncio.sleep(wait)
    raise last_exc
