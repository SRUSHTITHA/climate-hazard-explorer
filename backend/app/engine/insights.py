import numpy as np
import pandas as pd

from app.engine.trends import MIN_VALID_YEARS

DATA_SOURCE = "Data: ERA5 reanalysis via Open-Meteo"

_EVIDENCE_LEVELS = ("strong", "weak", "none", "insufficient")
_HEADLINE_KEYS = (
    "n_years",
    "evidence",
    "direction",
    "slope_per_decade",
    "first_mean",
    "last_mean",
    "pct_change",
)
_INTENSITY_KEYS = (
    "n_years",
    "evidence",
    "direction",
    "slope_per_decade",
    "first_mean",
    "last_mean",
)
_REGION_COLUMNS = ("heatwave_days", "valid", "n_cells_valid")
_VERBS = {"increasing": "increased", "decreasing": "decreased"}

_TEMPLATES = {
    "headline_strong_percent": (
        "{region}: {hazard} days per year {verb} from {first:.1f} to {last:.1f} "
        "(first vs last five valid years), a {pct:.0f}% change ({slope:.1f} days per decade)."
    ),
    "headline_strong_absolute": (
        "{region}: {hazard} days per year {verb} by {slope:.1f} days per decade "
        "(from {first:.1f} to {last:.1f}, first vs last five valid years); "
        "the early baseline is too low for a meaningful percentage change."
    ),
    "headline_weak": (
        "{region}: weak, non-conclusive evidence that {hazard} days per year "
        "{verb} by about {slope:.1f} days per decade."
    ),
    "headline_none": "{region}: no clear trend was detected in {hazard} days per year.",
    "headline_insufficient": (
        "{region}: not enough valid years to assess a {hazard} signal "
        "({n_years} of the required {min_years} valid years)."
    ),
    "intensity_strong": (
        "{region}: {hazard} intensity per year {verb} by {slope:.1f} degrees C per decade, "
        "from {first:.2f} to {last:.2f} degrees C above the threshold "
        "(first vs last five valid years)."
    ),
    "intensity_weak": (
        "{region}: weak, non-conclusive evidence that {hazard} intensity per year "
        "{verb} by about {slope:.1f} degrees C per decade."
    ),
    "intensity_none": "{region}: no clear trend was detected in {hazard} intensity.",
    "intensity_insufficient": (
        "{region}: not enough valid years to assess a {hazard} intensity signal "
        "({n_years} of the required {min_years} valid years)."
    ),
    "peak_year": (
        "{region}: the largest number of {hazard} days in a valid year was {value:.1f} in {year}."
    ),
    "peak_year_zero": "{region}: no {hazard} days in any valid year.",
    "data_quality": "{source} {region}: {valid_years} of {total_years} years are valid.",
    "data_quality_cells": (
        " The smallest cell coverage in a year was {min_cells} of {cell_count} cells."
    ),
}


class InsightError(ValueError):
    pass


def build_insights(
    hazard: str, region_name: str, region_df: pd.DataFrame, trends: dict[str, dict]
) -> list[dict]:
    _validate_inputs(region_df, trends)
    insights = [_headline(hazard, region_name, trends["heatwave_days"])]
    if "mean_intensity" in trends:
        insights.append(_intensity(hazard, region_name, trends["mean_intensity"]))
    peak = _peak_year(hazard, region_name, region_df)
    if peak is not None:
        insights.append(peak)
    insights.append(_data_quality(region_name, region_df))
    return insights


def _headline(hazard: str, region_name: str, trend: dict) -> dict:
    evidence = trend["evidence"]
    fields = {"region": region_name, "hazard": hazard}
    if evidence == "insufficient":
        fields.update(n_years=trend["n_years"], min_years=MIN_VALID_YEARS)
        return _insight("headline", "caution", _TEMPLATES["headline_insufficient"].format(**fields))
    if evidence == "none":
        return _insight("headline", "caution", _TEMPLATES["headline_none"].format(**fields))
    fields["verb"] = _verb(trend["direction"])
    fields["slope"] = abs(_finite("slope_per_decade", trend["slope_per_decade"]))
    if evidence == "weak":
        return _insight("headline", "caution", _TEMPLATES["headline_weak"].format(**fields))
    fields["first"] = _finite("first_mean", trend["first_mean"])
    fields["last"] = _finite("last_mean", trend["last_mean"])
    percent = _percent(trend["pct_change"])
    if percent is None:
        return _insight("headline", "info", _TEMPLATES["headline_strong_absolute"].format(**fields))
    fields["pct"] = percent
    return _insight("headline", "info", _TEMPLATES["headline_strong_percent"].format(**fields))


def _intensity(hazard: str, region_name: str, trend: dict) -> dict:
    evidence = trend["evidence"]
    fields = {"region": region_name, "hazard": hazard}
    if evidence == "insufficient":
        fields.update(n_years=trend["n_years"], min_years=MIN_VALID_YEARS)
        text = _TEMPLATES["intensity_insufficient"].format(**fields)
        return _insight("intensity", "caution", text)
    if evidence == "none":
        return _insight("intensity", "caution", _TEMPLATES["intensity_none"].format(**fields))
    fields["verb"] = _verb(trend["direction"])
    fields["slope"] = abs(_finite("slope_per_decade", trend["slope_per_decade"]))
    if evidence == "weak":
        return _insight("intensity", "caution", _TEMPLATES["intensity_weak"].format(**fields))
    fields["first"] = _finite("first_mean", trend["first_mean"])
    fields["last"] = _finite("last_mean", trend["last_mean"])
    return _insight("intensity", "info", _TEMPLATES["intensity_strong"].format(**fields))


def _peak_year(hazard: str, region_name: str, region_df: pd.DataFrame) -> dict | None:
    valid = region_df[region_df["valid"].astype(bool)]
    days = valid["heatwave_days"].dropna()
    if days.empty:
        return None
    value = float(days.max())
    if value == 0.0:
        text = _TEMPLATES["peak_year_zero"].format(region=region_name, hazard=hazard)
        return _insight("peak_year", "info", text)
    year = int(days.idxmax())
    text = _TEMPLATES["peak_year"].format(region=region_name, hazard=hazard, value=value, year=year)
    return _insight("peak_year", "info", text)


def _data_quality(region_name: str, region_df: pd.DataFrame) -> dict:
    total = len(region_df)
    valid_years = int(region_df["valid"].astype(bool).sum())
    text = _TEMPLATES["data_quality"].format(
        source=DATA_SOURCE, region=region_name, valid_years=valid_years, total_years=total
    )
    caution = valid_years != total
    if total:
        cells = region_df["n_cells_valid"]
        cell_count = int(cells.max())
        min_cells = int(cells.min())
        if min_cells < cell_count:
            text += _TEMPLATES["data_quality_cells"].format(
                min_cells=min_cells, cell_count=cell_count
            )
            caution = True
    return _insight("data_quality", "caution" if caution else "info", text)


def _insight(key: str, level: str, text: str) -> dict:
    return {"key": key, "level": level, "text": text}


def _verb(direction: str) -> str:
    if direction not in _VERBS:
        raise InsightError(f"Unknown direction: {direction!r}.")
    return _VERBS[direction]


def _finite(name: str, value: float) -> float:
    if value is None or not np.isfinite(value):
        raise InsightError(f"Trend {name} must be a finite number.")
    return float(value)


def _percent(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if not np.isfinite(value):
        return None
    return abs(value)


def _validate_inputs(region_df: pd.DataFrame, trends: dict[str, dict]) -> None:
    if not isinstance(trends, dict) or "heatwave_days" not in trends:
        raise InsightError("trends must contain a heatwave_days trend.")
    _validate_trend("heatwave_days", trends["heatwave_days"], _HEADLINE_KEYS)
    if "mean_intensity" in trends:
        _validate_trend("mean_intensity", trends["mean_intensity"], _INTENSITY_KEYS)
    if not isinstance(region_df, pd.DataFrame):
        raise InsightError("region_df must be a DataFrame.")
    missing = [column for column in _REGION_COLUMNS if column not in region_df.columns]
    if missing:
        raise InsightError(f"region_df is missing column(s): {', '.join(missing)}.")


def _validate_trend(name: str, trend: dict, keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in trend]
    if missing:
        raise InsightError(f"trend {name} is missing key(s): {', '.join(missing)}.")
    if trend["evidence"] not in _EVIDENCE_LEVELS:
        raise InsightError(f"trend {name} has unknown evidence: {trend['evidence']!r}.")
