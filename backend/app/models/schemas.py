import math
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.engine.insights import DATA_SOURCE
from app.services.ingestion import HISTORY_START
from app.services.regions import MAX_CELLS, RegionError, cell_id, cells_in_box

MIN_RANGE_YEARS = 10
MAX_SERIES_YEARS = 100

Hazard = Literal["heatwave"]
Evidence = Literal["strong", "weak", "none", "insufficient"]
Direction = Literal["increasing", "decreasing", "flat"]
InsightLevel = Literal["info", "caution"]
TrendKey = Literal["heatwave_days", "mean_intensity"]

_FORBIDDEN_MESSAGE_PARTS = ("http", "mongodb", "/", "\\", "traceback")


def _finite_or_none(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


NullableFloat = Annotated[float | None, BeforeValidator(_finite_or_none)]
Coordinate = Annotated[float | None, Field(allow_inf_nan=False)]
CellId = Annotated[str, StringConstraints(min_length=1, max_length=16)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(_Model):
    hazard: Hazard = "heatwave"
    start_year: int
    end_year: int
    lat: Coordinate = None
    lon: Coordinate = None
    south: Coordinate = None
    west: Coordinate = None
    north: Coordinate = None
    east: Coordinate = None

    _cell_ids: list[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        _validate_years(self)
        self._cell_ids = _resolve_region(self)
        return self

    @property
    def cell_ids(self) -> list[str]:
        return list(self._cell_ids)


class TrendOut(_Model):
    n_years: int
    slope_per_decade: NullableFloat = None
    p_value: NullableFloat = None
    evidence: Evidence
    direction: Direction | None = None
    first_mean: NullableFloat = None
    last_mean: NullableFloat = None
    pct_change: NullableFloat = None


class YearPoint(_Model):
    year: int
    valid: bool
    event_count: NullableFloat = None
    heatwave_days: NullableFloat = None
    max_duration: NullableFloat = None
    mean_duration: NullableFloat = None
    mean_intensity: NullableFloat = None
    max_exceedance: NullableFloat = None
    peak_tmax: NullableFloat = None
    n_cells_valid: int
    rolling_heatwave_days: NullableFloat = None


class InsightOut(_Model):
    key: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    level: InsightLevel
    text: Annotated[str, StringConstraints(min_length=1, max_length=1000)]


class QualityOut(_Model):
    valid_years: int
    total_years: int
    cells: int
    min_cells_valid: int


class AnalysisResponse(_Model):
    hazard: Hazard
    cell_ids: Annotated[list[CellId], Field(max_length=MAX_CELLS)]
    start_year: int
    end_year: int
    series: Annotated[list[YearPoint], Field(max_length=MAX_SERIES_YEARS)]
    trends: dict[TrendKey, TrendOut]
    insights: list[InsightOut]
    quality: QualityOut
    attribution: Annotated[str, StringConstraints(min_length=1, max_length=100)] = DATA_SOURCE


class ErrorResponse(_Model):
    code: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=40)]
    message: Annotated[str, StringConstraints(min_length=1, max_length=300)]

    @field_validator("message")
    @classmethod
    def _safe_message(cls, message: str) -> str:
        lowered = message.lower()
        if any(part in lowered for part in _FORBIDDEN_MESSAGE_PARTS):
            raise ValueError("message must not contain URLs, paths, credentials or stack traces.")
        return message


def _validate_years(request: AnalysisRequest) -> None:
    if request.start_year < HISTORY_START:
        raise ValueError(f"start_year must be {HISTORY_START} or later.")
    if request.end_year < request.start_year:
        raise ValueError("end_year must not be earlier than start_year.")
    if request.end_year - request.start_year + 1 < MIN_RANGE_YEARS:
        raise ValueError(f"The year range must span at least {MIN_RANGE_YEARS} years.")


def _resolve_region(request: AnalysisRequest) -> list[str]:
    point = (request.lat, request.lon)
    box = (request.south, request.west, request.north, request.east)
    point_count = sum(value is not None for value in point)
    box_count = sum(value is not None for value in box)
    if point_count and box_count:
        raise ValueError(
            "Specify a point (lat, lon) or a box (south, west, north, east), not both."
        )
    if point_count:
        if point_count != 2:
            raise ValueError("A point requires both lat and lon.")
        try:
            return [cell_id(request.lat, request.lon)]
        except RegionError as exc:
            raise ValueError(str(exc)) from None
    if box_count:
        if box_count != 4:
            raise ValueError("A box requires all of south, west, north and east.")
        if not (request.south < request.north and request.west < request.east):
            raise ValueError("A box requires south < north and west < east.")
        try:
            return cells_in_box(request.south, request.west, request.north, request.east)
        except RegionError as exc:
            raise ValueError(str(exc)) from None
    raise ValueError("Specify a point (lat, lon) or a box (south, west, north, east).")
