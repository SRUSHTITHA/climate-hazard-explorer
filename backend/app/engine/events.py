import numpy as np
import pandas as pd

from app.engine.thresholds import DOY_COUNT, leap_aligned_doy

MIN_EVENT_DAYS = 3

_COLUMNS = [
    "start",
    "end",
    "year",
    "duration_days",
    "peak_tmax",
    "mean_tmax",
    "intensity",
    "max_exceedance",
]


class EventError(ValueError):
    pass


def detect_events(tmax: pd.Series, thresholds: pd.Series) -> pd.DataFrame:
    _validate_inputs(tmax, thresholds)
    values = tmax.to_numpy(dtype=float)
    day_threshold = thresholds.to_numpy(dtype=float)[leap_aligned_doy(tmax.index) - 1]
    exceed = values > day_threshold
    if not exceed.any():
        return _empty_events(tmax.index)
    consecutive = np.diff(tmax.index.values).astype("timedelta64[D]").astype(int) == 1
    continues = np.zeros(len(tmax), dtype=bool)
    continues[1:] = exceed[1:] & exceed[:-1] & consecutive
    group = np.cumsum(~continues)
    days = pd.DataFrame(
        {
            "group": group[exceed],
            "date": tmax.index[exceed],
            "tmax": values[exceed],
            "exceedance": (values - day_threshold)[exceed],
        }
    )
    events = (
        days.groupby("group", sort=True)
        .agg(
            start=("date", "min"),
            end=("date", "max"),
            duration_days=("date", "size"),
            peak_tmax=("tmax", "max"),
            mean_tmax=("tmax", "mean"),
            intensity=("exceedance", "mean"),
            max_exceedance=("exceedance", "max"),
        )
        .reset_index(drop=True)
    )
    events = events[events["duration_days"] >= MIN_EVENT_DAYS].copy()
    events["year"] = events["start"].dt.year.astype("int64")
    return events.loc[:, _COLUMNS].sort_values("start").reset_index(drop=True)


def _validate_inputs(tmax: pd.Series, thresholds: pd.Series) -> None:
    index = tmax.index
    if not isinstance(index, pd.DatetimeIndex):
        raise EventError("tmax must have a DatetimeIndex.")
    if index.has_duplicates:
        raise EventError("tmax index must not contain duplicate dates.")
    if not index.is_monotonic_increasing:
        raise EventError("tmax index must be sorted.")
    if len(thresholds) != DOY_COUNT or not np.array_equal(
        np.asarray(thresholds.index), np.arange(1, DOY_COUNT + 1)
    ):
        raise EventError("thresholds must be indexed by day-of-year 1..366.")


def _empty_events(index: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "start": index[:0],
            "end": index[:0],
            "year": pd.Series(dtype="int64"),
            "duration_days": pd.Series(dtype="int64"),
            "peak_tmax": pd.Series(dtype="float64"),
            "mean_tmax": pd.Series(dtype="float64"),
            "intensity": pd.Series(dtype="float64"),
            "max_exceedance": pd.Series(dtype="float64"),
        }
    )
