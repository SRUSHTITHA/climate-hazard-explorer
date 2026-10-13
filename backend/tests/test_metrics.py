import numpy as np
import pandas as pd
import pytest

from app.engine.cleaning import MIN_VALID_FRACTION
from app.engine.events import detect_events
from app.engine.metrics import annual_metrics, region_metrics
from app.engine.thresholds import compute_thresholds
from app.errors import AppError


def _daily(start_year: int, end_year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")


def _constant(start_year: int, end_year: int, value: float = 30.0) -> pd.Series:
    index = _daily(start_year, end_year)
    return pd.Series(np.full(len(index), value), index=index, dtype="float64")


def _seasonal(start_year: int, end_year: int) -> pd.Series:
    index = _daily(start_year, end_year)
    doy = np.asarray(index.dayofyear)
    return pd.Series(30.0 + 8.0 * np.sin(2.0 * np.pi * (doy - 105.0) / 366.0), index=index)


def _as_na(series: pd.Series, year: int, n: int) -> pd.Series:
    result = series.copy()
    positions = np.flatnonzero(result.index.year == year)
    result.iloc[positions[:n]] = np.nan
    return result


def _event(
    start_date,
    duration: int,
    intensity: float,
    max_exceedance: float,
    peak_tmax: float,
    end_date=None,
) -> dict:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) if end_date else start + pd.Timedelta(days=duration - 1)
    return {
        "start": start,
        "end": end,
        "year": start.year,
        "duration_days": duration,
        "peak_tmax": float(peak_tmax),
        "mean_tmax": float(peak_tmax - intensity),
        "intensity": float(intensity),
        "max_exceedance": float(max_exceedance),
    }


def _events(*rows: dict) -> pd.DataFrame:
    return (
        pd.DataFrame(list(rows))
        if rows
        else pd.DataFrame(
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
    )


_METRIC_COLUMNS = [
    "event_count",
    "heatwave_days",
    "max_duration",
    "mean_duration",
    "mean_intensity",
    "max_exceedance",
    "peak_tmax",
]


def test_metrics_error_is_an_app_error_with_code() -> None:
    with pytest.raises(AppError) as excinfo:
        region_metrics([])
    assert excinfo.value.code == "data_unavailable"


def test_year_with_three_events_hand_computed() -> None:
    events = _events(
        _event("2000-06-01", 3, 4.0, 6.0, 38.0),
        _event("2000-07-10", 2, 2.0, 2.5, 35.0),
        _event("2000-08-01", 5, 6.0, 7.0, 40.0),
    )
    result = annual_metrics(_constant(2000, 2000), events)
    row = result.loc[2000]
    assert row["valid_days"] == 366 and row["total_days"] == 366 and row["valid"]
    assert row["event_count"] == 3
    assert row["heatwave_days"] == 10
    assert row["max_duration"] == 5
    assert row["mean_duration"] == pytest.approx(10 / 3)
    assert row["mean_intensity"] == pytest.approx(46 / 10)
    assert row["max_exceedance"] == pytest.approx(7.0)
    assert row["peak_tmax"] == pytest.approx(40.0)


def test_valid_year_with_no_events_is_zero_counts_and_nan_metrics() -> None:
    result = annual_metrics(_constant(2001, 2001), _events())
    row = result.loc[2001]
    assert row["valid"] and row["total_days"] == 365 and row["valid_days"] == 365
    assert row["event_count"] == 0
    assert row["heatwave_days"] == 0
    for column in [
        "max_duration",
        "mean_duration",
        "mean_intensity",
        "max_exceedance",
        "peak_tmax",
    ]:
        assert np.isnan(row[column])


def test_boundary_90_percent_leap_year_lengths() -> None:
    leap_valid = _as_na(_constant(2000, 2001), 2000, 36)
    leap_invalid = _as_na(_constant(2000, 2001), 2000, 37)
    assert annual_metrics(leap_valid, _events()).loc[2000, "valid"]
    assert not annual_metrics(leap_invalid, _events()).loc[2000, "valid"]


def test_boundary_90_percent_common_year_lengths() -> None:
    common_valid = _as_na(_constant(2000, 2001), 2001, 36)
    common_invalid = _as_na(_constant(2000, 2001), 2001, 37)
    assert annual_metrics(common_valid, _events()).loc[2001, "valid"]
    assert not annual_metrics(common_invalid, _events()).loc[2001, "valid"]


def test_invalid_year_with_events_shows_nan_everywhere() -> None:
    series = _as_na(_constant(2000, 2000), 2000, 66)
    events = _events(_event("2000-08-01", 4, 3.0, 5.0, 39.0))
    row = annual_metrics(series, events).loc[2000]
    assert not row["valid"]
    for column in _METRIC_COLUMNS:
        assert np.isnan(row[column])


def test_edge_years_judged_against_full_calendar_lengths() -> None:
    mid_year = pd.Series(np.full(549, 30.0), index=pd.date_range("2000-07-01", "2001-12-31"))
    result = annual_metrics(mid_year, _events())
    assert result.index.tolist() == [2000, 2001]
    row = result.loc[2000]
    assert row["total_days"] == 366 and row["valid_days"] == 184 and not row["valid"]
    assert result.loc[2001, "valid"]

    early_end = pd.Series(np.full(456, 30.0), index=pd.date_range("2000-01-01", "2001-03-31"))
    row = annual_metrics(early_end, _events()).loc[2001]
    assert row["total_days"] == 365 and row["valid_days"] == 90 and not row["valid"]


def test_cross_year_event_is_counted_once_in_start_year() -> None:
    events = _events(_event("2000-12-30", 4, 2.0, 3.0, 34.0, end_date="2001-01-02"))
    result = annual_metrics(_constant(2000, 2001), events)
    assert result.loc[2000, "event_count"] == 1
    assert result.loc[2000, "heatwave_days"] == 4
    assert result.loc[2000, "mean_duration"] == pytest.approx(4.0)
    assert result.loc[2001, "event_count"] == 0
    assert result.loc[2001, "heatwave_days"] == 0


def test_events_are_attributed_by_start_date_not_year_column() -> None:
    event = _event("2000-12-30", 4, 2.0, 3.0, 34.0, end_date="2001-01-02")
    event["year"] = 2099
    result = annual_metrics(_constant(2000, 2001), _events(event))
    assert result.loc[2000, "event_count"] == 1
    assert 2099 not in result.index


def test_year_with_no_rows_in_span_is_present_and_invalid() -> None:
    full = _constant(2000, 2002)
    series = full[full.index.year != 2001]
    result = annual_metrics(series, _events())
    assert result.index.tolist() == [2000, 2001, 2002]
    row = result.loc[2001]
    assert row["total_days"] == 365 and row["valid_days"] == 0 and not row["valid"]
    assert np.isnan(row["event_count"]) and np.isnan(row["heatwave_days"])


def test_schema_index_name_dtypes_and_column_order() -> None:
    result = annual_metrics(_constant(2000, 2001), _events())
    assert result.index.name == "year"
    assert result.index.dtype == np.int64
    assert result["valid"].dtype == bool
    assert result["total_days"].dtype == np.int64
    assert result["valid_days"].dtype == np.int64
    assert list(result.columns) == [
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


def test_valid_flag_matches_coverage_by_year_rule() -> None:
    series = _as_na(_constant(2000, 2001), 2001, 100)
    result = annual_metrics(series, _events())
    expected = result["valid_days"] / result["total_days"] >= MIN_VALID_FRACTION
    pd.testing.assert_series_equal(result["valid"], expected, check_names=False)


def test_total_days_match_reference_lengths() -> None:
    result = annual_metrics(_constant(1999, 2001), _events())
    assert result["total_days"].to_dict() == {1999: 365, 2000: 366, 2001: 365}


def test_unsorted_index_raises() -> None:
    with pytest.raises(AppError):
        annual_metrics(_constant(2000, 2001)[::-1], _events())


def test_duplicate_index_raises() -> None:
    duplicate = pd.concat([_constant(2000, 2000), _constant(2000, 2000).iloc[[0]]])
    with pytest.raises(AppError):
        annual_metrics(duplicate, _events())


def test_events_missing_column_raises() -> None:
    events = _events(_event("2000-07-01", 3, 2.0, 3.0, 36.0)).drop(columns=["intensity"])
    with pytest.raises(AppError):
        annual_metrics(_constant(2000, 2001), events)


def test_events_start_column_not_datetime_raises() -> None:
    events = _events(_event("2000-07-01", 3, 2.0, 3.0, 36.0)).assign(start=["2000-07-01"])
    with pytest.raises(AppError):
        annual_metrics(_constant(2000, 2001), events)


def test_all_nan_series_marks_every_year_invalid() -> None:
    series = pd.Series(
        np.full(len(_daily(1990, 2025)), np.nan), index=_daily(1990, 2025), dtype="float64"
    )
    result = annual_metrics(series, _events())
    assert len(result) == 36
    assert not result["valid"].any()
    assert result["event_count"].isna().all()
    assert result["total_days"].sum() == 365 * 36 + 9


def test_empty_events_with_correct_columns() -> None:
    result = annual_metrics(_constant(2000, 2002), _events())
    assert (result["event_count"] == 0).all()
    assert (result["heatwave_days"] == 0).all()
    assert result["mean_intensity"].isna().all()
    assert result["max_duration"].isna().all()


def test_event_start_year_outside_span_raises() -> None:
    with pytest.raises(AppError):
        annual_metrics(_constant(1990, 2025), _events(_event("2026-07-01", 3, 2.0, 3.0, 36.0)))
    with pytest.raises(AppError):
        annual_metrics(_constant(1990, 2025), _events(_event("1989-07-01", 3, 2.0, 3.0, 36.0)))


def test_inputs_not_mutated_and_two_calls_equal() -> None:
    series = _as_na(_constant(2000, 2001), 2000, 40)
    events = _events(
        _event("2000-06-01", 3, 4.0, 6.0, 38.0), _event("2001-07-01", 2, 2.0, 2.5, 35.0)
    )
    series_before = series.copy()
    events_before = events.copy()
    first = annual_metrics(series, events)
    second = annual_metrics(series, events)
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_series_equal(series, series_before)
    pd.testing.assert_frame_equal(events, events_before)


def test_region_means_over_valid_cells_only() -> None:
    cell_a = annual_metrics(
        _constant(2000, 2001),
        _events(_event("2000-06-01", 3, 4.0, 6.0, 38.0), _event("2001-07-01", 2, 2.0, 2.5, 35.0)),
    )
    cell_b = annual_metrics(
        _as_na(_constant(2000, 2001), 2000, 366),
        _events(_event("2001-08-10", 5, 6.0, 7.0, 40.0)),
    )
    region = region_metrics([cell_a, cell_b])
    year_2000 = region.loc[2000]
    assert year_2000["n_cells_valid"] == 1 and year_2000["valid"]
    assert year_2000["event_count"] == pytest.approx(1.0)
    assert year_2000["mean_intensity"] == pytest.approx(4.0)
    year_2001 = region.loc[2001]
    assert year_2001["n_cells_valid"] == 2
    assert year_2001["event_count"] == pytest.approx(1.0)
    assert year_2001["mean_intensity"] == pytest.approx(4.0)


def test_region_zero_event_cell_contributes_zero_count_not_intensity() -> None:
    cell_a = annual_metrics(_constant(2000, 2000), _events(_event("2000-06-01", 2, 4.0, 6.0, 38.0)))
    cell_b = annual_metrics(_constant(2000, 2000), _events())
    region = region_metrics([cell_a, cell_b])
    row = region.loc[2000]
    assert row["n_cells_valid"] == 2
    assert row["event_count"] == pytest.approx(0.5)
    assert row["heatwave_days"] == pytest.approx(1.0)
    assert row["mean_intensity"] == pytest.approx(4.0)
    assert row["max_exceedance"] == pytest.approx(6.0)
    assert row["peak_tmax"] == pytest.approx(38.0)


def test_region_valid_at_exactly_half_and_invalid_below() -> None:
    valid_cell = annual_metrics(_constant(2000, 2000), _events())
    invalid_cell = annual_metrics(_as_na(_constant(2000, 2000), 2000, 366), _events())
    region = region_metrics([valid_cell, invalid_cell])
    assert region.loc[2000, "n_cells_valid"] == 1
    assert region.loc[2000, "valid"]

    cells = [valid_cell] + [invalid_cell] * 3
    region = region_metrics(cells)
    assert region.loc[2000, "n_cells_valid"] == 1
    assert not region.loc[2000, "valid"]
    assert region.loc[2000, "event_count"] == pytest.approx(0.0)


def test_region_union_of_years_and_out_of_span_cells() -> None:
    cell_a = annual_metrics(_constant(1999, 2001), _events())
    cell_b = annual_metrics(_constant(2000, 2002), _events())
    region = region_metrics([cell_a, cell_b])
    assert region.index.tolist() == [1999, 2000, 2001, 2002]
    assert region.loc[1999, "n_cells_valid"] == 1 and region.loc[1999, "valid"]
    assert region.loc[2002, "n_cells_valid"] == 1
    assert region.loc[2000, "n_cells_valid"] == 2


def test_region_schema_order_and_dtypes() -> None:
    region = region_metrics([annual_metrics(_constant(2000, 2001), _events())])
    assert list(region.columns) == _METRIC_COLUMNS + ["n_cells_valid", "valid"]
    assert region["n_cells_valid"].dtype == np.int64
    assert region["valid"].dtype == bool


def test_region_rejects_empty_too_many_and_malformed() -> None:
    with pytest.raises(AppError):
        region_metrics([])
    with pytest.raises(AppError):
        region_metrics([pd.DataFrame({"x": [1]})])
    cells = [annual_metrics(_constant(2000, 2000), _events()) for _ in range(9)]
    assert not region_metrics(cells).empty
    with pytest.raises(AppError):
        region_metrics(cells + [annual_metrics(_constant(2000, 2000), _events())])
    with pytest.raises(AppError):
        region_metrics(cells[:4], max_cells=3)


def test_region_inputs_not_mutated_and_two_calls_equal() -> None:
    cell_a = annual_metrics(_constant(2000, 2001), _events(_event("2000-06-01", 3, 4.0, 6.0, 38.0)))
    cell_b = annual_metrics(_constant(2000, 2001), _events())
    cells_before = [cell_a.copy(), cell_b.copy()]
    first = region_metrics([cell_a, cell_b])
    second = region_metrics([cell_a, cell_b])
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(cell_a, cells_before[0])
    pd.testing.assert_frame_equal(cell_b, cells_before[1])


def test_integration_thresholds_events_metrics() -> None:
    series = _seasonal(1990, 2025)
    threshold = compute_thresholds(series)
    spiked = series.copy()
    spiked.loc["2005-07-10":"2005-07-14"] = 45.0
    events = detect_events(spiked, threshold)
    result = annual_metrics(spiked, events)
    assert (result["event_count"] == 1).sum() == 1
    assert result.loc[2005, "event_count"] == 1
    assert result.loc[2005, "heatwave_days"] == 5
    assert result.loc[2005, "max_duration"] == 5
    assert result.loc[2005, "peak_tmax"] == pytest.approx(45.0)
    assert (result["event_count"] == 0).sum() == 35
    assert result["valid"].all()
