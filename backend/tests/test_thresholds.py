import numpy as np
import pandas as pd
import pytest

from app.engine.thresholds import (
    compute_thresholds,
    leap_aligned_doy,
)
from app.errors import AppError


def _daily(start_year: int, end_year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")


def _constant(start_year: int, end_year: int, value: float = 30.0) -> pd.Series:
    index = _daily(start_year, end_year)
    return pd.Series(np.full(len(index), value), index=index, dtype="float64")


def _leap_year_index(start_year: int, end_year: int) -> pd.DatetimeIndex:
    parts = [
        _daily(year, year)
        for year in range(start_year, end_year + 1)
        if pd.Timestamp(year, 1, 1).is_leap_year
    ]
    return parts[0].append(parts[1:])


def test_threshold_error_is_an_app_error_with_code() -> None:
    with pytest.raises(AppError) as excinfo:
        compute_thresholds(_constant(2001, 2020))
    assert excinfo.value.code == "data_unavailable"


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ("2019-01-01", 1),
        ("2020-01-01", 1),
        ("2019-02-28", 59),
        ("2020-02-29", 60),
        ("2019-03-01", 61),
        ("2020-03-01", 61),
        ("2019-12-31", 366),
        ("2020-12-31", 366),
    ],
)
def test_leap_aligned_doy_single_dates(date: str, expected: int) -> None:
    result = leap_aligned_doy(pd.DatetimeIndex([date]))
    assert result.dtype == np.dtype(int) or result.dtype.kind == "i"
    assert result.tolist() == [expected]


def test_leap_aligned_doy_full_leap_year_is_1_to_366() -> None:
    result = leap_aligned_doy(_daily(2020, 2020))
    assert sorted(result.tolist()) == list(range(1, 367))


def test_leap_aligned_doy_full_non_leap_year_skips_slot_60() -> None:
    result = leap_aligned_doy(_daily(2019, 2019))
    assert 60 not in result.tolist()
    assert sorted(result.tolist()) == list(range(1, 60)) + list(range(61, 367))


def test_constant_series_gives_constant_thresholds() -> None:
    result = compute_thresholds(_constant(1991, 2020, 30.0))
    assert len(result) == 366
    assert result.name == "threshold"
    assert list(result.index) == list(range(1, 367))
    assert np.allclose(result.to_numpy(), 30.0)


def test_known_answer_percentile_and_circular_wrap() -> None:
    index = _daily(1991, 2014)
    year_values = {year: offset for offset, year in enumerate(range(1991, 2015))}
    values = np.asarray([year_values[year] for year in np.asarray(index.year)], dtype=float)
    values[np.asarray((index.month == 12) & (index.day == 31))] = 1000.0
    result = compute_thresholds(pd.Series(values, index=index))
    assert result.loc[100] == 22.0
    assert result.loc[200] == 22.0
    assert result.loc[1] == 1000.0
    assert result.loc[366] == 1000.0


def test_seasonal_sine_peaks_in_summer() -> None:
    index = _daily(1991, 2020)
    day_of_year = np.asarray(index.dayofyear)
    values = 20 + 10 * np.cos(2 * np.pi * (day_of_year - 200) / 365.0)
    result = compute_thresholds(pd.Series(values, index=index))
    assert len(result) == 366
    assert not result.isna().any()
    assert result.loc[200] > result.loc[17]
    assert 180 <= int(result.idxmax()) <= 215
    assert int(result.idxmin()) <= 40 or int(result.idxmin()) >= 340


def test_injected_nans_lower_the_pool_without_producing_nan() -> None:
    series = _constant(1991, 2020, 30.0)
    series.iloc[50:60] = np.nan
    result = compute_thresholds(series)
    assert not result.isna().any()
    assert np.allclose(result.to_numpy(), 30.0)


def test_all_nan_window_produces_nan_and_never_zero() -> None:
    index = _daily(1991, 2014)
    values = np.full(len(index), 30.0)
    aligned = leap_aligned_doy(index)
    values[(aligned >= 100) & (aligned <= 135)] = np.nan
    result = compute_thresholds(pd.Series(values, index=index))
    assert np.isnan(result.loc[117])
    assert result.loc[117] != 0.0
    assert result.loc[200] == 30.0


def test_insufficient_baseline_years_raise() -> None:
    with pytest.raises(AppError):
        compute_thresholds(_constant(2000, 2009))


def test_baseline_years_below_coverage_raise() -> None:
    index = _daily(1991, 2014)
    values = np.full(len(index), 30.0)
    for year in range(1991, 2015):
        positions = np.flatnonzero(np.asarray(index.year == year))
        values[positions[300:]] = np.nan
    with pytest.raises(AppError):
        compute_thresholds(pd.Series(values, index=index))


def test_data_outside_baseline_is_ignored() -> None:
    index = _daily(1990, 2025)
    day_of_year = np.asarray(index.dayofyear)
    values = 20 + 10 * np.cos(2 * np.pi * (day_of_year - 200) / 365.0)
    series = pd.Series(values, index=index)
    full = compute_thresholds(series)
    baseline = series[(series.index.year >= 1991) & (series.index.year <= 2020)]
    pd.testing.assert_series_equal(full, compute_thresholds(baseline))


def test_input_not_mutated_and_calls_deterministic() -> None:
    series = _constant(1991, 2020, 30.0)
    before = series.to_numpy().copy()
    first = compute_thresholds(series)
    second = compute_thresholds(series)
    assert np.array_equal(series.to_numpy(), before, equal_nan=True)
    pd.testing.assert_series_equal(first, second)


def test_non_datetime_index_rejected() -> None:
    with pytest.raises(AppError):
        compute_thresholds(pd.Series([30.0, 30.0, 30.0]))


def test_unsorted_index_rejected() -> None:
    index = pd.DatetimeIndex(["2020-01-02", "2020-01-01", "2020-01-03"])
    with pytest.raises(AppError):
        compute_thresholds(pd.Series([30.0, 30.0, 30.0], index=index))


def test_duplicate_index_rejected() -> None:
    index = pd.DatetimeIndex(["2020-01-01", "2020-01-01"])
    with pytest.raises(AppError):
        compute_thresholds(pd.Series([30.0, 30.0], index=index))


def test_all_nan_year_inside_baseline_is_ignored() -> None:
    series = _constant(1991, 2020, 30.0)
    series[np.asarray(series.index.year == 2005)] = np.nan
    result = compute_thresholds(series)
    assert not result.isna().any()
    assert np.allclose(result.to_numpy(), 30.0)


def test_series_starting_mid_baseline_raises() -> None:
    with pytest.raises(AppError):
        compute_thresholds(_constant(2000, 2020))


def test_only_leap_years_present_raises() -> None:
    index = _leap_year_index(1991, 2020)
    series = pd.Series(np.full(len(index), 30.0), index=index, dtype="float64")
    with pytest.raises(AppError):
        compute_thresholds(series)
