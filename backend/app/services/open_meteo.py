import datetime as dt
import logging
import time
from typing import Any
import httpx
from app.services.regions import cell_center

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
MAX_RETRY_AFTER_SECONDS = 5.0
MIN_YEAR = 1940
_LOGGER = logging.getLogger(__name__)

UPSTREAM_ERROR_MESSAGE = "Weather data is temporarily unavailable. Please try again later."

class UpstreamError(Exception):
    pass

def fetch_daily_tmax(
    cell_id: str, start_year: int, end_year: int, client: httpx.Client | None = None
) -> dict[str, Any]:
    _validate_year_range(start_year, end_year)
    lat, lon = cell_center(cell_id)
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{start_year}-01-01",
        "end_date": f"{end_year}-12-31",
        "daily": "temperature_2m_max",
        "temperature_unit": "celsius",
        "timezone": "auto",
        "models": "era5",
    }
    expected_days = (dt.date(end_year, 12, 31) - dt.date(start_year, 1, 1)).days + 1
    owns_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        return _fetch_with_retries(http, params, expected_days)
    finally:
        if owns_client:
            http.close()

def _validate_year_range(start_year: int, end_year: int) -> None:
    if start_year > end_year:
        raise ValueError("start_year must not be greater than end_year.")
    current = dt.date.today().year
    if start_year < MIN_YEAR or end_year > current:
        raise ValueError(f"Years must be between {MIN_YEAR} and {current}.")

def _fetch_with_retries(
    http: httpx.Client, params: dict[str, Any], expected_days: int
) -> dict[str, Any]:
    attempt = 0
    while True:
        delay: float | None = None
        try:
            response = http.get(ARCHIVE_URL, params=params, follow_redirects=False)
        except httpx.TransportError as exc:
            _LOGGER.warning("Open-Meteo request failed: %s", exc)
            delay = _retry_delay(attempt, None)
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from None
                return _validated_payload(data, expected_days)
            _LOGGER.warning(
                "Open-Meteo returned status %s: %s", response.status_code, response.text
            )
            if response.status_code != 429 and response.status_code < 500:
                raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
            delay = _retry_delay(attempt, response)
        if delay is None:
            raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
        time.sleep(delay)
        attempt += 1

def _retry_delay(attempt: int, response: httpx.Response | None) -> float | None:
    if attempt >= MAX_ATTEMPTS - 1:
        return None
    if response is not None:
        header = response.headers.get("Retry-After")
        if header is not None:
            try:
                return min(float(header), MAX_RETRY_AFTER_SECONDS)
            except ValueError:
                pass
    return BACKOFF_BASE_SECONDS * (2**attempt)

def _validated_payload(data: Any, expected_days: int) -> dict[str, Any]:
    daily = data.get("daily") if isinstance(data, dict) else None
    if not isinstance(daily, dict):
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    times = daily.get("time")
    values = daily.get("temperature_2m_max")
    if (
        not isinstance(times, list)
        or not isinstance(values, list)
        or len(times) != len(values)
        or not all(v is None or isinstance(v, (int, float)) for v in values)
    ):
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    units = data.get("daily_units")
    if not isinstance(units, dict) or units.get("temperature_2m_max") != "°C":
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    if len(times) != expected_days:
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    try:
        grid_lat = float(data["latitude"])
        grid_lon = float(data["longitude"])
        utc_offset = int(data["utc_offset_seconds"])
    except (KeyError, TypeError, ValueError):
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE) from None
    elevation = data.get("elevation")
    if elevation is not None and not isinstance(elevation, (int, float)):
        raise UpstreamError(UPSTREAM_ERROR_MESSAGE)
    return {
        "grid_lat": grid_lat,
        "grid_lon": grid_lon,
        "elevation": elevation,
        "utc_offset_seconds": utc_offset,
        "dates": times,
        "tmax": values,
    }
