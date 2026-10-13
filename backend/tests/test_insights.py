import copy

import numpy as np
import pandas as pd
import pytest

from app.engine.events import detect_events
from app.engine.insights import DATA_SOURCE, build_insights
from app.engine.metrics import annual_metrics, region_metrics
from app.engine.thresholds import compute_thresholds
from app.engine.trends import MIN_VALID_YEARS, trend_table
from app.errors import AppError


def _region(**overrides) -> pd.DataFrame:
    index = pd.Index(range(2000, 2020), name="year")
    columns = {
        "event_count": [0.0] * 19 + [2.0],
        "heatwave_days": [1.0] * 19 + [5.0],
        "max_duration": [0.0] * 20,
        "mean_duration": [np.nan] * 20,
        "mean_intensity": [2.0] * 20,
        "max_exceedance": [0.0] * 20,
        "peak_tmax": [np.nan] * 20,
        "n_cells_valid": [1] * 20,
        "valid": [True] * 20,
    }
    columns.update(overrides)
    return pd.DataFrame(columns, index=index)


def _trend(
    evidence: str = "strong",
    direction: str = "increasing",
    slope: float = 1.2,
    first: float = 5.1,
    last: float = 7.2,
    pct: float | None = 40.4,
    n_years: int = 30,
) -> dict:
    return {
        "n_years": n_years,
        "slope_per_decade": slope,
        "p_value": 0.01,
        "evidence": evidence,
        "direction": direction,
        "first_mean": first,
        "last_mean": last,
        "pct_change": pct,
    }


def _unusable() -> dict:
    return _trend(
        evidence="insufficient",
        direction=None,
        slope=np.nan,
        first=np.nan,
        last=np.nan,
        pct=None,
    )


def _build(trends: dict, region: pd.DataFrame | None = None) -> list[dict]:
    frame = _region() if region is None else region
    return build_insights("Heatwave", "Delhi", frame, trends)


def _by_key(insights: list[dict], key: str) -> dict:
    matches = [insight for insight in insights if insight["key"] == key]
    assert len(matches) == 1
    return matches[0]


def test_strong_increasing_headline_with_percent() -> None:
    headline = _build({"heatwave_days": _trend()})[0]
    assert headline["key"] == "headline"
    assert headline["level"] == "info"
    assert "increased" in headline["text"]
    assert "40%" in headline["text"]
    assert "1.2" in headline["text"]
    assert "5.1" in headline["text"]
    assert "7.2" in headline["text"]


def test_strong_headline_without_percent_has_no_percent_sign() -> None:
    text = _build({"heatwave_days": _trend(pct=None)})[0]["text"]
    assert "1.2" in text
    assert "%" not in text
    assert "too low" in text


def test_weak_headline_is_cautionary_and_never_claims_a_trend() -> None:
    headline = _build({"heatwave_days": _trend(evidence="weak")})[0]
    assert headline["level"] == "caution"
    assert "weak" in headline["text"]
    assert "%" not in headline["text"]
    assert "significant" not in headline["text"]
    assert "trend" not in headline["text"]


def test_none_headline_reports_no_clear_trend() -> None:
    trend = _trend(evidence="none", direction="flat", slope=0.0, pct=None)
    headline = _build({"heatwave_days": trend})[0]
    assert headline["level"] == "caution"
    assert "no clear trend" in headline["text"]
    assert "%" not in headline["text"]


def test_insufficient_headline_names_the_minimum() -> None:
    trend = _trend(
        evidence="insufficient",
        direction=None,
        slope=np.nan,
        first=np.nan,
        last=np.nan,
        pct=None,
        n_years=10,
    )
    headline = _build({"heatwave_days": trend})[0]
    assert headline["level"] == "caution"
    assert "10" in headline["text"]
    assert str(MIN_VALID_YEARS) in headline["text"]


def test_decreasing_headline_has_no_double_sign() -> None:
    trend = _trend(direction="decreasing", slope=-1.2, first=7.2, last=5.1, pct=-40.4)
    text = _build({"heatwave_days": trend})[0]["text"]
    assert "decreased" in text
    assert "1.2" in text
    assert "-1.2" not in text
    assert "40%" in text
    assert "-40" not in text


def test_intensity_present_uses_degrees_and_no_percent() -> None:
    trends = {
        "heatwave_days": _trend(),
        "mean_intensity": _trend(slope=0.3, first=3.1, last=4.2, pct=None),
    }
    intensity = _by_key(_build(trends), "intensity")
    assert intensity["level"] == "info"
    assert "degrees C per decade" in intensity["text"]
    assert "0.3" in intensity["text"]
    assert "%" not in intensity["text"]


def test_intensity_absent_produces_no_intensity_insight() -> None:
    insights = _build({"heatwave_days": _trend()})
    assert all(insight["key"] != "intensity" for insight in insights)


def test_peak_year_value_and_tie_break() -> None:
    peak = _by_key(_build({"heatwave_days": _trend()}), "peak_year")
    assert "5.0" in peak["text"]
    assert "2019" in peak["text"]

    tied = _region(heatwave_days=[9.0] * 20)
    peak = _by_key(_build({"heatwave_days": _trend()}, tied), "peak_year")
    assert "2000" in peak["text"]


def test_peak_year_zero_and_all_invalid() -> None:
    zero = _region(heatwave_days=[0.0] * 20)
    peak = _by_key(_build({"heatwave_days": _trend()}, zero), "peak_year")
    assert "no Heatwave days in any valid year" in peak["text"]

    invalid = _region(valid=[False] * 20)
    assert all(i["key"] != "peak_year" for i in _build({"heatwave_days": _trend()}, invalid))


def test_data_quality_counts_and_caution_for_invalid_years() -> None:
    region = _region(valid=[True] * 18 + [False] * 2)
    quality = _by_key(_build({"heatwave_days": _trend()}, region), "data_quality")
    assert quality["level"] == "caution"
    assert "18" in quality["text"]
    assert "20" in quality["text"]
    assert DATA_SOURCE in quality["text"]


def test_data_quality_info_when_all_valid_and_cells_constant() -> None:
    quality = _by_key(_build({"heatwave_days": _trend()}), "data_quality")
    assert quality["level"] == "info"
    assert DATA_SOURCE in quality["text"]


def test_data_quality_caution_when_cell_coverage_varies() -> None:
    region = _region(n_cells_valid=[2] * 19 + [1])
    quality = _by_key(_build({"heatwave_days": _trend()}, region), "data_quality")
    assert quality["level"] == "caution"
    assert "1 of 2" in quality["text"]


def test_fixed_order_keys_equality_and_no_mutation() -> None:
    region = _region()
    trends = {"heatwave_days": _trend(), "mean_intensity": _trend(slope=0.3)}
    region_before = region.copy()
    trends_before = copy.deepcopy(trends)
    first = build_insights("Heatwave", "Delhi", region, trends)
    second = build_insights("Heatwave", "Delhi", region, trends)
    assert first == second
    keys = [insight["key"] for insight in first]
    assert keys == ["headline", "intensity", "peak_year", "data_quality"]
    assert all(list(insight.keys()) == ["key", "level", "text"] for insight in first)
    assert all(insight["level"] in ("info", "caution") for insight in first)
    assert all(insight["text"] for insight in first)
    pd.testing.assert_frame_equal(region, region_before)
    assert trends == trends_before


def test_bad_inputs_raise_app_error() -> None:
    region = _region()
    with pytest.raises(AppError) as excinfo:
        build_insights("Heatwave", "Delhi", region, {"event_count": _trend()})
    assert excinfo.value.code == "internal_error"
    with pytest.raises(AppError):
        build_insights("Heatwave", "Delhi", region, {"heatwave_days": {"evidence": "strong"}})
    with pytest.raises(AppError):
        broken = region.drop(columns="valid")
        build_insights("Heatwave", "Delhi", broken, {"heatwave_days": _trend()})
    with pytest.raises(AppError):
        build_insights("Heatwave", "Delhi", region, {"heatwave_days": "not a dict"})


def test_unknown_evidence_raises_app_error() -> None:
    with pytest.raises(AppError):
        _build({"heatwave_days": _trend(evidence="probable")})


def test_nan_in_used_trend_field_raises_but_unused_nan_is_fine() -> None:
    with pytest.raises(AppError):
        _build({"heatwave_days": _trend(slope=np.nan)})
    assert _build({"heatwave_days": _unusable()})[0]["level"] == "caution"
    nan_percent = _build({"heatwave_days": _trend(pct=np.nan)})[0]
    assert "%" not in nan_percent["text"]
    assert "too low" in nan_percent["text"]


def test_no_banned_words_in_any_branch() -> None:
    variants = [
        _trend(),
        _trend(pct=None),
        _trend(evidence="weak"),
        _trend(evidence="none", direction="flat", slope=0.0, pct=None),
        _unusable(),
    ]
    banned = ("because", "caused", "will", "significant", "climate change")
    for variant in variants:
        trends = {"heatwave_days": variant, "mean_intensity": variant}
        for insight in _build(trends):
            for word in banned:
                assert word not in insight["text"].lower()


def test_integration_with_tasks_08_to_11() -> None:
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
    assert [insight["key"] for insight in insights] == [
        "headline",
        "intensity",
        "peak_year",
        "data_quality",
    ]
    headline = insights[0]
    assert headline["level"] == "info"
    assert "increased" in headline["text"]
    assert f"{abs(trends['heatwave_days']['slope_per_decade']):.1f}" in headline["text"]
    assert trends["heatwave_days"]["evidence"] == "strong"
