import json
from typing import Annotated

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI, Query
from pydantic import ValidationError

from app.engine.events import detect_events
from app.engine.insights import build_insights
from app.engine.metrics import annual_metrics, region_metrics
from app.engine.thresholds import compute_thresholds
from app.engine.trends import rolling_mean, trend_table
from app.errors import AppError
from app.models.schemas import (
    MAX_SERIES_YEARS,
    AnalysisRequest,
    AnalysisResponse,
    ErrorResponse,
    InsightOut,
    QualityOut,
    TrendOut,
    YearPoint,
)
from app.services.ingestion import HISTORY_START
from app.services.open_meteo import UPSTREAM_ERROR_MESSAGE
from app.services.regions import cell_id, cells_in_box


def _point(**over: object) -> AnalysisRequest:
    fields: dict[str, object] = {
        "lat": 28.6,
        "lon": 77.2,
        "start_year": 2000,
        "end_year": 2019,
    }
    fields.update(over)
    return AnalysisRequest(**fields)


def _box(**over: object) -> AnalysisRequest:
    fields: dict[str, object] = {
        "south": 28.0,
        "west": 77.0,
        "north": 28.5,
        "east": 77.5,
        "start_year": 2000,
        "end_year": 2019,
    }
    fields.update(over)
    return AnalysisRequest(**fields)


def _year_point(year: int, row: pd.Series, rolling: pd.Series) -> YearPoint:
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


def _pipeline() -> tuple[pd.DataFrame, dict, list[dict]]:
    index = pd.date_range("1990-01-01", "2025-12-31", freq="D")
    doy = np.asarray(index.dayofyear)
    series = pd.Series(30.0 + 8.0 * np.sin(2.0 * np.pi * (doy - 105.0) / 366.0), index=index)
    threshold = compute_thresholds(series)
    spiked = series.copy()
    for year in range(1990, 2026):
        for k in range((year - 1990) // 6):
            start = pd.Timestamp(f"{year}-07-01") + pd.Timedelta(days=8 * k)
            spiked.loc[start : start + pd.Timedelta(days=4)] = 45.0
    events = detect_events(spiked, threshold)
    region = region_metrics([annual_metrics(spiked, events)])
    trends = trend_table(region, ("heatwave_days", "mean_intensity"))
    insights = build_insights("Heatwave", "Test region", region, trends)
    return region, trends, insights


def test_point_request_parses_with_defaults() -> None:
    request = _point()
    assert request.hazard == "heatwave"
    assert request.cell_ids == [cell_id(28.6, 77.2)]


def test_box_request_parses() -> None:
    request = _box()
    assert request.hazard == "heatwave"
    assert request.cell_ids == cells_in_box(28.0, 77.0, 28.5, 77.5)
    assert len(request.cell_ids) == 9


def test_span_boundary_and_year_rules() -> None:
    AnalysisRequest(lat=28.6, lon=77.2, start_year=2000, end_year=2009)
    with pytest.raises(ValidationError):
        AnalysisRequest(lat=28.6, lon=77.2, start_year=2000, end_year=2008)
    with pytest.raises(ValidationError):
        AnalysisRequest(lat=28.6, lon=77.2, start_year=HISTORY_START - 1, end_year=2020)
    with pytest.raises(ValidationError):
        AnalysisRequest(lat=28.6, lon=77.2, start_year=2005, end_year=2000)


def test_region_shape_combinations_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalysisRequest(
            lat=28.6,
            lon=77.2,
            south=28.0,
            west=77.0,
            north=28.5,
            east=77.5,
            start_year=2000,
            end_year=2019,
        )
    with pytest.raises(ValidationError):
        AnalysisRequest(start_year=2000, end_year=2019)
    with pytest.raises(ValidationError):
        AnalysisRequest(south=28.0, west=77.0, north=28.5, start_year=2000, end_year=2019)
    with pytest.raises(ValidationError):
        _point(lon=None)


def test_coordinate_bounds_and_box_ordering_rejected() -> None:
    with pytest.raises(ValidationError):
        _point(lat=91.0)
    with pytest.raises(ValidationError):
        _point(lon=181.0)
    with pytest.raises(ValidationError):
        _box(south=28.5, north=28.5)
    with pytest.raises(ValidationError):
        _box(west=77.5, east=77.5)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), "abc", None])
def test_bad_coordinate_values_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        _point(lat=value)


def test_numeric_strings_coerce_for_query_parsing() -> None:
    request = AnalysisRequest(lat="28.6", lon="77.2", start_year="2000", end_year="2019")
    assert request.cell_ids == [cell_id(28.6, 77.2)]


def test_too_many_cells_rejected_exactly_nine_accepted() -> None:
    with pytest.raises(ValidationError):
        _box(south=0.0, west=0.0, north=10.0, east=10.0)
    edge = _box(south=89.5, west=179.5, north=90.0, east=180.0)
    assert len(edge.cell_ids) == 9
    assert edge.cell_ids == cells_in_box(89.5, 179.5, 90.0, 180.0)
    assert "90.00_180.00" in edge.cell_ids


def test_unknown_hazard_extra_field_and_injection_rejected() -> None:
    with pytest.raises(ValidationError):
        _point(hazard="flood")
    with pytest.raises(ValidationError):
        _point(evil="x")
    with pytest.raises(ValidationError):
        _point(lat={"$ne": None})
    with pytest.raises(ValidationError):
        _point(lat="$ne")


def test_query_model_serves_over_http() -> None:
    app = FastAPI()

    @app.get("/analysis")
    def analysis(item: Annotated[AnalysisRequest, Query()]) -> dict:
        return {"cells": item.cell_ids}

    from fastapi.testclient import TestClient

    client = TestClient(app)
    ok = client.get(
        "/analysis",
        params={"lat": 28.6, "lon": 77.2, "start_year": 2000, "end_year": 2019},
    )
    assert ok.status_code == 200
    bad = client.get(
        "/analysis",
        params={"lat": "abc", "lon": 77.2, "start_year": 2000, "end_year": 2019},
    )
    assert bad.status_code == 422


def test_response_models_generate_openapi() -> None:
    app = FastAPI()

    @app.get("/analysis", response_model=AnalysisResponse)
    def analysis() -> AnalysisResponse:
        raise NotImplementedError

    @app.get("/error", response_model=ErrorResponse)
    def error() -> ErrorResponse:
        raise NotImplementedError

    schemas = app.openapi()["components"]["schemas"]
    assert "AnalysisResponse" in schemas
    assert "ErrorResponse" in schemas


def test_analysis_response_round_trips_strict_json() -> None:
    region, trends, insights = _pipeline()
    rolling = rolling_mean(region["heatwave_days"])
    series = [_year_point(year, row, rolling) for year, row in region.iterrows()]
    request = _point(start_year=1990, end_year=2025)
    response = AnalysisResponse(
        hazard="heatwave",
        cell_ids=request.cell_ids,
        start_year=1990,
        end_year=2025,
        series=series,
        trends=trends,
        insights=insights,
        events=[],
        quality=QualityOut(
            valid_years=int(region["valid"].sum()),
            total_years=len(region),
            cells=1,
            min_cells_valid=int(region["n_cells_valid"].min()),
            events_total=0,
        ),
    )
    dumped = response.model_dump(mode="json")
    assert json.dumps(dumped, allow_nan=False)
    assert dumped["attribution"] == "Data: ERA5 reanalysis via Open-Meteo"
    assert len(dumped["series"]) == len(region)


def test_analysis_response_matches_engine_outputs() -> None:
    region, trends, insights = _pipeline()
    rolling = rolling_mean(region["heatwave_days"])
    series = [_year_point(year, row, rolling) for year, row in region.iterrows()]
    response = AnalysisResponse(
        hazard="heatwave",
        cell_ids=["28.50_77.25"],
        start_year=1990,
        end_year=2025,
        series=series,
        trends=trends,
        insights=insights,
        events=[],
        quality=QualityOut(
            valid_years=int(region["valid"].sum()),
            total_years=len(region),
            cells=1,
            min_cells_valid=int(region["n_cells_valid"].min()),
            events_total=0,
        ),
    )
    engine_trend = trends["heatwave_days"]
    out_trend = response.trends["heatwave_days"]
    assert out_trend.n_years == engine_trend["n_years"]
    assert out_trend.slope_per_decade == engine_trend["slope_per_decade"]
    assert out_trend.evidence == engine_trend["evidence"]
    assert [insight.model_dump() for insight in response.insights] == insights


def test_nan_metric_becomes_null() -> None:
    point = YearPoint(year=2000, valid=True, n_cells_valid=1, heatwave_days=float("nan"))
    assert point.heatwave_days is None
    trend = TrendOut(n_years=0, evidence="insufficient", slope_per_decade=float("inf"))
    assert trend.slope_per_decade is None
    payload = json.dumps(
        {"point": point.model_dump(mode="json"), "trend": trend.model_dump(mode="json")},
        allow_nan=False,
    )
    assert "NaN" not in payload and "Infinity" not in payload


def _nan_point() -> YearPoint:
    nan = float("nan")
    return YearPoint(
        year=2000,
        valid=True,
        event_count=nan,
        heatwave_days=nan,
        max_duration=nan,
        mean_duration=nan,
        mean_intensity=nan,
        max_exceedance=nan,
        peak_tmax=nan,
        n_cells_valid=1,
        rolling_heatwave_days=nan,
    )


def _nan_trend() -> TrendOut:
    nan = float("nan")
    return TrendOut(
        n_years=0,
        slope_per_decade=nan,
        p_value=nan,
        evidence="insufficient",
        direction=None,
        first_mean=nan,
        last_mean=nan,
        pct_change=nan,
    )


def test_response_nan_in_every_float_field() -> None:
    point = _nan_point()
    trend = _nan_trend()
    response = AnalysisResponse(
        hazard="heatwave",
        cell_ids=["28.50_77.25"],
        start_year=2000,
        end_year=2000,
        series=[point],
        trends={"heatwave_days": trend},
        insights=[],
        events=[],
        quality=QualityOut(
            valid_years=1, total_years=1, cells=1, min_cells_valid=1, events_total=0
        ),
    )
    dumped = json.dumps(response.model_dump(mode="json"), allow_nan=False)
    assert "null" in dumped
    assert point.heatwave_days is None
    assert point.rolling_heatwave_days is None
    assert trend.pct_change is None


def test_literal_and_list_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        TrendOut(n_years=1, evidence="likely")
    with pytest.raises(ValidationError):
        InsightOut(key="k", level="warning", text="x")
    too_many_years = [
        {"year": 2000 + offset, "valid": True, "n_cells_valid": 1}
        for offset in range(MAX_SERIES_YEARS + 1)
    ]
    base = {
        "hazard": "heatwave",
        "start_year": 2000,
        "end_year": 2019,
        "insights": [],
        "events": [],
        "quality": {
            "valid_years": 1,
            "total_years": 1,
            "cells": 1,
            "min_cells_valid": 1,
            "events_total": 0,
        },
    }
    with pytest.raises(ValidationError):
        AnalysisResponse(cell_ids=["28.50_77.25"], series=too_many_years, trends={}, **base)
    with pytest.raises(ValidationError):
        AnalysisResponse(cell_ids=["c"] * 10, series=[], trends={}, **base)
    with pytest.raises(ValidationError):
        AnalysisResponse(cell_ids=["28.50_77.25"], series=[], trends={"bogus": {}}, **base)


def test_oversized_strings_rejected() -> None:
    huge = "a" * 10000
    with pytest.raises(ValidationError):
        ErrorResponse(code="analysis_error", message=huge)
    with pytest.raises(ValidationError):
        InsightOut(key="headline", level="info", text=huge)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            AppError("invalid_region", "The request parameters are invalid.", status=400),
            "invalid_region",
        ),
        (AppError("upstream_error", UPSTREAM_ERROR_MESSAGE, status=502), "upstream_error"),
        (
            AppError(
                "data_unavailable",
                "Not enough data is available to compute the analysis.",
                status=502,
            ),
            "data_unavailable",
        ),
        (
            AppError(
                "internal_error",
                "An internal error occurred while computing the analysis.",
                status=500,
            ),
            "internal_error",
        ),
    ],
)
def test_error_response_message_is_safe(error: AppError, expected_code: str) -> None:
    assert error.code == expected_code
    response = ErrorResponse(code="analysis_error", message=str(error))
    lowered = response.message.lower()
    assert "http" not in lowered
    assert "mongodb" not in lowered
    assert "/" not in response.message
    assert "\\" not in response.message


def test_error_response_rejects_unsafe_message() -> None:
    with pytest.raises(ValidationError):
        ErrorResponse(code="analysis_error", message="call https://example.com now")
    with pytest.raises(ValidationError):
        ErrorResponse(code="analysis_error", message="see mongodb://localhost")
    with pytest.raises(ValidationError):
        ErrorResponse(code="analysis_error", message="path\\to\\secret")
    with pytest.raises(ValidationError):
        ErrorResponse(code="Bad Code", message="ok")
