import datetime as dt
import logging
import math
from typing import Any

import pandas as pd
from pymongo.database import Database

from app.engine.cleaning import clean_daily, days_in_year
from app.services.regions import cell_center

RAW_DAILY = "raw_daily"
THRESHOLDS = "thresholds"
EVENTS = "events"
ANNUAL_METRICS = "annual_metrics"
ANALYSES = "analyses"
ANALYSIS_TTL_SECONDS = 7 * 24 * 60 * 60

_COLLECTIONS = (RAW_DAILY, THRESHOLDS, EVENTS, ANNUAL_METRICS, ANALYSES)
_LOGGER = logging.getLogger(__name__)

_UNIQUE_INDEXES = {
    RAW_DAILY: [("cell_id", 1), ("year", 1)],
    THRESHOLDS: [
        ("cell_id", 1),
        ("baseline_start", 1),
        ("baseline_end", 1),
        ("window_days", 1),
        ("percentile", 1),
    ],
    EVENTS: [("cell_id", 1), ("hazard", 1), ("start", 1)],
    ANNUAL_METRICS: [("cell_id", 1), ("hazard", 1), ("year", 1)],
}


def ensure_indexes(db: Database) -> None:
    for collection, spec in _UNIQUE_INDEXES.items():
        db[collection].create_index(spec, unique=True)
    db[ANALYSES].create_index("key", unique=True)
    db[ANALYSES].create_index("created_at", expireAfterSeconds=ANALYSIS_TTL_SECONDS)


def upsert_docs(
    db: Database, collection: str, key_fields: tuple[str, ...], docs: list[dict]
) -> int:
    if collection not in _COLLECTIONS:
        raise ValueError(f"Unknown collection: {collection}")
    if not docs:
        return 0
    if not key_fields:
        raise ValueError("key_fields must not be empty.")
    for doc in docs:
        if any(field not in doc for field in key_fields):
            raise ValueError("Document missing a key field.")
    for doc in docs:
        db[collection].replace_one(
            {field: doc[field] for field in key_fields}, _sanitize(doc), upsert=True
        )
    return len(docs)


def save_raw_year(
    db: Database,
    *,
    cell_id: str,
    year: int,
    tmax: list,
    source: str,
    unit: str,
    grid_lat: float,
    grid_lon: float,
    elevation: float | None,
    utc_offset_seconds: int,
    quality: dict,
) -> None:
    cell_center(cell_id)
    expected = days_in_year(year)
    if len(tmax) != expected:
        raise ValueError(f"tmax must contain {expected} values for {year}.")
    for value in tmax:
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("tmax must contain only numbers or null.")
        if isinstance(value, float) and math.isinf(value):
            raise ValueError("tmax must contain only numbers or null.")
    valid_days = sum(
        1
        for value in tmax
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    )
    upsert_docs(
        db,
        RAW_DAILY,
        ("cell_id", "year"),
        [
            {
                "cell_id": cell_id,
                "year": year,
                "source": source,
                "unit": unit,
                "fetched_at": dt.datetime.now(dt.UTC),
                "grid_lat": grid_lat,
                "grid_lon": grid_lon,
                "elevation": elevation,
                "utc_offset_seconds": utc_offset_seconds,
                "tmax": tmax,
                "total_days": len(tmax),
                "valid_days": valid_days,
                "quality": quality,
            }
        ],
    )


def existing_years(db: Database, cell_id: str, start_year: int, end_year: int) -> set[int]:
    docs = db[RAW_DAILY].find(
        {"cell_id": cell_id, "year": {"$gte": start_year, "$lte": end_year}}, {"year": 1, "_id": 0}
    )
    return {int(doc["year"]) for doc in docs}


def load_raw_series(db: Database, cell_id: str, start_year: int, end_year: int) -> pd.Series:
    docs = list(
        db[RAW_DAILY]
        .find({"cell_id": cell_id, "year": {"$gte": start_year, "$lte": end_year}})
        .sort("year", 1)
    )
    if not docs:
        raise LookupError(f"No raw data stored for {cell_id} in {start_year}-{end_year}.")
    dates: list[str] = []
    values: list = []
    for doc in docs:
        year = int(doc["year"])
        start = f"{year}-01-01"
        dates.extend(day.strftime("%Y-%m-%d") for day in pd.date_range(start, f"{year}-12-31"))
        values.extend(doc["tmax"])
    return clean_daily(dates, values)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, float) and math.isnan(value):
        return None
    return value
