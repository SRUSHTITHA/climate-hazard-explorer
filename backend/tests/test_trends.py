import types

import numpy as np
import pandas as pd
import pytest
from scipy.stats import theilslopes

from app.engine import trends
from app.engine.events import detect_events
from app.engine.metrics import annual_metrics
from app.engine.thresholds import compute_thresholds
from app.engine.trends import rolling_mean, trend, trend_table
from app.errors import AppError


def _series(values, start: int = 1990, name=None) -> pd.Series:
    index = pd.Index(range(start, start + len(values)), name="year")
    return pd.Series(np.asarray(values, dtype=float), index=index, name=name)


def _linear(
    count: int = 30, start: int = 1990, base: float = 5.0, step: float = 0.1, name=None
) -> pd.Series:
    return _series([base + step * i for i in range(count)], start=start, name=name)


def test_linear_series_is_strong_increasing() -> None:
    result = trend(_linear(30))
    assert result["n_years"] == 30
    assert result["slope_per_decade"] == pytest.approx(1.0)
    assert result["p_value"] < 0.05
    assert result["evidence"] == "strong"
    assert result["direction"] == "increasing"
    assert result["first_mean"] == pytest.approx(5.2)
    assert result["last_mean"] == pytest.approx(7.7)
    assert result["pct_change"] == pytest.approx(2.5 / 5.2 * 100.0)


def test_slope_matches_scipy_theilslopes_on_real_years() -> None:
    series = _linear(30)
    result = trend(series)
    x = series.index.to_numpy(dtype=float)
    y = series.to_numpy(dtype=float)
    assert result["slope_per_decade"] == pytest.approx(theilslopes(y, x).slope * 10.0)


def test_flat_series_is_flat_with_no_evidence() -> None:
    result = trend(_series([10.0] * 30))
    assert result["slope_per_decade"] == 0.0
    assert result["p_value"] == 1.0
    assert result["evidence"] == "none"
    assert result["direction"] == "flat"
    assert result["pct_change"] == pytest.approx(0.0)


def test_decreasing_series_direction() -> None:
    result = trend(_series([30.0 - 0.2 * i for i in range(30)]))
    assert result["slope_per_decade"] == pytest.approx(-2.0)
    assert result["evidence"] == "strong"
    assert result["direction"] == "decreasing"


def test_fourteen_valid_years_is_insufficient() -> None:
    result = trend(_linear(14))
    assert result["n_years"] == 14
    assert result["evidence"] == "insufficient"
    assert result["direction"] is None
    assert result["pct_change"] is None
    assert np.isnan(result["slope_per_decade"])
    assert np.isnan(result["p_value"])


def test_fifteen_valid_years_is_fitted() -> None:
    result = trend(_linear(15))
    assert result["n_years"] == 15
    assert result["evidence"] == "strong"
    assert not np.isnan(result["slope_per_decade"])
    assert not np.isnan(result["p_value"])


def test_nan_years_are_dropped_before_fitting() -> None:
    values = [5.0 + 0.1 * i for i in range(20)]
    for position in (2, 7, 11, 13, 17, 19):
        values[position] = np.nan
    result = trend(_series(values))
    assert result["n_years"] == 14
    assert result["evidence"] == "insufficient"


def test_p_value_at_strong_boundary_is_weak(monkeypatch) -> None:
    monkeypatch.setattr(trends.mk, "original_test", lambda values: types.SimpleNamespace(p=0.05))
    result = trend(_linear(30))
    assert result["evidence"] == "weak"
    assert result["direction"] == "increasing"


def test_p_value_at_weak_boundary_is_none(monkeypatch) -> None:
    monkeypatch.setattr(trends.mk, "original_test", lambda values: types.SimpleNamespace(p=0.15))
    result = trend(_linear(30))
    assert result["evidence"] == "none"
    assert result["direction"] == "flat"


def test_pct_change_is_none_below_one_day_base() -> None:
    result = trend(_linear(30, base=0.5))
    assert result["first_mean"] < 1.0
    assert result["pct_change"] is None


def test_pct_change_with_zero_base_does_not_divide() -> None:
    result = trend(_linear(30, base=0.0, step=0.0))
    assert result["first_mean"] == 0.0
    assert result["pct_change"] is None


def test_non_contiguous_years_use_real_year_values() -> None:
    index = pd.Index(list(range(1990, 1998)) + list(range(2003, 2011)), name="year")
    values = np.array([0.0] * 8 + [1.0] * 8)
    result = trend(pd.Series(values, index=index))
    expected = theilslopes(values, index.to_numpy(dtype=float)).slope * 10.0
    positional = theilslopes(values, np.arange(len(values))).slope * 10.0
    assert result["slope_per_decade"] == pytest.approx(expected)
    assert result["slope_per_decade"] != pytest.approx(positional)


def test_theil_sen_ignores_a_single_extreme_outlier() -> None:
    result = trend(_series([5.0] * 29 + [1000.0]))
    assert result["slope_per_decade"] == 0.0


def test_fifteen_identical_years_fit_flat() -> None:
    result = trend(_series([7.0] * 15))
    assert result["slope_per_decade"] == 0.0
    assert result["p_value"] == 1.0
    assert result["evidence"] == "none"
    assert result["direction"] == "flat"


def test_all_nan_series_is_insufficient() -> None:
    result = trend(_series([np.nan] * 30))
    assert result["n_years"] == 0
    assert result["evidence"] == "insufficient"
    assert result["direction"] is None
    assert result["pct_change"] is None
    assert rolling_mean(_series([np.nan] * 30)).isna().all()


def test_rolling_mean_centered_hand_computed() -> None:
    result = rolling_mean(_series(list(range(1, 12)), start=2000))
    assert result.loc[2000] == pytest.approx(2.0)
    assert result.loc[2001] == pytest.approx(2.5)
    assert result.loc[2002] == pytest.approx(3.0)
    assert result.loc[2005] == pytest.approx(6.0)
    assert result.loc[2009] == pytest.approx(9.5)
    assert result.loc[2010] == pytest.approx(10.0)


def test_rolling_mean_ignores_nan_not_zero_filled() -> None:
    values = [np.nan, np.nan, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    result = rolling_mean(_series(values, start=2000))
    assert np.isnan(result.loc[2000])
    assert np.isnan(result.loc[2001])
    assert result.loc[2002] == pytest.approx(4.0)


def test_rolling_mean_sparse_windows_are_nan_under_min_periods() -> None:
    result = rolling_mean(_series([1.0, 2.0], start=2000))
    assert result.isna().all()


def test_rolling_mean_preserves_index_and_name_without_mutating() -> None:
    series = _linear(30, name="heatwave_days")
    before = series.copy()
    result = rolling_mean(series)
    assert result.index.equals(series.index)
    assert result.name == "heatwave_days"
    assert result.dtype == np.float64
    pd.testing.assert_series_equal(series, before)


def test_functions_do_not_mutate_input() -> None:
    series = _linear(30)
    before = series.copy()
    trend(series)
    pd.testing.assert_series_equal(series, before)


def test_trend_table_excludes_invalid_years() -> None:
    index = pd.Index(range(2000, 2020), name="year")
    frame = pd.DataFrame(
        {"heatwave_days": [1.0] * 10 + [99.0] * 10, "valid": [True] * 10 + [False] * 10},
        index=index,
    )
    table = trend_table(frame, ("heatwave_days",))
    assert table["heatwave_days"]["n_years"] == 10


def test_trend_table_keeps_zero_counts_and_drops_nan_intensity() -> None:
    index = pd.Index(range(2000, 2020), name="year")
    frame = pd.DataFrame(
        {
            "event_count": [0.0] * 19 + [2.0],
            "mean_intensity": [np.nan] * 19 + [3.0],
            "valid": [True] * 20,
        },
        index=index,
    )
    table = trend_table(frame, ("event_count", "mean_intensity"))
    assert table["event_count"]["n_years"] == 20
    assert table["mean_intensity"]["n_years"] == 1


def test_trend_table_rejects_missing_columns() -> None:
    index = pd.Index([2000, 2001], name="year")
    frame = pd.DataFrame({"heatwave_days": [1.0, 2.0], "valid": [True, True]}, index=index)
    with pytest.raises(AppError):
        trend_table(frame, ("event_count",))
    with pytest.raises(AppError):
        trend_table(frame.drop(columns="valid"), ("heatwave_days",))


def test_bad_inputs_raise_app_error() -> None:
    with pytest.raises(AppError) as excinfo:
        trend("not a series")
    assert excinfo.value.code == "internal_error"
    with pytest.raises(AppError):
        trend(pd.Series([1.0, 2.0], index=pd.Index(["a", "b"])))
    with pytest.raises(AppError):
        trend(pd.Series(["a", "b"], index=pd.Index([2000, 2001])))
    with pytest.raises(AppError):
        trend(pd.Series([1.0, 2.0], index=pd.Index([2000.0, 2001.0])))
    with pytest.raises(AppError):
        trend(pd.Series([1.0, 2.0], index=pd.Index([2000, 2000])))
    with pytest.raises(AppError):
        trend(_series([1.0, np.inf, 3.0]))
    with pytest.raises(AppError):
        trend(pd.Series([1.0, 2.0], index=pd.Index([2001, 2000])))
    with pytest.raises(AppError):
        rolling_mean(_series([1.0, np.inf, 3.0]))


def test_integration_increasing_heatwave_frequency() -> None:
    index = pd.date_range("1990-01-01", "2025-12-31", freq="D")
    doy = np.asarray(index.dayofyear)
    series = pd.Series(30.0 + 8.0 * np.sin(2.0 * np.pi * (doy - 105.0) / 366.0), index=index)
    threshold = compute_thresholds(series)
    spiked = series.copy()
    for year in range(1990, 2026):
        for k in range((year - 1990) // 6):
            start = pd.Timestamp(f"{year}-07-01") + pd.Timedelta(days=8 * k)
            spiked.loc[start : start + pd.Timedelta(days=4)] = 45.0
    metrics = annual_metrics(spiked, detect_events(spiked, threshold))
    assert metrics["valid"].all()
    result = trend_table(metrics, ("heatwave_days",))["heatwave_days"]
    assert result["n_years"] == 36
    assert result["direction"] == "increasing"
    assert result["evidence"] == "strong"
    assert result["slope_per_decade"] > 0.0
