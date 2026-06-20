import os
import sys

import httpx
import pytest

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from shared.retry import retry_post, retry_request


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            resp = httpx.Response(self.status_code, request=httpx.Request("POST", "http://test"))
            raise httpx.HTTPStatusError("error", request=resp.request, response=resp)


class TestRetryPost:
    async def test_succeeds_first_try(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                return FakeResponse(200, {"ok": 1})

        result = await retry_post(MockClient(), "http://test/api", max_retries=3, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 1

    async def test_succeeds_on_second_try(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise httpx.ConnectError("connection refused")
                return FakeResponse(200, {"ok": 1})

        result = await retry_post(MockClient(), "http://test/api", max_retries=3, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 2

    async def test_succeeds_on_third_try(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise httpx.ConnectError("connection refused")
                return FakeResponse(200, {"ok": 1})

        result = await retry_post(MockClient(), "http://test/api", max_retries=3, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 3

    async def test_exhausts_retries_and_raises(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectError("connection refused")

        with pytest.raises(httpx.ConnectError):
            await retry_post(MockClient(), "http://test/api", max_retries=3, backoff=0.01)
        assert call_count == 3

    async def test_does_not_retry_http_status_errors(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                return FakeResponse(500)

        with pytest.raises(httpx.HTTPStatusError):
            await retry_post(MockClient(), "http://test/api", max_retries=3, backoff=0.01)
        assert call_count == 1

    async def test_passes_kwargs_to_post(self):
        captured = {}

        class MockClient:
            async def post(self, url, **kwargs):
                captured.update(kwargs)
                return FakeResponse(200)

        await retry_post(
            MockClient(), "http://test/api",
            max_retries=1, backoff=0.01,
            json={"key": "val"}, headers={"X-Token": "abc"},
        )
        assert captured["json"] == {"key": "val"}
        assert captured["headers"] == {"X-Token": "abc"}

    async def test_single_retry_no_second_chance(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                raise httpx.ConnectError("fail")

        with pytest.raises(httpx.ConnectError):
            await retry_post(MockClient(), "http://test/api", max_retries=1, backoff=0.01)
        assert call_count == 1

    async def test_timeout_error_is_retried(self):
        call_count = 0

        class MockClient:
            async def post(self, url, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise httpx.ReadTimeout("timeout")
                return FakeResponse(200, {"ok": 1})

        result = await retry_post(MockClient(), "http://test/api", max_retries=2, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 2
