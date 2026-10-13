import numpy as np
import pandas as pd
import pytest

from app.engine.events import detect_events
from app.engine.thresholds import DOY_COUNT, compute_thresholds
from app.errors import AppError


def _thresholds(overrides: dict[int, float] | None = None, default: float = 30.0) -> pd.Series:
    values = np.full(DOY_COUNT, default)
    for doy, value in (overrides or {}).items():
        values[doy - 1] = value
    return pd.Series(values, index=np.arange(1, DOY_COUNT + 1))


def _daily(values: list[float], start: str = "2020-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=index, dtype="float64")


def test_event_error_is_an_app_error_with_code() -> None:
    with pytest.raises(AppError) as excinfo:
        detect_events(pd.Series([31.0]), _thresholds())
    assert excinfo.value.code == "internal_error"


def test_two_exceeding_days_is_not_an_event() -> None:
    assert detect_events(_daily([31.0, 31.0]), _thresholds()).empty


def test_three_exceeding_days_is_one_event() -> None:
    events = detect_events(_daily([31.0, 31.0, 31.0]), _thresholds())
    assert len(events) == 1
    assert events.loc[0, "start"] == pd.Timestamp("2020-01-01")
    assert events.loc[0, "end"] == pd.Timestamp("2020-01-03")
    assert events.loc[0, "duration_days"] == 3


def test_strict_inequality_splits_at_a_day_equal_to_threshold() -> None:
    assert detect_events(_daily([31.0, 31.0, 30.0, 31.0, 31.0]), _thresholds()).empty
    events = detect_events(_daily([31.0, 31.0, 31.0, 30.0, 31.0, 31.0, 31.0]), _thresholds())
    assert len(events) == 2
    assert events["duration_days"].tolist() == [3, 3]


def test_nan_value_splits_a_run() -> None:
    assert detect_events(_daily([31.0, 31.0, np.nan, 31.0, 31.0]), _thresholds()).empty
    one_side = detect_events(_daily([31.0, 31.0, 31.0, np.nan, 31.0, 31.0]), _thresholds())
    assert len(one_side) == 1
    assert one_side.loc[0, "duration_days"] == 3
    both = detect_events(_daily([31.0, 31.0, 31.0, np.nan, 31.0, 31.0, 31.0]), _thresholds())
    assert both["duration_days"].tolist() == [3, 3]


def test_nan_threshold_breaks_a_run() -> None:
    events = detect_events(_daily([31.0] * 7), _thresholds({4: np.nan}))
    assert events["duration_days"].tolist() == [3, 3]


def test_year_boundary_run_is_one_event() -> None:
    index = pd.DatetimeIndex(["2019-12-30", "2019-12-31", "2020-01-01", "2020-01-02"])
    events = detect_events(pd.Series([31.0, 31.0, 31.0, 31.0], index=index), _thresholds())
    assert len(events) == 1
    assert events.loc[0, "start"] == pd.Timestamp("2019-12-30")
    assert events.loc[0, "end"] == pd.Timestamp("2020-01-02")
    assert events.loc[0, "year"] == 2019
    assert events.loc[0, "duration_days"] == 4


def test_leap_year_feb_29_uses_slot_60() -> None:
    index = pd.DatetimeIndex(["2020-02-28", "2020-02-29", "2020-03-01"])
    series = pd.Series([50.0, 50.0, 50.0], index=index)
    events = detect_events(series, _thresholds({59: 0.0, 60: 0.0, 61: 0.0}, default=1000.0))
    assert events["duration_days"].tolist() == [3]
    broken = detect_events(series, _thresholds({59: 0.0, 60: 1000.0, 61: 0.0}, default=1000.0))
    assert broken.empty


def test_non_leap_year_uses_aligned_slots() -> None:
    index = pd.DatetimeIndex(["2019-02-28", "2019-03-01", "2019-03-02"])
    series = pd.Series([50.0, 50.0, 50.0], index=index)
    overrides = {59: 0.0, 60: 1000.0, 61: 0.0, 62: 0.0}
    events = detect_events(series, _thresholds(overrides, default=1000.0))
    assert events["duration_days"].tolist() == [3]


def test_run_at_start_and_end_of_series_is_detected() -> None:
    values = [31.0, 31.0, 31.0, 10.0, 10.0, 10.0, 10.0, 31.0, 31.0, 31.0]
    events = detect_events(_daily(values), _thresholds())
    assert events["duration_days"].tolist() == [3, 3]
    assert events.loc[0, "start"] == pd.Timestamp("2020-01-01")
    assert events.loc[1, "start"] == pd.Timestamp("2020-01-08")


def test_missing_date_breaks_a_run() -> None:
    index = pd.DatetimeIndex(
        ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-05", "2020-01-06", "2020-01-07"]
    )
    events = detect_events(pd.Series([31.0] * 6, index=index), _thresholds())
    assert events["duration_days"].tolist() == [3, 3]
    assert events.loc[0, "end"] == pd.Timestamp("2020-01-03")
    assert events.loc[1, "start"] == pd.Timestamp("2020-01-05")


def test_event_statistics_are_hand_computed() -> None:
    events = detect_events(_daily([32.0, 34.0, 36.0, 33.0]), _thresholds(default=30.0))
    row = events.iloc[0]
    assert row["start"] == pd.Timestamp("2020-01-01")
    assert row["end"] == pd.Timestamp("2020-01-04")
    assert row["year"] == 2020
    assert row["duration_days"] == 4
    assert row["peak_tmax"] == 36.0
    assert row["mean_tmax"] == 33.75
    assert row["intensity"] == 3.75
    assert row["max_exceedance"] == 6.0


def test_output_is_sorted_by_start() -> None:
    values = [31.0, 31.0, 31.0, 10.0, 31.0, 31.0, 31.0, 10.0, 31.0, 31.0, 31.0]
    events = detect_events(_daily(values), _thresholds())
    assert events["start"].is_monotonic_increasing
    assert list(events.index) == [0, 1, 2]


def test_empty_result_has_expected_columns_and_dtypes() -> None:
    empty = detect_events(_daily([10.0, 10.0, 10.0]), _thresholds())
    populated = detect_events(_daily([31.0, 31.0, 31.0]), _thresholds())
    assert empty.empty
    assert list(empty.columns) == [
        "start",
        "end",
        "year",
        "duration_days",
        "peak_tmax",
        "mean_tmax",
        "intensity",
        "max_exceedance",
    ]
    assert dict(empty.dtypes) == dict(populated.dtypes)


def test_inputs_not_mutated_and_calls_equal() -> None:
    series = _daily([31.0, 31.0, 31.0])
    thresholds = _thresholds()
    series_before = series.to_numpy().copy()
    thresholds_before = thresholds.to_numpy().copy()
    first = detect_events(series, thresholds)
    second = detect_events(series, thresholds)
    assert np.array_equal(series.to_numpy(), series_before)
    assert np.array_equal(thresholds.to_numpy(), thresholds_before)
    pd.testing.assert_frame_equal(first, second)


def test_non_datetime_index_raises() -> None:
    with pytest.raises(AppError):
        detect_events(pd.Series([31.0, 31.0, 31.0]), _thresholds())


def test_unsorted_index_raises() -> None:
    index = pd.DatetimeIndex(["2020-01-02", "2020-01-01", "2020-01-03"])
    with pytest.raises(AppError):
        detect_events(pd.Series([31.0, 31.0, 31.0], index=index), _thresholds())


def test_duplicate_index_raises() -> None:
    index = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])
    with pytest.raises(AppError):
        detect_events(pd.Series([31.0, 31.0, 31.0], index=index), _thresholds())


def test_thresholds_wrong_length_raises() -> None:
    with pytest.raises(AppError):
        detect_events(_daily([31.0]), pd.Series(np.zeros(365), index=np.arange(1, 366)))


def test_thresholds_wrong_index_raises() -> None:
    with pytest.raises(AppError):
        detect_events(_daily([31.0]), pd.Series(np.zeros(DOY_COUNT), index=np.arange(DOY_COUNT)))


def test_all_nan_series_has_no_events() -> None:
    assert detect_events(_daily([np.nan] * 20), _thresholds()).empty


def test_every_day_exceeding_is_one_event() -> None:
    events = detect_events(_daily([31.0] * 25), _thresholds())
    assert len(events) == 1
    assert events.loc[0, "duration_days"] == 25


def test_integration_with_compute_thresholds() -> None:
    index = pd.date_range("1990-01-01", "2025-12-31", freq="D")
    day_of_year = np.asarray(index.dayofyear)
    values = 20 + 10 * np.cos(2 * np.pi * (day_of_year - 200) / 365.0)
    series = pd.Series(values, index=index, dtype="float64")
    thresholds = compute_thresholds(series)
    assert detect_events(series, thresholds).empty
    spike = pd.date_range("2025-07-01", "2025-07-05", freq="D")
    spiked = series.copy()
    spiked.loc[spike] = spiked.loc[spike] + 25.0
    events = detect_events(spiked, thresholds)
    assert len(events) == 1
    assert events.loc[0, "start"] == spike[0]
    assert events.loc[0, "end"] == spike[-1]
    assert events.loc[0, "duration_days"] == 5
    assert events.loc[0, "year"] == 2025
