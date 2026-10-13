import numpy as np
import pandas as pd

from app.engine.cleaning import MIN_VALID_FRACTION, coverage_by_year, is_sorted_datetime_index
from app.errors import AppError

BASELINE_START = 1991
BASELINE_END = 2020
PERCENTILE = 95.0
WINDOW_HALF_WIDTH = 7
MIN_BASELINE_YEARS = 24
MIN_POOL = 100
DOY_COUNT = 366


def leap_aligned_doy(index: pd.DatetimeIndex) -> np.ndarray:
    day_of_year = np.asarray(index.dayofyear)
    shift = (~np.asarray(index.is_leap_year) & (np.asarray(index.month) >= 3)).astype(int)
    return day_of_year + shift


def compute_thresholds(tmax: pd.Series) -> pd.Series:
    _validate_series(tmax)
    baseline = tmax[(tmax.index.year >= BASELINE_START) & (tmax.index.year <= BASELINE_END)]
    valid_years = int((coverage_by_year(baseline) >= MIN_VALID_FRACTION).sum())
    if valid_years < MIN_BASELINE_YEARS:
        raise AppError.unavailable()
    pooled = _window_pool(_baseline_matrix(baseline))
    counts = np.count_nonzero(~np.isnan(pooled), axis=0)
    thresholds = np.full(DOY_COUNT, np.nan)
    enough = counts >= MIN_POOL
    thresholds[enough] = np.nanpercentile(pooled[:, enough], PERCENTILE, axis=0)
    return pd.Series(thresholds, index=np.arange(1, DOY_COUNT + 1), name="threshold")


def _validate_series(tmax: pd.Series) -> None:
    if not is_sorted_datetime_index(tmax.index):
        raise AppError.unavailable()


def _baseline_matrix(baseline: pd.Series) -> np.ndarray:
    years = np.asarray(baseline.index.year)
    unique_years = np.unique(years)
    matrix = np.full((len(unique_years), DOY_COUNT), np.nan)
    rows = np.searchsorted(unique_years, years)
    matrix[rows, leap_aligned_doy(baseline.index) - 1] = baseline.to_numpy(dtype=float)
    return matrix


def _window_pool(matrix: np.ndarray) -> np.ndarray:
    offsets = np.arange(-WINDOW_HALF_WIDTH, WINDOW_HALF_WIDTH + 1)
    columns = (np.arange(DOY_COUNT)[None, :] + offsets[:, None]) % DOY_COUNT
    return matrix[:, columns].reshape(-1, DOY_COUNT)
