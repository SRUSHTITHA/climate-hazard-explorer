import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor

import mongomock
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.engine import metrics as metrics_engine
from app.engine import thresholds as thresholds_engine
from app.engine.thresholds import compute_thresholds
from app.errors import AppError
from app.models.schemas import AnalysisRequest, AnalysisResponse
from app.services import analysis, ingestion, open_meteo, storage

HISTORY_START = ingestion.HISTORY_START
LAST_FULL = 2025
CELL = "28.50_77.25"
SPIKE = 40.0


def _dates(start_year: int, end_year: int) -> list[str]:
    return [
        day.strftime("%Y-%m-%d")
        for day in pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31")
    ]


def _payload(start_year: int, end_year: int, spike_year: int | None = None) -> dict:
    dates = _dates(start_year, end_year)
    tmax = [25.0] * len(dates)
    if spike_year is not None:
        for offset in range(5):
            day = pd.Timestamp(f"{spike_year}-07-01") + pd.Timedelta(days=offset)
            tmax[dates.index(day.strftime("%Y-%m-%d"))] = SPIKE
    return {
        "grid_lat": 28.5,
        "grid_lon": 77.25,
        "elevation": 216.0,
        "utc_offset_seconds": 19800,
        "dates": dates,
        "tmax": tmax,
    }


def _install_fetch(monkeypatch: pytest.MonkeyPatch, spike_year=None, fail=frozenset()) -> list:
    calls: list[tuple] = []

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        calls.append((cell_id, start_year, end_year))
        if cell_id in fail:
            raise AppError(
                "upstream_error",
                open_meteo.UPSTREAM_ERROR_MESSAGE,
                status=502,
            )
        return _payload(start_year, end_year, spike_year)

    monkeypatch.setattr(open_meteo, "fetch_daily_tmax", fake)
    return calls


def _block_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args, **kwargs):
        raise AssertionError("engine must not run on a cache hit")

    for name in (
        "compute_thresholds",
        "detect_events",
        "annual_metrics",
        "region_metrics",
        "trend_table",
        "rolling_mean",
        "build_insights",
    ):
        monkeypatch.setattr(analysis, name, boom)


def _request(end_year: int = 2020) -> AnalysisRequest:
    return AnalysisRequest(lat=28.6, lon=77.2, start_year=HISTORY_START, end_year=end_year)


def _box_request() -> AnalysisRequest:
    return AnalysisRequest(
        south=0.0, west=0.0, north=0.25, east=0.25, start_year=HISTORY_START, end_year=2020
    )


def _point(response: AnalysisResponse, year: int):
    return next(point for point in response.series if point.year == year)


def _insight(response: AnalysisResponse, key: str):
    return next(insight for insight in response.insights if insight.key == key)


def _as_float(values: list) -> np.ndarray:
    return np.array([math.nan if value is None else float(value) for value in values])


@pytest.fixture
def db():
    database = mongomock.MongoClient()["t"]
    storage.ensure_indexes(database)
    return database


@pytest.fixture(autouse=True)
def _horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "last_full_year", lambda: LAST_FULL)


def test_cold_request_ingests_each_cell_once_and_stores_derived_docs(db, monkeypatch) -> None:
    calls = _install_fetch(monkeypatch)
    response = analysis.run_analysis(db, _request())
    assert calls == [(CELL, HISTORY_START, LAST_FULL)]
    assert isinstance(response, AnalysisResponse)
    assert response.cell_ids == [CELL]
    assert len(response.series) == 31
    assert db[storage.THRESHOLDS].count_documents({}) == 1
    assert db[storage.EVENTS].count_documents({}) == 0
    assert db[storage.ANNUAL_METRICS].count_documents({}) == LAST_FULL - HISTORY_START + 1
    assert db[storage.ANALYSES].count_documents({}) == 1


def test_warm_request_is_served_from_cache_with_no_engine_or_http(db, monkeypatch) -> None:
    calls = _install_fetch(monkeypatch)
    first = analysis.run_analysis(db, _request())
    calls.clear()
    _block_engine(monkeypatch)
    second = analysis.run_analysis(db, _request())
    assert calls == []
    assert second.model_dump() == first.model_dump()


def test_different_range_reuses_derived_docs_without_new_http(db, monkeypatch) -> None:
    calls = _install_fetch(monkeypatch)
    analysis.run_analysis(db, _request(end_year=2020))
    calls.clear()
    response = analysis.run_analysis(db, _request(end_year=2000))
    assert calls == []
    assert len(response.series) == 11


def test_known_spike_year_reports_one_event_of_five_days(db, monkeypatch) -> None:
    _install_fetch(monkeypatch, spike_year=2005)
    response = analysis.run_analysis(db, _request())
    point = _point(response, 2005)
    assert point.event_count == 1
    assert point.heatwave_days == 5
    assert _insight(response, "peak_year").text.endswith("was 5.0 in 2005.")
    assert _insight(response, "headline").text == (
        "Selected region: no clear trend was detected in heatwave days per year."
    )


def test_range_clipping_leaves_fixed_baseline_thresholds(db, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    analysis.run_analysis(db, _request(end_year=2000))
    stored = db[storage.THRESHOLDS].find_one({"cell_id": CELL})["values"]
    full = compute_thresholds(storage.load_raw_series(db, CELL, HISTORY_START, LAST_FULL))
    assert np.allclose(_as_float(stored), full.to_numpy(dtype=float), equal_nan=True)
    subset = storage.load_raw_series(db, CELL, HISTORY_START, 2000)
    with pytest.raises(AppError) as excinfo:
        compute_thresholds(subset)
    assert excinfo.value.code == "data_unavailable"


def test_end_year_equal_to_last_full_year_is_accepted(db, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    response = analysis.run_analysis(db, _request(end_year=LAST_FULL))
    assert response.end_year == LAST_FULL
    assert len(response.series) == LAST_FULL - HISTORY_START + 1


def test_end_year_beyond_last_full_year_raises_year_out_of_range(db, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    with pytest.raises(AppError) as excinfo:
        analysis.run_analysis(db, _request(end_year=LAST_FULL + 1))
    assert excinfo.value.code == "year_out_of_range"
    assert db[storage.ANALYSES].count_documents({}) == 0


def test_changing_last_full_year_invalidates_both_caches(db, monkeypatch) -> None:
    calls = _install_fetch(monkeypatch)
    monkeypatch.setattr(ingestion, "last_full_year", lambda: 2024)
    analysis.run_analysis(db, _request(end_year=2024))
    calls.clear()
    monkeypatch.setattr(ingestion, "last_full_year", lambda: 2025)
    analysis.run_analysis(db, _request(end_year=2024))
    assert calls == [(CELL, 2025, 2025)]
    assert db[storage.ANALYSES].count_documents({}) == 2
    stored = db[storage.THRESHOLDS].find_one({"cell_id": CELL})
    assert stored["computed_for_last_full_year"] == 2025


def test_one_of_four_cells_failing_still_returns_three_cell_quality(db, monkeypatch) -> None:
    box = _box_request()
    _install_fetch(monkeypatch, fail={box.cell_ids[0]})
    response = analysis.run_analysis(db, box)
    assert response.quality.cells == 3
    assert len(response.cell_ids) == 3
    assert box.cell_ids[0] not in response.cell_ids
    assert db[storage.ANALYSES].count_documents({}) == 0


def test_three_of_four_cells_failing_raises_data_unavailable(db, monkeypatch) -> None:
    box = _box_request()
    _install_fetch(monkeypatch, fail=set(box.cell_ids[:3]))
    with pytest.raises(AppError) as excinfo:
        analysis.run_analysis(db, box)
    assert excinfo.value.code == "data_unavailable"
    assert db[storage.ANALYSES].count_documents({}) == 0


def test_box_of_ten_cells_is_rejected_before_any_fetch(db, monkeypatch) -> None:
    calls = _install_fetch(monkeypatch)
    with pytest.raises(ValidationError):
        AnalysisRequest(
            south=0.0, west=0.0, north=0.25, east=1.0, start_year=HISTORY_START, end_year=2020
        )
    assert calls == []


def test_malformed_cached_body_is_recomputed(db, monkeypatch) -> None:
    _install_fetch(monkeypatch, spike_year=2005)
    first = analysis.run_analysis(db, _request())
    db[storage.ANALYSES].update_one({}, {"$set": {"result": {"hazard": "heatwave"}}})
    calls: list[int] = []
    real = metrics_engine.region_metrics

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analysis, "region_metrics", counting)
    second = analysis.run_analysis(db, _request())
    assert calls
    assert second.model_dump() == first.model_dump()


def test_stale_derived_doc_from_older_last_full_year_is_recomputed(db, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    analysis.run_analysis(db, _request())
    db[storage.THRESHOLDS].update_one({}, {"$set": {"computed_for_last_full_year": LAST_FULL - 1}})
    calls: list[int] = []
    real = thresholds_engine.compute_thresholds

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analysis, "compute_thresholds", counting)
    analysis.run_analysis(db, _request(end_year=2019))
    assert calls
    assert db[storage.THRESHOLDS].find_one({})["computed_for_last_full_year"] == LAST_FULL


def test_two_simultaneous_cold_requests_for_the_same_cell(db, monkeypatch) -> None:
    barrier = threading.Barrier(2)

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        barrier.wait(timeout=10)
        return _payload(start_year, end_year)

    monkeypatch.setattr(open_meteo, "fetch_daily_tmax", fake)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(analysis.run_analysis, db, _request()) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0].model_dump() == results[1].model_dump()
    assert db[storage.RAW_DAILY].count_documents({}) == LAST_FULL - HISTORY_START + 1
    assert db[storage.THRESHOLDS].count_documents({}) == 1
    assert db[storage.ANALYSES].count_documents({}) == 1


def test_analysis_doc_has_tz_aware_created_at_and_ttl_index(db, monkeypatch) -> None:
    captured: list[dict] = []
    original = storage.upsert_docs

    def spy(database, collection, key_fields, docs):
        captured.extend(docs)
        return original(database, collection, key_fields, docs)

    monkeypatch.setattr(storage, "upsert_docs", spy)
    storage.save_analysis(
        db,
        key="k",
        region="r",
        cell_ids=[CELL],
        hazard="heatwave",
        start_year=HISTORY_START,
        end_year=2020,
        computed_for_last_full_year=LAST_FULL,
        result={"ok": 1},
    )
    assert captured and captured[0]["created_at"].tzinfo is not None
    info = db[storage.ANALYSES].index_information()
    assert info["created_at_1"]["expireAfterSeconds"] == storage.ANALYSIS_TTL_SECONDS


def test_threshold_round_trip_preserves_nan_and_columns(db) -> None:
    values = np.arange(1.0, 367.0)
    values[0] = math.nan
    storage.save_thresholds(
        db,
        cell_id=CELL,
        hazard="heatwave",
        values=values,
        baseline_start=1991,
        baseline_end=2020,
        window_days=15,
        percentile=95.0,
        computed_for_last_full_year=LAST_FULL,
    )
    loaded = storage.load_thresholds(db, CELL, "heatwave", LAST_FULL)
    assert len(loaded) == 366
    assert math.isnan(loaded.loc[1])
    assert loaded.loc[2] == 2.0


def test_events_round_trip_preserve_columns(db) -> None:
    events = pd.DataFrame(
        {
            "start": [pd.Timestamp("2005-07-01")],
            "end": [pd.Timestamp("2005-07-05")],
            "year": [2005],
            "duration_days": [5],
            "peak_tmax": [SPIKE],
            "mean_tmax": [40.0],
            "intensity": [15.0],
            "max_exceedance": [15.0],
        }
    )
    storage.save_events(
        db, cell_id=CELL, hazard="heatwave", events=events, computed_for_last_full_year=LAST_FULL
    )
    loaded_events = storage.load_events(db, CELL, "heatwave")
    assert list(loaded_events.columns) == storage._EVENT_COLUMNS
    assert loaded_events.loc[0, "duration_days"] == 5
    assert loaded_events.loc[0, "start"] == pd.Timestamp("2005-07-01")


def test_annual_metrics_round_trip_restores_nan(db) -> None:
    index = pd.Index([2000, 2001], name="year")
    metrics = pd.DataFrame(
        {
            "valid_days": [365, 100],
            "total_days": [365, 365],
            "valid": [True, False],
            "event_count": [1.0, math.nan],
            "heatwave_days": [5.0, math.nan],
            "max_duration": [5.0, math.nan],
            "mean_duration": [5.0, math.nan],
            "mean_intensity": [15.0, math.nan],
            "max_exceedance": [15.0, math.nan],
            "peak_tmax": [40.0, math.nan],
        },
        index=index,
    )
    storage.save_annual_metrics(
        db, cell_id=CELL, hazard="heatwave", metrics=metrics, computed_for_last_full_year=LAST_FULL
    )
    loaded = storage.load_annual_metrics(db, CELL, "heatwave", LAST_FULL)
    assert list(loaded.columns) == storage._ANNUAL_COLUMNS
    assert loaded.loc[2000, "heatwave_days"] == 5.0
    assert math.isnan(loaded.loc[2001, "heatwave_days"])
    assert loaded.loc[2001, "valid_days"] == 100


def _event_frame(starts: list[str]) -> pd.DataFrame:
    start = pd.to_datetime(starts)
    fixed = {"duration_days": 3, "peak_tmax": 40.0, "mean_tmax": 40.0}
    return pd.DataFrame(
        {
            "start": start,
            "end": start + pd.Timedelta(days=2),
            "year": start.year,
            "intensity": 15.0,
            "max_exceedance": 15.0,
            **fixed,
        }
    )


def test_spike_response_lists_one_event_with_five_days(db, monkeypatch) -> None:
    _install_fetch(monkeypatch, spike_year=2005)
    events = analysis.run_analysis(db, _request()).events
    fields = [(e.cell_id, e.start, e.end, e.duration_days, e.year) for e in events]
    assert fields == [(CELL, "2005-07-01", "2005-07-05", 5, 2005)]


def test_event_in_invalid_year_is_excluded() -> None:
    tmax = pd.Series(25.0, index=pd.date_range("1990-01-01", "2000-12-31"))
    tmax[tmax.loc["2000"].sample(frac=0.5).index] = np.nan
    events = _event_frame(["1999-07-01", "2000-07-01"])
    annual = metrics_engine.annual_metrics(tmax, events)
    request = AnalysisRequest(lat=28.6, lon=77.2, start_year=1990, end_year=2000)
    response = analysis._assemble(request, [(CELL, (None, events, annual))])
    assert [event.year for event in response.events] == [1999]


def test_events_are_capped_at_300_with_full_total(db, monkeypatch) -> None:
    _install_fetch(monkeypatch)
    starts = list(pd.date_range("1999-01-01", periods=350).strftime("%Y-%m-%d"))
    monkeypatch.setattr(analysis, "detect_events", lambda *args, **kwargs: _event_frame(starts))
    response = analysis.run_analysis(db, _request())
    assert (len(response.events), response.quality.events_total) == (300, 350)


def test_response_serialises_with_no_nan(db, monkeypatch) -> None:
    _install_fetch(monkeypatch, spike_year=2005)
    response = analysis.run_analysis(db, _request())
    assert "NaN" not in json.dumps(response.model_dump(mode="json"), allow_nan=False)
