import logging

import mongomock
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError
from starlette.requests import Request as StarletteRequest

import app.services.ingestion as ingestion
from app.api import errors as api_errors
from app.config import Settings
from app.db import get_db
from app.main import app, create_app
from app.services import storage
from tests.test_analysis_api import _PARAMS, _install_fetch

_FORBIDDEN = ("http", "mongodb", "/", "\\", "traceback")
_SECRET = "mongodb://user:pass@host/secret /etc/passwd"


class _BrokenDatabase:
    def __getitem__(self, name: str) -> None:
        raise ServerSelectionTimeoutError("no server")


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    app.state.limiter.reset()
    yield
    app.state.limiter.reset()


@pytest.fixture
def db():
    database = mongomock.MongoClient()["t"]
    storage.ensure_indexes(database)
    return database


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _forwarded_key(monkeypatch: pytest.MonkeyPatch, client_ip: str, forwarded: str) -> str:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": headers,
        "client": (client_ip, 1),
    }
    return api_errors.client_identifier(StarletteRequest(scope))


def test_health_response_is_hardened_and_rate_limited(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-ratelimit-limit"] == "120"


def test_unknown_route_returns_safe_not_cacheable_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {
        "code": "not_found",
        "message": "The requested resource was not found.",
    }
    assert response.headers["cache-control"] == "no-store"


def test_method_not_allowed_returns_safe_405(client: TestClient) -> None:
    response = client.post("/health")
    assert response.status_code == 405
    assert response.json() == {
        "code": "method_not_allowed",
        "message": "The request method is not allowed for this resource.",
    }
    assert response.headers["cache-control"] == "no-store"


def test_validation_error_returns_safe_400(client: TestClient) -> None:
    response = client.get("/api/analysis", params=_PARAMS | {"lat": 28.6, "extra": 1})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert response.headers["cache-control"] == "no-store"
    text = response.text.lower()
    for token in _FORBIDDEN:
        assert token not in text


def test_oversized_query_value_is_safely_rejected(client: TestClient) -> None:
    response = client.get("/api/analysis", params={**_PARAMS, "lat": "9" * 5000})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert len(response.text) < 1000
    assert response.headers["cache-control"] == "no-store"


def test_unhandled_error_returns_safe_500_and_logs_only_the_type(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom() -> None:
        raise RuntimeError(_SECRET)

    app.dependency_overrides[get_db] = boom
    with caplog.at_level(logging.ERROR):
        response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "An internal error occurred.",
    }
    for token in _FORBIDDEN:
        assert token not in response.text
    assert "RuntimeError" in caplog.text
    assert "user:pass" not in caplog.text


def test_mapped_upstream_failure_is_not_cacheable(client: TestClient) -> None:
    app.dependency_overrides[get_db] = lambda: _BrokenDatabase()
    response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_analysis_response_carries_strong_validators_and_304(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingestion, "last_full_year", lambda: 2025)
    _install_fetch(monkeypatch)
    first = client.get("/api/analysis", params=_PARAMS)
    assert first.status_code == 200
    etag = first.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"') and len(etag) > 10
    assert first.headers["cache-control"] == "public, max-age=3600"
    assert first.headers["x-ratelimit-limit"] == "30"
    revalidated = client.get("/api/analysis", params=_PARAMS, headers={"If-None-Match": etag})
    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert revalidated.headers["etag"] == etag
    stale = client.get("/api/analysis", params=_PARAMS, headers={"If-None-Match": '"stale"'})
    assert stale.status_code == 200
    assert stale.headers["etag"] == etag


def test_rate_limit_exceeded_returns_429_with_retry_after(client: TestClient) -> None:
    responses = [client.get("/health") for _ in range(121)]
    exceeded = responses[-1]
    assert exceeded.status_code == 429
    assert exceeded.json() == {
        "code": "rate_limited",
        "message": "Too many requests. Please retry later.",
    }
    assert int(exceeded.headers["retry-after"]) >= 0
    assert exceeded.headers["cache-control"] == "no-store"


def test_cors_allows_configured_origin_and_rejects_others(db) -> None:
    origin = "https://app.example"
    cors_app = create_app(
        Settings(mongodb_uri="mongodb://localhost:27017", cors_allowed_origins=origin)
    )
    cors_app.dependency_overrides[get_db] = lambda: db
    test_client = TestClient(cors_app, raise_server_exceptions=False)
    allowed = test_client.options(
        "/api/analysis",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == origin
    assert "GET" in allowed.headers["access-control-allow-methods"]
    actual = test_client.get("/health", headers={"Origin": origin})
    assert actual.headers["access-control-allow-origin"] == origin
    exposed = actual.headers["access-control-expose-headers"].replace(" ", "").split(",")
    assert set(exposed) == {"ETag", "Retry-After"}
    assert "access-control-allow-credentials" not in actual.headers
    blocked = test_client.options(
        "/api/analysis",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in blocked.headers
    assert blocked.headers["cache-control"] == "no-store"


def test_forged_forwarded_for_does_not_change_key_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _forwarded_key(monkeypatch, "1.1.1.1", "9.9.9.9") == "1.1.1.1"
    assert _forwarded_key(monkeypatch, "1.1.1.1", "9.9.9.9") == _forwarded_key(
        monkeypatch, "1.1.1.1", ""
    )


def test_trusted_proxy_hops_uses_the_rightmost_forwarded_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_errors, "_SETTINGS", Settings(mongodb_uri="mongodb://localhost", trusted_proxy_hops=1)
    )
    assert _forwarded_key(monkeypatch, "10.0.0.1", "203.0.113.7") == "203.0.113.7"
