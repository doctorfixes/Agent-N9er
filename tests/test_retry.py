import os
import sys
from unittest.mock import AsyncMock, patch

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


class TestRetryRequest:
    async def test_succeeds_first_try(self):
        call_count = 0
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            return FakeResponse(200, {"ok": 1})

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await retry_request("GET", "http://test/api", max_retries=3, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 1

    async def test_retries_on_connect_error(self):
        call_count = 0
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.ConnectError("connection refused")
            return FakeResponse(200, {"ok": 1})

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await retry_request("POST", "http://test/api", max_retries=3, backoff=0.01)
        assert result.json() == {"ok": 1}
        assert call_count == 3

    async def test_exhausts_retries_and_raises(self):
        call_count = 0
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("connection refused")

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(httpx.ConnectError):
                await retry_request("GET", "http://test/api", max_retries=2, backoff=0.01)
        assert call_count == 2

    async def test_passes_headers_and_kwargs(self):
        captured_method = None
        captured_headers = None
        captured_kwargs = {}
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            nonlocal captured_method, captured_headers, captured_kwargs
            captured_method = method
            captured_headers = headers
            captured_kwargs = kwargs
            return FakeResponse(200)

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            await retry_request(
                "PUT", "http://test/api",
                max_retries=1, backoff=0.01,
                headers={"Authorization": "Bearer token"},
                json={"key": "val"},
            )
        assert captured_method == "PUT"
        assert captured_headers == {"Authorization": "Bearer token"}
        assert captured_kwargs["json"] == {"key": "val"}

    async def test_does_not_retry_http_status_errors(self):
        call_count = 0
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            nonlocal call_count
            call_count += 1
            return FakeResponse(500)

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(httpx.HTTPStatusError):
                await retry_request("GET", "http://test/api", max_retries=3, backoff=0.01)
        assert call_count == 1

    async def test_timeout_parameter_used(self):
        mock_client = AsyncMock()

        async def mock_request(method, url, headers=None, **kwargs):
            return FakeResponse(200)

        mock_client.request = mock_request

        with patch("shared.retry.httpx.AsyncClient") as MockClass:
            MockClass.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            MockClass.return_value.__aexit__ = AsyncMock(return_value=False)
            await retry_request("GET", "http://test/api", timeout=42.0, max_retries=1, backoff=0.01)
            MockClass.assert_called_with(timeout=42.0)
