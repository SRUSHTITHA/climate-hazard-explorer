import json
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.engine.cleaning import (
    MIN_VALID_FRACTION,
    clean_daily,
    coverage_by_year,
    drop_unusable_years,
    quality_report,
)


def _year_index(year: int) -> pd.DatetimeIndex:
    return pd.date_range(date(year, 1, 1), date(year, 12, 31), freq="D")


def _year_series(year: int, valid_days: int) -> pd.Series:
    total = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    values = [30.0] * valid_days + [np.nan] * (total - valid_days)
    return pd.Series(values, index=_year_index(year), dtype="float64")


def _assert_plain(value: object) -> None:
    assert isinstance(value, (int, float, str, bool, list, dict))
    assert not isinstance(value, (np.integer, np.floating, np.bool_))
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            _assert_plain(item)
    elif isinstance(value, list):
        for item in value:
            _assert_plain(item)


def test_none_becomes_nan_and_skipped_date_is_missing() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02", "2024-01-04"], [10.0, None, 30.0])
    assert list(series.index) == list(pd.date_range("2024-01-01", "2024-01-04", freq="D"))
    assert np.isnan(series["2024-01-02"])
    assert np.isnan(series["2024-01-03"])
    assert series["2024-01-01"] == 10.0
    assert series["2024-01-04"] == 30.0
    report = quality_report(series)
    assert report["valid_days"] == 2
    assert report["missing_days"] == 2
    assert report["invalid_days"] == 0


def test_raises_on_empty_input() -> None:
    with pytest.raises(ValueError):
        clean_daily([], [])
    with pytest.raises(ValueError):
        clean_daily(["2024-01-01"], [])


def test_raises_on_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        clean_daily(["2024-01-01", "2024-01-02"], [1.0])


@pytest.mark.parametrize(
    "dates",
    [
        ["2024-01-01", "not-a-date"],
        [20240101, 20240102],
        [None, "2024-01-01"],
        ["", "2024-01-01"],
    ],
)
def test_raises_on_unparseable_dates(dates: list) -> None:
    with pytest.raises(ValueError):
        clean_daily(dates, [1.0, 2.0])


def test_raises_on_duplicate_dates() -> None:
    with pytest.raises(ValueError):
        clean_daily(["2024-01-01", "2024-01-01"], [1.0, 2.0])
    with pytest.raises(ValueError):
        clean_daily(["2024-01-01", "2024-1-1"], [1.0, 2.0])


def test_unsorted_dates_are_sorted() -> None:
    series = clean_daily(["2024-01-03", "2024-01-01", "2024-01-02"], [30.0, 10.0, 20.0])
    assert list(series.index) == list(pd.date_range("2024-01-01", "2024-01-03", freq="D"))
    assert series.tolist() == [10.0, 20.0, 30.0]


def test_bounds_kept_and_invalid_values_removed() -> None:
    dates = [f"2024-01-0{i}" for i in range(1, 9)]
    tmax = [60.0, -90.0, 60.1, -90.1, float("inf"), float("nan"), "abc", 104]
    series = clean_daily(dates, tmax)
    assert series.dropna().tolist() == [60.0, -90.0]
    report = quality_report(series)
    assert report["valid_days"] == 2
    assert report["invalid_days"] == 6
    assert report["missing_days"] == 0


def test_fahrenheit_style_string_removed() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02"], ["104", 30.0])
    report = quality_report(series)
    assert report["valid_days"] == 1
    assert report["invalid_days"] == 1
    assert np.isnan(series.iloc[0])


def test_constant_series_with_outlier_is_suspect_but_retained() -> None:
    days = 366
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(days)]
    tmax = [30.0] * days
    tmax[200] = 50.0
    series = clean_daily(dates, tmax)
    report = quality_report(series)
    assert report["invalid_days"] == 0
    assert report["suspect_days"] == 1
    assert series.iloc[200] == 50.0


def test_clean_daily_exposes_per_day_suspect_mask() -> None:
    days = 366
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(days)]
    tmax = [30.0] * days
    tmax[200] = 50.0
    tmax[100] = None
    tmax[300] = 200.0
    series = clean_daily(dates, tmax)
    masks = ("missing_mask", "invalid_mask", "suspect_mask")
    for name in masks:
        assert name in series.attrs
        mask = series.attrs[name]
        assert isinstance(mask, np.ndarray)
        assert mask.shape == (days,)
        assert mask.dtype == np.dtype(bool)
    assert bool(series.attrs["missing_mask"][100])
    assert bool(series.attrs["invalid_mask"][300])
    assert bool(series.attrs["suspect_mask"][200])
    assert not bool(series.attrs["missing_mask"][200])
    assert series.attrs["suspect_mask"].sum() == quality_report(series)["suspect_days"]


@pytest.mark.parametrize(
    ("year", "valid_days", "total_days", "included"),
    [
        (2021, 329, 365, True),
        (2021, 328, 365, False),
        (2024, 330, 366, True),
        (2024, 329, 366, False),
    ],
)
def test_year_coverage_threshold(
    year: int, valid_days: int, total_days: int, included: bool
) -> None:
    series = _year_series(year, valid_days)
    report = quality_report(series)
    assert report["total_days"] == total_days
    assert report["years"] == [
        {"year": year, "valid_fraction": valid_days / total_days, "included": included}
    ]
    assert report["excluded_years"] == ([] if included else [year])


def test_partial_year_is_excluded() -> None:
    series = pd.Series([30.0] * 184, index=pd.date_range("2024-07-01", "2024-12-31", freq="D"))
    coverage = coverage_by_year(series)
    assert coverage[2024] == 184 / 366
    report = quality_report(series)
    assert report["years"][0]["included"] is False
    assert report["excluded_years"] == [2024]

def test_drop_unusable_years_nulls_excluded_year_and_keeps_index() -> None:
    index = pd.date_range("2021-01-01", "2022-12-31", freq="D")
    series = pd.Series([30.0] * len(index), index=index, dtype="float64")
    series["2022-02-01":] = np.nan
    dropped = drop_unusable_years(series)
    assert dropped.index.equals(series.index)
    assert dropped["2021-01-01"] == 30.0
    assert dropped["2021-12-31"] == 30.0
    assert np.isnan(dropped["2022-01-01"])
    assert np.isnan(dropped["2022-12-31"])

def test_all_nan_series_survives() -> None:
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)]
    series = clean_daily(dates, [None] * 366)
    report = quality_report(series)
    assert report["valid_fraction"] == 0.0
    assert report["valid_days"] == 0
    assert report["missing_days"] == 366
    assert report["invalid_days"] == 0
    assert report["excluded_years"] == [2024]
    dropped = drop_unusable_years(series)
    assert dropped.isna().all()

def test_report_is_plain_python_and_json_serialisable() -> None:
    dates = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(366)]
    tmax = [30.0] * 361 + [None] * 5
    report = quality_report(clean_daily(dates, tmax))
    json.dumps(report)
    _assert_plain(report)
    assert report["min_valid_fraction"] == MIN_VALID_FRACTION
    assert report["bounds_c"] == [-90.0, 60.0]

def test_missing_invalid_and_valid_counts_partition() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02", "2024-01-04"], [10.0, "abc", None])
    report = quality_report(series)
    assert report["total_days"] == 4
    assert report["valid_days"] == 1
    assert report["missing_days"] == 2
    assert report["invalid_days"] == 1

def test_input_lists_not_mutated() -> None:
    dates = ["2024-01-03", "2024-01-01", "2024-01-02"]
    tmax = [30.0, 10.0, 20.0]
    dates_before = list(dates)
    tmax_before = list(tmax)
    clean_daily(dates, tmax)
    assert dates == dates_before
    assert tmax == tmax_before

def test_36_year_series_processes_in_well_under_one_second() -> None:
    days = 36 * 365 + 9
    start = date(1990, 1, 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    tmax = [30.0 if i % 97 else None for i in range(days)]
    started = time.perf_counter()
    series = clean_daily(dates, tmax)
    report = quality_report(series)
    elapsed = time.perf_counter() - started
    assert len(series) == days
    assert report["total_days"] == days
    assert elapsed < 1.0

def test_single_day_input() -> None:
    series = clean_daily(["2024-06-01"], [40.0])
    assert len(series) == 1
    assert series.iloc[0] == 40.0
    report = quality_report(series)
    assert report["total_days"] == 1
    assert report["valid_fraction"] == 1.0

def test_series_entirely_within_leap_day() -> None:
    series = clean_daily(["2024-02-29"], [-5.0])
    assert len(series) == 1
    assert series.iloc[0] == -5.0

def test_mixed_int_and_float_values() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02"], [30, 30.5])
    assert series.tolist() == [30.0, 30.5]

def test_dates_in_different_formats() -> None:
    series = clean_daily(["2024-01-01", "2024/02/05", "2024-03-05"], [10.0, 20.0, 30.0])
    assert list(series.index) == list(pd.date_range("2024-01-01", "2024-03-05", freq="D"))
    assert series["2024-01-01"] == 10.0
    assert series["2024-02-05"] == 20.0
    assert series["2024-03-05"] == 30.0

def test_booleans_are_invalid() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02"], [True, 30.0])
    report = quality_report(series)
    assert report["valid_days"] == 1
    assert report["invalid_days"] == 1
    assert np.isnan(series.iloc[0])

def test_huge_integer_is_invalid_not_a_crash() -> None:
    series = clean_daily(["2024-01-01", "2024-01-02"], [10**400, 30.0])
    report = quality_report(series)
    assert report["valid_days"] == 1
    assert report["invalid_days"] == 1
    assert np.isnan(series.iloc[0])
