from datetime import date
import mongomock
import pandas as pd
import pytest
from app.engine.cleaning import clean_daily, days_in_year, quality_report
from app.services import ingestion, open_meteo, regions, storage

CELL = "28.50_77.25" 
LAST_FULL = 2025
WINDOW_START = ingestion.HISTORY_START

def _dates(start_year: int, end_year: int) -> list[str]:
    return [
        day.strftime("%Y-%m-%d")
        for day in pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31")
    ]

def _payload(start_year: int, end_year: int, tmax: list | None = None) -> dict:
    dates = _dates(start_year, end_year)
    values = tmax if tmax is not None else [25.0] * len(dates)
    return {
        "grid_lat": 28.5,
        "grid_lon": 77.25,
        "elevation": 216.0,
        "utc_offset_seconds": 19800,
        "dates": dates,
        "tmax": values,
    }

def _db() -> mongomock.MongoClient:
    db = mongomock.MongoClient()["t"]
    storage.ensure_indexes(db)
    return db

def _save_year(db, year: int, cell: str = CELL) -> None:
    storage.save_raw_year(
        db,
        cell_id=cell,
        year=year,
        tmax=[25.0] * days_in_year(year),
        source="open-meteo-era5",
        unit="C",
        grid_lat=28.5,
        grid_lon=77.25,
        elevation=216.0,
        utc_offset_seconds=19800,
        quality={"missing_days": 0, "invalid_days": 0, "suspect_days": 0},
    )

@pytest.fixture(autouse=True)
def _fixed_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingestion, "last_full_year", lambda: LAST_FULL)

@pytest.fixture
def _no_fetch(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list[tuple] = []

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        calls.append((cell_id, start_year, end_year))
        return _payload(start_year, end_year)

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    return calls

def test_ingest_cold_cell_fetches_whole_span_once_and_counts_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    dates = _dates(WINDOW_START, LAST_FULL)
    by_date = {day: i for i, day in enumerate(dates)}
    tmax = [25.0] * len(dates)
    missing_i = by_date["1995-06-15"]
    invalid_i = by_date["2010-09-01"]
    suspect_i = by_date["2020-07-10"]
    tmax[missing_i] = None
    tmax[invalid_i] = 200.0
    tmax[suspect_i] = 50.0
    calls: list[tuple] = []

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        calls.append((cell_id, start_year, end_year))
        return _payload(WINDOW_START, LAST_FULL, tmax)

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)

    result = ingestion.ingest_cell(db, CELL)

    assert result["status"] == "ingested"
    assert result["fetched_years"] == list(range(WINDOW_START, LAST_FULL + 1))
    assert result["skipped_years"] == []
    assert calls == [(CELL, WINDOW_START, LAST_FULL)]
    assert db[storage.RAW_DAILY].count_documents({"cell_id": CELL}) == LAST_FULL - WINDOW_START + 1
    doc_1995 = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 1995})
    assert doc_1995["quality"] == {"missing_days": 1, "invalid_days": 0, "suspect_days": 0}
    assert doc_1995["valid_days"] == 364 and doc_1995["total_days"] == 365
    doc_2010 = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 2010})
    assert doc_2010["quality"] == {"missing_days": 0, "invalid_days": 1, "suspect_days": 0}
    doc_2020 = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 2020})
    assert doc_2020["quality"] == {"missing_days": 0, "invalid_days": 0, "suspect_days": 1}
    assert doc_2020["tmax"][(date(2020, 7, 10) - date(2020, 1, 1)).days] == 50.0  # suspect retained

def test_warm_cell_is_cached_with_zero_http_calls(_no_fetch: list) -> None:
    db = _db()
    for year in range(WINDOW_START, LAST_FULL + 1):
        _save_year(db, year)
    result = ingestion.ingest_cell(db, CELL)
    assert result["status"] == "cached"
    assert result["fetched_years"] == []
    assert result["skipped_years"] == list(range(WINDOW_START, LAST_FULL + 1))
    assert _no_fetch == []

def test_gap_missing_years_are_fetched_in_one_covered_call_only(_no_fetch: list) -> None:
    db = _db()
    for year in list(range(WINDOW_START, 2001)) + list(range(2005, LAST_FULL + 1)):
        _save_year(db, year)
    before_1995 = dict(db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 1995}, {"_id": 0}))
    before_2005 = dict(db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 2005}, {"_id": 0}))
    result = ingestion.ingest_cell(db, CELL)
    assert result["status"] == "ingested"
    assert result["fetched_years"] == [2001, 2002, 2003, 2004]
    assert _no_fetch == [(CELL, 2001, 2004)]
    for year in range(2001, 2005):
        assert db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": year}) is not None
    after_1995 = dict(db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 1995}, {"_id": 0}))
    after_2005 = dict(db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 2005}, {"_id": 0}))
    assert after_1995 == before_1995
    assert after_2005 == before_2005

def test_short_response_raises_typed_error_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    for year in list(range(WINDOW_START, 2001)) + list(range(2005, LAST_FULL + 1)):
        _save_year(db, year)
    truncated = _dates(2001, 2004)[: (date(2004, 6, 30) - date(2001, 1, 1)).days + 1]

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        return {
            "grid_lat": 28.5,
            "grid_lon": 77.25,
            "elevation": 216.0,
            "utc_offset_seconds": 19800,
            "dates": truncated,
            "tmax": [25.0] * len(truncated),
        }

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    with pytest.raises(ingestion.IngestError):
        ingestion.ingest_cell(db, CELL)
    assert (
        db[storage.RAW_DAILY].count_documents(
            {"cell_id": CELL, "year": {"$gte": 2001, "$lte": 2004}}
        )
        == 0
    )

def test_region_one_cell_fails_others_ingest_without_url_in_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    cells = [CELL, "30.00_75.50", "31.00_76.00"]

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        if cell_id == cells[1]:
            raise RuntimeError("boom")
        return _payload(start_year, end_year)

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    results = ingestion.ingest_region(db, cells)
    assert len(results) == 3
    assert results[0]["status"] == "ingested"
    assert results[2]["status"] == "ingested"
    assert results[1]["status"] == "failed"
    assert results[1]["error"] == "boom"
    assert "http" not in results[1]["error"]
    assert db[storage.RAW_DAILY].count_documents({"cell_id": cells[1]}) == 0
    assert db[storage.RAW_DAILY].count_documents({"cell_id": cells[2]}) == 36

def test_region_rejects_more_than_nine_cells_before_any_call(_no_fetch: list) -> None:
    db = _db()
    cells = [regions.cell_id(28.50 + i, 77.25 + j) for i in range(2) for j in range(5)]
    assert len(cells) > regions.MAX_CELLS
    with pytest.raises(ValueError, match=str(regions.MAX_CELLS)):
        ingestion.ingest_region(db, cells)
    assert _no_fetch == []

def test_leap_year_lengths_and_missing_feb_29(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    for year in range(2000, LAST_FULL + 1):
        _save_year(db, year)
    dates = _dates(1990, 1999)
    tmax = [25.0] * len(dates)
    dropped = "1992-02-29"
    drop_idx = dates.index(dropped)
    del dates[drop_idx]
    del tmax[drop_idx]
    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        return {
            "grid_lat": 28.5,
            "grid_lon": 77.25,
            "elevation": 216.0,
            "utc_offset_seconds": 19800,
            "dates": dates,
            "tmax": tmax,
        }

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    result = ingestion.ingest_cell(db, CELL)
    assert result["fetched_years"] == list(range(1990, 2000))
    for year, expected in ((1990, 365), (1992, 366), (1996, 366), (1999, 365)):
        doc = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": year})
        assert doc is not None
        assert len(doc["tmax"]) == expected, f"year {year}"
    doc_1992 = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 1992})
    assert doc_1992["tmax"][59] is None
    assert doc_1992["quality"]["missing_days"] == 1

def test_per_year_quality_counts_sum_to_whole_span_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    dates = _dates(WINDOW_START, LAST_FULL)
    by_date = {day: i for i, day in enumerate(dates)}
    tmax = [25.0] * len(dates)
    for target, value in (
        ("1995-06-15", None),
        ("1996-02-28", 200.0),
        ("2010-09-01", None),
        ("2020-07-10", 50.0),
        ("2024-12-31", 200.0),
    ):
        tmax[by_date[target]] = value

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        return _payload(WINDOW_START, LAST_FULL, tmax)

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    ingestion.ingest_cell(db, CELL)
    whole = quality_report(clean_daily(dates, tmax))
    docs = db[storage.RAW_DAILY].find({"cell_id": CELL})
    summed = {"missing_days": 0, "invalid_days": 0, "suspect_days": 0}
    for doc in docs:
        for key in summed:
            summed[key] += doc["quality"][key]
    assert summed == {
        "missing_days": whole["missing_days"],
        "invalid_days": whole["invalid_days"],
        "suspect_days": whole["suspect_days"],
    }

def test_malformed_cell_id_rejected_before_any_http_or_db_call(_no_fetch: list) -> None:
    class _Forbidden:
        def __getitem__(self, _key):
            raise AssertionError("db must not be touched")

    db = _Forbidden()
    with pytest.raises(regions.RegionError):
        ingestion.ingest_cell(db, {"$ne": None})
    with pytest.raises(regions.RegionError):
        ingestion.ingest_cell(db, "999.00_0.00")
    with pytest.raises(regions.RegionError):
        ingestion.ingest_cell(db, "28.50_77.25_x")
    assert _no_fetch == []

def test_null_filled_year_is_stored_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    for year in list(range(WINDOW_START, 2001)) + list(range(2005, LAST_FULL + 1)):
        _save_year(db, year)
    dates = _dates(2001, 2004)
    tmax = [None if "2003" in day else 25.0 for day in dates]

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        return {
            "grid_lat": 28.5,
            "grid_lon": 77.25,
            "elevation": 216.0,
            "utc_offset_seconds": 19800,
            "dates": dates,
            "tmax": tmax,
        }

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    result = ingestion.ingest_cell(db, CELL)
    assert result["fetched_years"] == [2001, 2002, 2003, 2004]
    doc_2003 = db[storage.RAW_DAILY].find_one({"cell_id": CELL, "year": 2003})
    assert doc_2003["quality"]["missing_days"] == 365
    assert doc_2003["valid_days"] == 0 and len(doc_2003["tmax"]) == 365
    assert all(value is None for value in doc_2003["tmax"])

def test_duplicate_dated_response_raises_typed_error_and_saves_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _db()
    for year in list(range(WINDOW_START, 2001)) + list(range(2005, LAST_FULL + 1)):
        _save_year(db, year)
    dates = _dates(2001, 2004)
    dates[100] = dates[99]  # duplicate date away from the span endpoints

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        return {
            "grid_lat": 28.5,
            "grid_lon": 77.25,
            "elevation": 216.0,
            "utc_offset_seconds": 19800,
            "dates": dates,
            "tmax": [25.0] * len(dates),
        }

    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    with pytest.raises(ingestion.IngestError):
        ingestion.ingest_cell(db, CELL)
    assert (
        db[storage.RAW_DAILY].count_documents(
            {"cell_id": CELL, "year": {"$gte": 2001, "$lte": 2004}}
        )
        == 0
    )

def test_mid_region_timeout_is_captured_with_safe_message(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db()
    cells = [CELL, "30.00_75.50", "31.00_76.00"]

    def fake(cell_id: str, start_year: int, end_year: int, client=None):
        if cell_id == cells[2]:
            raise open_meteo.UpstreamError(
                "Weather data is temporarily unavailable. Please try again later."
            )
        return _payload(start_year, end_year)
    monkeypatch.setattr(ingestion.open_meteo, "fetch_daily_tmax", fake)
    results = ingestion.ingest_region(db, cells)
    assert results[2]["status"] == "failed"
    assert open_meteo.ARCHIVE_URL not in results[2]["error"]
    assert "http" not in results[2]["error"]
    assert results[0]["status"] == "ingested" and results[1]["status"] == "ingested"
    assert db[storage.RAW_DAILY].count_documents({"cell_id": cells[0]}) == 36
