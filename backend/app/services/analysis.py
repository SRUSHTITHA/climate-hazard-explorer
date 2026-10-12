import hashlib
import json
import math
from typing import Any
import pandas as pd
from pydantic import ValidationError
from app.engine.events import EventError, detect_events
from app.engine.insights import build_insights
from app.engine.metrics import MIN_CELL_FRACTION, MetricsError, annual_metrics, region_metrics
from app.engine.thresholds import (
    BASELINE_END,
    BASELINE_START,
    PERCENTILE,
    WINDOW_HALF_WIDTH,
    ThresholdError,
    compute_thresholds,
)
from app.engine.trends import rolling_mean, trend_table
from app.models.schemas import AnalysisRequest, AnalysisResponse, YearPoint
from app.services import ingestion, storage

HAZARD = "heatwave"
REGION_LABEL = "Selected region"
_TREND_COLUMNS = ("heatwave_days", "mean_intensity")
_WINDOW_DAYS = 2 * WINDOW_HALF_WIDTH + 1
_DATA_MESSAGE = "Not enough cells could be analyzed for the selected region."


class AnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def run_analysis(db: Any, request: AnalysisRequest) -> AnalysisResponse:
    current = ingestion.last_full_year()
    if request.end_year > current:
        raise AnalysisError("year_out_of_range", f"end_year must be {current} or earlier.")
    cell_ids = list(request.cell_ids)
    key = _cache_key(request.hazard, cell_ids, request.start_year, request.end_year, current)
    cached = _cached_response(db, key)
    if cached is not None:
        return cached
    usable = _load_cells(db, cell_ids)
    if len(usable) < math.ceil(MIN_CELL_FRACTION * len(cell_ids)):
        raise AnalysisError("data_unavailable", _DATA_MESSAGE)
    response = _assemble(request, usable)
    if len(usable) == len(cell_ids):
        _store(db, response, key, request, current, usable)
    return response


def get_cell_results(db: Any, cell_id: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    current = ingestion.last_full_year()
    thresholds = storage.load_thresholds(db, cell_id, HAZARD, current)
    if thresholds is not None:
        metrics = storage.load_annual_metrics(db, cell_id, HAZARD, current)
        if metrics is not None:
            return thresholds, storage.load_events(db, cell_id, HAZARD), metrics
    return _compute_cell_results(db, cell_id, current)


def _compute_cell_results(
    db: Any, cell_id: str, current: int
) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    series = storage.load_raw_series(db, cell_id, ingestion.HISTORY_START, current)
    thresholds = compute_thresholds(series)
    events = detect_events(series, thresholds)
    metrics = annual_metrics(series, events)
    storage.save_thresholds(
        db,
        cell_id=cell_id,
        hazard=HAZARD,
        values=thresholds.to_numpy(),
        baseline_start=BASELINE_START,
        baseline_end=BASELINE_END,
        window_days=_WINDOW_DAYS,
        percentile=PERCENTILE,
        computed_for_last_full_year=current,
    )
    storage.save_events(
        db, cell_id=cell_id, hazard=HAZARD, events=events, computed_for_last_full_year=current
    )
    storage.save_annual_metrics(
        db, cell_id=cell_id, hazard=HAZARD, metrics=metrics, computed_for_last_full_year=current
    )
    return thresholds, events, metrics


def _load_cells(db: Any, cell_ids: list[str]) -> list[tuple[str, tuple]]:
    usable: list[tuple[str, tuple]] = []
    for result in ingestion.ingest_region(db, cell_ids):
        if result["status"] not in ("ingested", "cached"):
            continue
        try:
            usable.append((result["cell_id"], get_cell_results(db, result["cell_id"])))
        except (ThresholdError, EventError, MetricsError, LookupError):
            continue
    return usable


def _assemble(request: AnalysisRequest, usable: list[tuple[str, tuple]]) -> AnalysisResponse:
    frames = [
        annual.loc[(annual.index >= request.start_year) & (annual.index <= request.end_year)]
        for _cell, (_thresholds, _events, annual) in usable
    ]
    region = region_metrics(frames)
    trends = trend_table(region, _TREND_COLUMNS)
    rolling = rolling_mean(region["heatwave_days"])
    return AnalysisResponse(
        hazard=request.hazard,
        cell_ids=[cell for cell, _ in usable],
        start_year=request.start_year,
        end_year=request.end_year,
        series=[_year_point(year, region, rolling) for year in region.index],
        trends=trends,
        insights=build_insights(request.hazard, REGION_LABEL, region, trends),
        quality=_quality(region, len(usable)),
    )


def _year_point(year: int, region: pd.DataFrame, rolling: pd.Series) -> YearPoint:
    row = region.loc[year]
    return YearPoint(
        year=int(year),
        valid=bool(row["valid"]),
        event_count=row["event_count"],
        heatwave_days=row["heatwave_days"],
        max_duration=row["max_duration"],
        mean_duration=row["mean_duration"],
        mean_intensity=row["mean_intensity"],
        max_exceedance=row["max_exceedance"],
        peak_tmax=row["peak_tmax"],
        n_cells_valid=int(row["n_cells_valid"]),
        rolling_heatwave_days=rolling.loc[year],
    )


def _quality(region: pd.DataFrame, cells: int) -> dict:
    return {
        "valid_years": int(region["valid"].sum()),
        "total_years": int(len(region)),
        "cells": cells,
        "min_cells_valid": int(region["n_cells_valid"].min()) if len(region) else 0,
    }


def _cached_response(db: Any, key: str) -> AnalysisResponse | None:
    result = storage.load_analysis(db, key)
    if result is None:
        return None
    try:
        return AnalysisResponse.model_validate(result)
    except ValidationError:
        return None


def _store(
    db: Any,
    response: AnalysisResponse,
    key: str,
    request: AnalysisRequest,
    current: int,
    usable: list[tuple[str, tuple]],
) -> None:
    storage.save_analysis(
        db,
        key=key,
        region=REGION_LABEL,
        cell_ids=[cell for cell, _ in usable],
        hazard=request.hazard,
        start_year=request.start_year,
        end_year=request.end_year,
        computed_for_last_full_year=current,
        result=response.model_dump(mode="json"),
    )


def _cache_key(
    hazard: str, cell_ids: list[str], start_year: int, end_year: int, last_full_year: int
) -> str:
    canonical = json.dumps(
        {
            "hazard": hazard,
            "cell_ids": sorted(cell_ids),
            "start_year": start_year,
            "end_year": end_year,
            "last_full_year": last_full_year,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
