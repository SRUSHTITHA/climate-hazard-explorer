import numpy as np
import pandas as pd

from app.engine.cleaning import is_sorted_datetime_index
from app.engine.thresholds import DOY_COUNT, leap_aligned_doy
from app.errors import AppError

MIN_EVENT_DAYS = 3
EVENT_COLUMNS = [
    "start",
    "end",
    "year",
    "duration_days",
    "peak_tmax",
    "mean_tmax",
    "intensity",
    "max_exceedance",
]


def detect_events(tmax: pd.Series, thresholds: pd.Series) -> pd.DataFrame:
    _validate_inputs(tmax, thresholds)
    values = tmax.to_numpy(dtype=float)
    day_threshold = thresholds.to_numpy(dtype=float)[leap_aligned_doy(tmax.index) - 1]
    exceed = values > day_threshold
    if not exceed.any():
        return empty_events(tmax.index)
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
    return events.loc[:, EVENT_COLUMNS].sort_values("start").reset_index(drop=True)


def _validate_inputs(tmax: pd.Series, thresholds: pd.Series) -> None:
    if not is_sorted_datetime_index(tmax.index):
        raise AppError.internal()
    if len(thresholds) != DOY_COUNT or not np.array_equal(
        np.asarray(thresholds.index), np.arange(1, DOY_COUNT + 1)
    ):
        raise AppError.internal()


def empty_events(index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    dates = index[:0] if index is not None else pd.Series(dtype="datetime64[ns]")
    empty_dates = dates if index is not None else pd.Series(dtype="datetime64[ns]")
    return pd.DataFrame(
        {
            "start": dates,
            "end": empty_dates,
            "year": pd.Series(dtype="int64"),
            "duration_days": pd.Series(dtype="int64"),
            "peak_tmax": pd.Series(dtype="float64"),
            "mean_tmax": pd.Series(dtype="float64"),
            "intensity": pd.Series(dtype="float64"),
            "max_exceedance": pd.Series(dtype="float64"),
        }
    )
