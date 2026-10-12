import json

import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.api import analysis as api_analysis
from app.db import get_db
from app.engine.events import EventError
from app.engine.insights import InsightError
from app.engine.metrics import MetricsError
from app.engine.thresholds import ThresholdError
from app.engine.trends import TrendError
from app.main import app
from app.services import ingestion, open_meteo, storage
from app.services.analysis import AnalysisError
from app.services.ingestion import IngestError
from app.services.open_meteo import UpstreamError
from app.services.regions import RegionError

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
            raise UpstreamError("Weather data is temporarily unavailable.")
        return _payload(start_year, end_year)

    monkeypatch.setattr(open_meteo, "fetch_daily_tmax", fake)
    return calls


class _BrokenDatabase:
    def __getitem__(self, name: str) -> None:
        raise ServerSelectionTimeoutError("no server")


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


def test_openapi_exposes_exactly_health_and_analysis(client) -> None:
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == {"/health", "/api/analysis"}


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (AnalysisError("year_out_of_range", "msg"), 400),
        (AnalysisError("data_unavailable", "msg"), 502),
        (AnalysisError("unexpected_code", "msg"), 500),
        (UpstreamError("upstream"), 502),
        (IngestError("ingest"), 502),
        (ThresholdError("threshold"), 502),
        (MetricsError("metrics"), 502),
        (LookupError("lookup"), 502),
        (ServerSelectionTimeoutError("mongo"), 503),
        (RegionError("region"), 400),
        (EventError("event"), 500),
        (TrendError("trend"), 500),
        (InsightError("insight"), 500),
        (ValueError("value"), 400),
        (RuntimeError("runtime"), 500),
    ],
)
def test_mapped_error_bodies_are_safe(exc: Exception, status: int) -> None:
    response = api_analysis._error_response(exc)
    assert response.status_code == status
    body = json.loads(response.body)
    assert set(body) == {"code", "message"}
    text = json.dumps(body).lower()
    for token in _FORBIDDEN:
        assert token not in text
