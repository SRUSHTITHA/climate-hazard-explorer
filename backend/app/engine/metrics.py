import numpy as np
import pandas as pd

from app.constants import MAX_CELLS
from app.engine.cleaning import MIN_VALID_FRACTION, coverage_by_year, days_in_year, is_sorted_datetime_index
from app.errors import AppError

MIN_CELL_FRACTION = 0.5

ANNUAL_COLUMNS = [
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
_METRIC_COLUMNS = ANNUAL_COLUMNS[3:]
_REQUIRED_EVENT_COLUMNS = ("start", "duration_days", "intensity", "max_exceedance", "peak_tmax")


def annual_metrics(tmax: pd.Series, events: pd.DataFrame) -> pd.DataFrame:
    _validate_series(tmax)
    _validate_events(events)
    years = np.arange(int(tmax.index.year.min()), int(tmax.index.year.max()) + 1)
    index = pd.Index(years, name="year")
    metrics = pd.DataFrame(index=index)
    metrics["valid_days"] = (
        tmax.notna().groupby(tmax.index.year).sum().reindex(index).fillna(0).to_numpy(dtype="int64")
    )
    metrics["total_days"] = np.array([days_in_year(int(year)) for year in years])
    coverage = coverage_by_year(tmax).reindex(index).fillna(0.0)
    metrics["valid"] = coverage >= MIN_VALID_FRACTION
    start_years = events["start"].dt.year
    if not ((start_years >= years[0]) & (start_years <= years[-1])).all():
        raise AppError.unavailable()
    grouped = events.groupby(start_years)
    metrics["event_count"] = grouped.size().reindex(index, fill_value=0)
    metrics["heatwave_days"] = grouped["duration_days"].sum().reindex(index, fill_value=0)
    metrics["max_duration"] = grouped["duration_days"].max().reindex(index)
    metrics["mean_duration"] = grouped["duration_days"].mean().reindex(index)
    weighted = (events["intensity"] * events["duration_days"]).groupby(start_years).sum()
    metrics["mean_intensity"] = weighted.reindex(index) / metrics["heatwave_days"]
    metrics["max_exceedance"] = grouped["max_exceedance"].max().reindex(index)
    metrics["peak_tmax"] = grouped["peak_tmax"].max().reindex(index)
    metrics.loc[~np.asarray(metrics["valid"]), _METRIC_COLUMNS] = np.nan
    return metrics


def region_metrics(per_cell: list[pd.DataFrame], max_cells: int = MAX_CELLS) -> pd.DataFrame:
    if (
        not isinstance(per_cell, list)
        or not per_cell
        or len(per_cell) > max_cells
        or any("valid" not in cell.columns for cell in per_cell)
    ):
        raise AppError.unavailable()
    cell_count = len(per_cell)
    combined = pd.concat([cell[_METRIC_COLUMNS] for cell in per_cell])
    result = combined.groupby(level=0).mean()
    result["n_cells_valid"] = pd.concat([cell["valid"] for cell in per_cell]).groupby(level=0).sum()
    result["valid"] = result["n_cells_valid"] >= MIN_CELL_FRACTION * cell_count
    return result


def _validate_series(tmax: pd.Series) -> None:
    if not is_sorted_datetime_index(tmax.index):
        raise AppError.unavailable()


def _validate_events(events: pd.DataFrame) -> None:
    missing = [column for column in _REQUIRED_EVENT_COLUMNS if column not in events.columns]
    if missing or not pd.api.types.is_datetime64_any_dtype(events["start"]):
        raise AppError.unavailable()
