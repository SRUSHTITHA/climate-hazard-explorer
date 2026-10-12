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


_THRESHOLD_KEY = ("cell_id", "baseline_start", "baseline_end", "window_days", "percentile")
_EVENT_KEY = ("cell_id", "hazard", "start")
_ANNUAL_KEY = ("cell_id", "hazard", "year")
_ANALYSIS_KEY = ("key",)
_EVENT_COLUMNS = [
    "start",
    "end",
    "year",
    "duration_days",
    "peak_tmax",
    "mean_tmax",
    "intensity",
    "max_exceedance",
]
_ANNUAL_COLUMNS = [
    "valid_days",
    "total_days",
    "valid",
    "event_count",
    "heatwave_days",
    "max_duration",
    "mean_duration",
    "mean_intensity",
    "max_exceedance",
    "peak_tmax",
]


def save_thresholds(
    db: Database,
    *,
    cell_id: str,
    hazard: str,
    values: Any,
    baseline_start: int,
    baseline_end: int,
    window_days: int,
    percentile: float,
    computed_for_last_full_year: int,
) -> None:
    cell_center(cell_id)
    doc = {
        "cell_id": cell_id,
        "baseline_start": baseline_start,
        "baseline_end": baseline_end,
        "window_days": window_days,
        "percentile": percentile,
        "hazard": hazard,
        "values": [None if math.isnan(v) else float(v) for v in values],
        "computed_for_last_full_year": computed_for_last_full_year,
        "created_at": dt.datetime.now(dt.UTC),
    }
    upsert_docs(db, THRESHOLDS, _THRESHOLD_KEY, [doc])


def load_thresholds(
    db: Database, cell_id: str, hazard: str, computed_for_last_full_year: int
) -> pd.Series | None:
    doc = db[THRESHOLDS].find_one({"cell_id": cell_id, "hazard": hazard})
    if doc is None or doc.get("computed_for_last_full_year") != computed_for_last_full_year:
        return None
    values = [math.nan if value is None else float(value) for value in doc["values"]]
    return pd.Series(values, index=range(1, len(values) + 1), name="threshold")


def save_events(
    db: Database,
    *,
    cell_id: str,
    hazard: str,
    events: pd.DataFrame,
    computed_for_last_full_year: int,
) -> None:
    cell_center(cell_id)
    now = dt.datetime.now(dt.UTC)
    docs = [
        {
            "cell_id": cell_id,
            "hazard": hazard,
            "year": int(row.year),
            "start": pd.Timestamp(row.start).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(row.end).strftime("%Y-%m-%d"),
            "duration_days": int(row.duration_days),
            "peak_tmax": float(row.peak_tmax),
            "mean_tmax": float(row.mean_tmax),
            "intensity": float(row.intensity),
            "max_exceedance": float(row.max_exceedance),
            "computed_for_last_full_year": computed_for_last_full_year,
            "created_at": now,
        }
        for row in events.itertuples(index=False)
    ]
    upsert_docs(db, EVENTS, _EVENT_KEY, docs)


def load_events(db: Database, cell_id: str, hazard: str) -> pd.DataFrame:
    docs = list(db[EVENTS].find({"cell_id": cell_id, "hazard": hazard}).sort("start", 1))
    if not docs:
        return _empty_events()
    frame = pd.DataFrame(
        [
            {
                "start": pd.Timestamp(doc["start"]),
                "end": pd.Timestamp(doc["end"]),
                "year": int(doc["year"]),
                "duration_days": int(doc["duration_days"]),
                "peak_tmax": float(doc["peak_tmax"]),
                "mean_tmax": float(doc["mean_tmax"]),
                "intensity": float(doc["intensity"]),
                "max_exceedance": float(doc["max_exceedance"]),
            }
            for doc in docs
        ]
    )
    return frame.loc[:, _EVENT_COLUMNS]


def save_annual_metrics(
    db: Database,
    *,
    cell_id: str,
    hazard: str,
    metrics: pd.DataFrame,
    computed_for_last_full_year: int,
) -> None:
    cell_center(cell_id)
    docs = [
        {
            "cell_id": cell_id,
            "hazard": hazard,
            "year": int(year),
            "valid_days": int(row["valid_days"]),
            "total_days": int(row["total_days"]),
            "valid": bool(row["valid"]),
            "event_count": float(row["event_count"]),
            "heatwave_days": float(row["heatwave_days"]),
            "max_duration": float(row["max_duration"]),
            "mean_duration": float(row["mean_duration"]),
            "mean_intensity": float(row["mean_intensity"]),
            "max_exceedance": float(row["max_exceedance"]),
            "peak_tmax": float(row["peak_tmax"]),
            "computed_for_last_full_year": computed_for_last_full_year,
            "created_at": dt.datetime.now(dt.UTC),
        }
        for year, row in metrics.iterrows()
    ]
    upsert_docs(db, ANNUAL_METRICS, _ANNUAL_KEY, docs)


def load_annual_metrics(
    db: Database, cell_id: str, hazard: str, computed_for_last_full_year: int
) -> pd.DataFrame | None:
    docs = list(db[ANNUAL_METRICS].find({"cell_id": cell_id, "hazard": hazard}).sort("year", 1))
    if not docs:
        return None
    if any(doc.get("computed_for_last_full_year") != computed_for_last_full_year for doc in docs):
        return None
    frame = pd.DataFrame(
        [
            {
                "year": int(doc["year"]),
                "valid_days": int(doc["valid_days"]),
                "total_days": int(doc["total_days"]),
                "valid": bool(doc["valid"]),
                "event_count": _number(doc["event_count"]),
                "heatwave_days": _number(doc["heatwave_days"]),
                "max_duration": _number(doc["max_duration"]),
                "mean_duration": _number(doc["mean_duration"]),
                "mean_intensity": _number(doc["mean_intensity"]),
                "max_exceedance": _number(doc["max_exceedance"]),
                "peak_tmax": _number(doc["peak_tmax"]),
            }
            for doc in docs
        ]
    ).set_index("year")
    frame.index.name = "year"
    return frame.loc[:, _ANNUAL_COLUMNS]


def save_analysis(
    db: Database,
    *,
    key: str,
    region: str,
    cell_ids: list[str],
    hazard: str,
    start_year: int,
    end_year: int,
    computed_for_last_full_year: int,
    result: dict,
) -> None:
    upsert_docs(
        db,
        ANALYSES,
        _ANALYSIS_KEY,
        [
            {
                "key": key,
                "region": region,
                "cell_ids": list(cell_ids),
                "hazard": hazard,
                "start_year": start_year,
                "end_year": end_year,
                "computed_for_last_full_year": computed_for_last_full_year,
                "created_at": dt.datetime.now(dt.UTC),
                "result": result,
            }
        ],
    )


def load_analysis(db: Database, key: str) -> dict | None:
    doc = db[ANALYSES].find_one({"key": key})
    if doc is None:
        return None
    return doc.get("result")


def _number(value: Any) -> float:
    return math.nan if value is None else float(value)


def _empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "start": pd.Series(dtype="datetime64[ns]"),
            "end": pd.Series(dtype="datetime64[ns]"),
            "year": pd.Series(dtype="int64"),
            "duration_days": pd.Series(dtype="int64"),
            "peak_tmax": pd.Series(dtype="float64"),
            "mean_tmax": pd.Series(dtype="float64"),
            "intensity": pd.Series(dtype="float64"),
            "max_exceedance": pd.Series(dtype="float64"),
        }
    )
