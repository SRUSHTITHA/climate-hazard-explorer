import numpy as np
import pandas as pd
import pymannkendall as mk
from scipy.stats import theilslopes
from app.errors import AppError

MIN_VALID_YEARS = 15
P_STRONG = 0.05
P_WEAK = 0.15
ROLLING_WINDOW = 5
ROLLING_MIN_PERIODS = 3
PERIOD_YEARS = 5
PCT_BASE_MIN = 1.0


def rolling_mean(series: pd.Series) -> pd.Series:
    _validate_series(series)
    return series.rolling(ROLLING_WINDOW, center=True, min_periods=ROLLING_MIN_PERIODS).mean()

def trend(series: pd.Series) -> dict:
    _validate_series(series)
    valid = series.dropna()
    result = {
        "n_years": int(valid.size),
        "slope_per_decade": np.nan,
        "p_value": np.nan,
        "evidence": "insufficient",
        "direction": None,
        "first_mean": np.nan,
        "last_mean": np.nan,
        "pct_change": None,
    }
    if valid.size < MIN_VALID_YEARS:
        return result
    years = valid.index.to_numpy(dtype=float)
    values = valid.to_numpy(dtype=float)
    result["slope_per_decade"] = float(theilslopes(values, years).slope) * 10.0
    result["p_value"] = float(mk.original_test(values).p)
    result["first_mean"] = float(valid.iloc[:PERIOD_YEARS].mean())
    result["last_mean"] = float(valid.iloc[-PERIOD_YEARS:].mean())
    result["evidence"] = _evidence(result["p_value"])
    result["direction"] = _direction(result["slope_per_decade"], result["evidence"])
    result["pct_change"] = _pct_change(result["first_mean"], result["last_mean"])
    return result

def trend_table(df: pd.DataFrame, columns: tuple[str, ...]) -> dict[str, dict]:
    if "valid" not in df.columns or any(column not in df.columns for column in columns):
        raise AppError.internal()
    valid_rows = df[df["valid"].astype(bool)]
    return {column: trend(valid_rows[column]) for column in columns}


def _evidence(p_value: float) -> str:
    if p_value < P_STRONG:
        return "strong"
    if p_value < P_WEAK:
        return "weak"
    return "none"


def _direction(slope: float, evidence: str) -> str:
    if evidence == "none":
        return "flat"
    if slope > 0:
        return "increasing"
    if slope < 0:
        return "decreasing"
    return "flat"


def _pct_change(first_mean: float, last_mean: float) -> float | None:
    if first_mean < PCT_BASE_MIN:
        return None
    return (last_mean - first_mean) / first_mean * 100.0


def _validate_series(series: pd.Series) -> None:
    if not isinstance(series, pd.Series) or not pd.api.types.is_numeric_dtype(series.dtype):
        raise AppError.internal()
    index = series.index
    if (
        not pd.api.types.is_integer_dtype(index.dtype)
        or index.has_duplicates
        or not index.is_monotonic_increasing
        or np.isinf(series.to_numpy(dtype=float)).any()
    ):
        raise AppError.internal()
