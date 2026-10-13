import json

import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.db import get_db
from app.errors import AppError
from app.main import app
from app.services import ingestion, open_meteo, storage

HISTORY_START = ingestion.HISTORY_START
LAST_FULL = 2025
CELL = "28.50_77.25"
_FORBIDDEN = ("http", "mongodb", "/", "\\", "traceback")


def _payload(start_year: int, end_year: int) -> dict:
    dates = [
        day.strftime("%Y-%m-%d")
        for day in pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31")
    ]
    return {
        "grid_lat": 28.5,
        "grid_lon": 77.25,
        "elevation": 216.0,
        "utc_offset_seconds": 19800,
        "dates": dates,
        "tmax": [25.0] * len(dates),
    }


def _install_fetch(monkeypatch: pytest.MonkeyPatch, fail=frozenset()) -> list:
    calls: list[tuple] = []

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        calls.append((cell_id, start_year, end_year))
        if cell_id in fail:
            raise AppError(
                "upstream_error",
                open_meteo.UPSTREAM_ERROR_MESSAGE,
                status=502,
            )
        return _payload(start_year, end_year)

    monkeypatch.setattr(open_meteo, "fetch_daily_tmax", fake)
    return calls


class _BrokenDatabase:
    def __getitem__(self, name: str) -> None:
        raise ServerSelectionTimeoutError("no server")


class _UnexpectedDatabase:
    def __getitem__(self, name: str) -> None:
        raise RuntimeError("private database details")


@pytest.fixture
def db():
    database = mongomock.MongoClient()["t"]
    storage.ensure_indexes(database)
    return database


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "last_full_year", lambda: LAST_FULL)


_PARAMS = {"lat": 28.6, "lon": 77.2, "start_year": HISTORY_START, "end_year": 2020}


def test_cold_request_returns_200_with_strict_json(client, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 200
    assert "NaN" not in response.text and "Infinity" not in response.text
    body = response.json()
    assert body["cell_ids"] == [CELL]
    assert set(body["trends"]) == {"heatwave_days", "mean_intensity"}
    assert body["attribution"].startswith("Data: ERA5")


def test_end_year_out_of_range_returns_400(client, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    response = client.get("/api/analysis", params={**_PARAMS, "end_year": LAST_FULL + 1})
    assert response.status_code == 400
    assert response.json() == {
        "code": "year_out_of_range",
        "message": f"end_year must be {LAST_FULL} or earlier.",
    }


def test_all_cells_failing_returns_502_data_unavailable(client, monkeypatch) -> None:
    _install_fetch(monkeypatch, fail={CELL})
    response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 502
    assert response.json()["code"] == "data_unavailable"


def test_database_failure_returns_503(client) -> None:
    app.dependency_overrides[get_db] = lambda: _BrokenDatabase()
    response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"


def test_unexpected_analysis_failure_returns_safe_500(client) -> None:
    app.dependency_overrides[get_db] = lambda: _UnexpectedDatabase()
    response = client.get("/api/analysis", params=_PARAMS)
    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "An internal error occurred while computing the analysis.",
    }


def test_schema_validation_error_returns_safe_400_body(client) -> None:
    response = client.get(
        "/api/analysis", params={"lat": 28.6, "lon": 77.2, "start_year": 2015, "end_year": 2020}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert "traceback" not in response.text.lower()
    assert "\\" not in response.text


def test_injection_query_param_is_rejected_before_database_touch(client) -> None:
    app.dependency_overrides[get_db] = lambda: object()
    params = {"lat[$ne]": 1, "start_year": 1990, "end_year": 2020}
    response = client.get("/api/analysis", params=params)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


def test_unknown_extra_query_param_is_rejected(client) -> None:
    response = client.get("/api/analysis", params={**_PARAMS, "extra": 1})
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"


def test_openapi_exposes_exactly_health_analysis_and_regions(client) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == {"/health", "/api/analysis", "/api/regions"}


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (AppError("year_out_of_range", "msg", status=400), 400, "year_out_of_range"),
        (AppError("data_unavailable", "msg", status=502), 502, "data_unavailable"),
        (AppError("unexpected_code", "msg", status=500), 500, "unexpected_code"),
        (AppError("upstream_error", "msg", status=502), 502, "upstream_error"),
        (AppError("invalid_region", "msg", status=400), 400, "invalid_region"),
        (AppError("internal_error", "msg", status=500), 500, "internal_error"),
    ],
)
def test_app_error_bodies_preserve_code_and_status(exc: AppError, status: int, code: str) -> None:
    from starlette.requests import Request

    from app.api.errors import app_error_handler

    request = Request({"type": "http", "method": "GET", "path": "/"})
    response = app_error_handler(request, exc)
    assert response.status_code == status
    body = json.loads(response.body)
    assert set(body) == {"code", "message"}
    assert body["code"] == code
    text = json.dumps(body).lower()
    for token in _FORBIDDEN:
        assert token not in text
