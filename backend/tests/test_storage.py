import datetime as dt
import math
from unittest import mock

import mongomock
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.engine.cleaning import days_in_year
from app.errors import AppError
from app.main import app
from app.services import storage

_CELL = "28.50_77.25"
_GRID_LAT = 28.5
_GRID_LON = 77.25
_ELEVATION = 216.0
_UTC_OFFSET = 19800
_QUALITY = {"missing_days": 0, "invalid_days": 0, "suspect_days": 0}


class _RaisingDatabase:
    def __getattr__(self, name: str) -> None:
        raise AssertionError("_RaisingDatabase was touched")


def _db():
    return mongomock.MongoClient()["test"]


def _save(db, year, tmax=None, cell=_CELL, quality=None):
    if tmax is None:
        tmax = [25.0] * days_in_year(year)
    storage.save_raw_year(
        db,
        cell_id=cell,
        year=year,
        tmax=tmax,
        source="open-meteo-era5",
        unit="C",
        grid_lat=_GRID_LAT,
        grid_lon=_GRID_LON,
        elevation=_ELEVATION,
        utc_offset_seconds=_UTC_OFFSET,
        quality=quality if quality is not None else _QUALITY,
    )


def test_ensure_indexes_is_idempotent_and_enforces_uniqueness() -> None:
    db = _db()
    storage.ensure_indexes(db)
    storage.ensure_indexes(db)
    assert db[storage.RAW_DAILY].index_information()["cell_id_1_year_1"].get("unique")
    db[storage.RAW_DAILY].insert_one({"_id": 1, "cell_id": _CELL, "year": 2024})
    with pytest.raises(DuplicateKeyError):
        db[storage.RAW_DAILY].insert_one({"_id": 2, "cell_id": _CELL, "year": 2024})


def test_ensure_indexes_creates_all_expected_indexes() -> None:
    db = _db()
    storage.ensure_indexes(db)
    assert "cell_id_1_year_1" in db[storage.RAW_DAILY].index_information()
    assert (
        "cell_id_1_baseline_start_1_baseline_end_1_window_days_1_percentile_1"
        in db[storage.THRESHOLDS].index_information()
    )
    assert "cell_id_1_hazard_1_start_1" in db[storage.EVENTS].index_information()
    assert "cell_id_1_hazard_1_year_1" in db[storage.ANNUAL_METRICS].index_information()
    analyses = db[storage.ANALYSES].index_information()
    assert "key_1" in analyses
    assert analyses["created_at_1"].get("expireAfterSeconds") == storage.ANALYSIS_TTL_SECONDS


def test_save_raw_year_round_trip_derives_counts_and_sanitises_nan() -> None:
    db = _db()
    storage.ensure_indexes(db)
    tmax = [25.0] * 363 + [float("nan"), None]
    _save(db, 2021, tmax)
    doc = db[storage.RAW_DAILY].find_one({"cell_id": _CELL, "year": 2021})
    assert doc["total_days"] == 365
    assert doc["valid_days"] == 363
    assert doc["tmax"][-2] is None
    assert doc["tmax"][-1] is None
    assert not any(isinstance(value, float) and math.isnan(value) for value in doc["tmax"])
    assert doc["unit"] == "C"
    assert doc["source"] == "open-meteo-era5"
    assert doc["grid_lat"] == _GRID_LAT
    assert doc["elevation"] == _ELEVATION
    assert doc["utc_offset_seconds"] == _UTC_OFFSET
    assert doc["quality"] == _QUALITY
    stored = doc["fetched_at"]
    assert stored.tzinfo is None  # pymongo/mongomock return naive UTC datetimes
    assert abs((dt.datetime.now(dt.UTC) - stored.replace(tzinfo=dt.UTC)).total_seconds()) < 30


@pytest.mark.parametrize("year,wrong", [(2021, 364), (2024, 365)])
def test_save_raw_year_rejects_wrong_length(year: int, wrong: int) -> None:
    with pytest.raises(ValueError):
        _save(_db(), year, tmax=[25.0] * wrong)


def test_save_raw_year_accepts_correct_lengths() -> None:
    db = _db()
    storage.ensure_indexes(db)
    _save(db, 2021, [25.0] * 365)
    _save(db, 2024, [25.0] * 366)
    assert db[storage.RAW_DAILY].count_documents({}) == 2


def test_saving_same_cell_year_twice_replaces_document_and_updates_fetched_at() -> None:
    db = _db()
    storage.ensure_indexes(db)
    first_fetched = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    second_fetched = dt.datetime(2026, 2, 1, tzinfo=dt.UTC)
    with mock.patch("app.services.storage.dt") as fake_dt:
        fake_dt.datetime.now.return_value = first_fetched
        _save(db, 2024, [29.0] * 366)
        fake_dt.datetime.now.return_value = second_fetched
        _save(db, 2024, [31.0] * 366)
    docs = list(db[storage.RAW_DAILY].find({"cell_id": _CELL, "year": 2024}))
    assert len(docs) == 1
    assert docs[0]["tmax"][0] == 31.0
    assert docs[0]["fetched_at"] == second_fetched.replace(tzinfo=None)


def test_existing_years_returns_only_stored_years_in_range() -> None:
    db = _db()
    storage.ensure_indexes(db)
    for year in (2019, 2020, 2021, 2023):
        _save(db, year)
    assert storage.existing_years(db, _CELL, 2020, 2022) == {2020, 2021}


def test_save_raw_year_rejects_non_numeric_tmax_entries() -> None:
    with pytest.raises(ValueError, match="only numbers or null"):
        _save(_db(), 2021, tmax=[25.0] * 364 + ["25.0"])
    with pytest.raises(ValueError, match="only numbers or null"):
        _save(_db(), 2021, tmax=[25.0] * 364 + [float("inf")])


def test_load_raw_series_round_trip_over_two_years_preserves_gaps() -> None:
    db = _db()
    storage.ensure_indexes(db)
    tmax_2020 = [20.0 + 0.1 * i for i in range(366)]
    tmax_2020[100] = None
    tmax_2021 = [22.0] * 365
    _save(db, 2020, tmax_2020)
    _save(db, 2021, tmax_2021)
    series = storage.load_raw_series(db, _CELL, 2020, 2021)
    assert len(series) == 731
    assert series.index[0] == pd.Timestamp("2020-01-01")
    assert series.index[-1] == pd.Timestamp("2021-12-31")
    assert series.loc["2020-01-01"] == 20.0
    assert series.loc["2020-04-10"] != 20.0
    assert math.isnan(series.loc["2020-04-10"])
    assert series.loc["2021-12-31"] == 22.0


def test_load_raw_series_skipped_middle_year_is_nan() -> None:
    db = _db()
    storage.ensure_indexes(db)
    _save(db, 1999)
    _save(db, 2001)
    series = storage.load_raw_series(db, _CELL, 1999, 2001)
    assert len(series) == 1096
    assert series.loc["1999-01-01"] == 25.0
    assert all(math.isnan(value) for value in series.loc["2000"])
    assert series.loc["2001-12-31"] == 25.0


def test_load_raw_series_with_no_stored_years_raises() -> None:
    db = _db()
    storage.ensure_indexes(db)
    with pytest.raises(LookupError):
        storage.load_raw_series(db, _CELL, 2020, 2022)


def test_upsert_docs_rejects_unknown_collection() -> None:
    with pytest.raises(ValueError, match="Unknown collection"):
        storage.upsert_docs(_db(), "not_a_collection", ("cell_id",), [{"cell_id": "x"}])


def test_upsert_docs_rejects_doc_missing_key_field() -> None:
    db = _db()
    with pytest.raises(ValueError, match="missing a key field"):
        storage.upsert_docs(db, storage.RAW_DAILY, ("cell_id", "year"), [{"cell_id": "x"}])


def test_upsert_docs_rejects_empty_key_fields() -> None:
    with pytest.raises(ValueError, match="key_fields"):
        storage.upsert_docs(_db(), storage.RAW_DAILY, (), [{"cell_id": "x", "year": 2024}])


def test_upsert_docs_missing_key_in_any_doc_writes_nothing() -> None:
    db = _db()
    storage.ensure_indexes(db)
    docs = [
        {"cell_id": _CELL, "year": 2000, "source": "a"},
        {"cell_id": _CELL},
    ]
    with pytest.raises(ValueError):
        storage.upsert_docs(db, storage.RAW_DAILY, ("cell_id", "year"), docs)
    assert db[storage.RAW_DAILY].count_documents({}) == 0


def test_upsert_docs_sanitises_nested_nan() -> None:
    db = _db()
    storage.ensure_indexes(db)
    storage.upsert_docs(
        db,
        storage.RAW_DAILY,
        ("cell_id", "year"),
        [
            {
                "cell_id": _CELL,
                "year": 2000,
                "tmax": [float("nan"), 27.0],
                "quality": {"missing_days": 0, "invalid_days": float("nan")},
            }
        ],
    )
    doc = db[storage.RAW_DAILY].find_one({"cell_id": _CELL, "year": 2000})
    assert doc["tmax"][0] is None
    assert doc["quality"]["invalid_days"] is None
    assert not any(
        isinstance(value, float) and math.isnan(value)
        for value in list(doc["tmax"]) + list(doc["quality"].values())
    )


def test_upsert_docs_empty_list_returns_zero_without_db_touch() -> None:
    assert storage.upsert_docs(_RaisingDatabase(), storage.RAW_DAILY, ("cell_id",), []) == 0


def test_upsert_docs_empty_list_after_allowlist_check() -> None:
    with pytest.raises(ValueError):
        storage.upsert_docs(_db(), "not_a_collection", ("cell_id",), [])


def test_upsert_docs_writes_many_docs() -> None:
    db = _db()
    storage.ensure_indexes(db)
    docs = [{"cell_id": _CELL, "year": year, "v": float(year)} for year in range(2000, 2000 + 500)]
    assert storage.upsert_docs(db, storage.RAW_DAILY, ("cell_id", "year"), docs) == 500
    assert db[storage.RAW_DAILY].count_documents({}) == 500


@pytest.mark.parametrize("bad_cell", ["abc", "999.00_0.00", {"$ne": None}])
def test_invalid_cell_id_rejected_before_database_touch(bad_cell) -> None:
    with pytest.raises(AppError) as excinfo:
        _save(_RaisingDatabase(), 2024, cell=bad_cell)
    assert excinfo.value.code == "invalid_region"


def test_startup_ensures_indexes_and_health_up() -> None:
    mock_db = mongomock.MongoClient()["test"]
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with mock.patch("app.main.get_db", return_value=mock_db):
            with TestClient(app) as client:
                assert client.get("/health").json() == {"status": "ok", "database": "up"}
        assert "cell_id_1_year_1" in mock_db[storage.RAW_DAILY].index_information()
    finally:
        app.dependency_overrides.clear()


def test_startup_survives_index_failure_and_health_responds() -> None:
    mock_db = mongomock.MongoClient()["test"]
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with mock.patch("app.main.get_db", return_value=mock_db):
            with mock.patch("app.main.ensure_indexes", side_effect=RuntimeError("boom")):
                with TestClient(app) as client:
                    response = client.get("/health")
                    assert response.status_code == 200
                    assert response.json() == {"status": "ok", "database": "up"}
    finally:
        app.dependency_overrides.clear()
