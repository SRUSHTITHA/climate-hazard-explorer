import datetime as dt
import numpy as np
import pandas as pd

MIN_VALID_FRACTION = 0.9
LOWER_BOUND_C = -90.0
UPPER_BOUND_C = 60.0
SUSPECT_DEVIATION_C = 15.0

def clean_daily(dates: list[str], tmax: list) -> pd.Series:
    if not dates or not tmax:
        raise ValueError("dates and tmax must not be empty.")
    if len(dates) != len(tmax):
        raise ValueError("dates and tmax must have the same length.")
    index = _parse_index(dates)
    raw = pd.Series(tmax, index=index, dtype=object).sort_index()
    full = pd.date_range(raw.index[0], raw.index[-1], freq="D")
    aligned = raw.reindex(full)
    obj = aligned.to_numpy(dtype=object)
    none = np.equal(obj, None)
    text = obj.astype(str)
    non_number = ~none & (pd.isna(obj) | (text == obj) | (text == "True") | (text == "False"))
    try:
        values = pd.to_numeric(aligned, errors="coerce").to_numpy(dtype="float64")
    except OverflowError:
        values = np.frompyfunc(_as_float, 1, 1)(obj).astype("float64")
    missing = none | ~full.isin(index)
    invalid = ~missing & (
        non_number | ~np.isfinite(values) | (values < LOWER_BOUND_C) | (values > UPPER_BOUND_C)
    )
    clean = pd.Series(np.where(missing | invalid, np.nan, values), index=full, dtype="float64")
    clean.attrs["missing_mask"] = missing
    clean.attrs["invalid_mask"] = invalid
    clean.attrs["suspect_mask"] = _suspect_mask(clean)
    return clean

def _suspect_mask(series: pd.Series) -> np.ndarray:
    valid = series.notna().to_numpy(dtype=bool)
    median = series.rolling(15, center=True, min_periods=8).median()
    return (valid & ((series - median).abs() > SUSPECT_DEVIATION_C)).to_numpy(dtype=bool)

def _as_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        return np.nan
    try:
        return float(value)
    except OverflowError:
        return np.nan

def _parse_index(dates: list[str]) -> pd.DatetimeIndex:
    if not all(isinstance(day, str) for day in dates):
        raise ValueError("dates must be ISO date strings.")
    try:
        index = pd.DatetimeIndex(pd.to_datetime(dates, format="mixed", errors="raise"))
    except (TypeError, ValueError):
        raise ValueError("dates must be ISO date strings.") from None
    if index.hasnans:
        raise ValueError("dates must be ISO date strings.")
    if index.has_duplicates:
        raise ValueError("dates must not contain duplicates.")
    return index

def days_in_year(year: int) -> int:
    return (dt.date(year, 12, 31) - dt.date(year, 1, 1)).days + 1

def coverage_by_year(series: pd.Series) -> pd.Series:
    counts = series.notna().groupby(series.index.year).sum()
    totals = pd.Series((days_in_year(int(year)) for year in counts.index), index=counts.index)
    return counts / totals

def drop_unusable_years(series: pd.Series) -> pd.Series:
    coverage = coverage_by_year(series)
    usable = coverage.index[coverage >= MIN_VALID_FRACTION]
    result = series.where(series.index.year.isin(usable))
    result.attrs = {}
    return result

def quality_report(series: pd.Series) -> dict:
    attrs = series.attrs
    missing = attrs.get("missing_mask", series.isna().to_numpy(dtype=bool))
    invalid = attrs.get("invalid_mask", np.zeros(len(series), dtype=bool))
    valid = series.notna().to_numpy(dtype=bool)
    suspect = attrs.get("suspect_mask", _suspect_mask(series))
    yearly = coverage_by_year(series)
    years = [
        {
            "year": int(year),
            "valid_fraction": float(fraction),
            "included": bool(fraction >= MIN_VALID_FRACTION),
        }
        for year, fraction in yearly.items()
    ]
    total = len(series)
    valid_days = int(valid.sum())
    return {
        "total_days": total,
        "valid_days": valid_days,
        "missing_days": int(missing.sum()),
        "invalid_days": int(invalid.sum()),
        "suspect_days": int(suspect.sum()),
        "valid_fraction": valid_days / total if total else 0.0,
        "bounds_c": [LOWER_BOUND_C, UPPER_BOUND_C],
        "min_valid_fraction": MIN_VALID_FRACTION,
        "years": years,
        "excluded_years": [
            int(year) for year, fraction in yearly.items() if fraction < MIN_VALID_FRACTION
        ],
    }
