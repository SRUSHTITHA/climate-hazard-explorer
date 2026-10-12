import logging
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from app.services.open_meteo import ARCHIVE_URL, UpstreamError, fetch_daily_tmax
from app.services.regions import RegionError

Handler = Callable[[httpx.Request], httpx.Response]


def _full_year_payload(
    year: int, *, unit: str = "°C", values: list[float | None] | None = None
) -> dict[str, Any]:
    days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    times = [(date(year, 1, 1) + timedelta(days=index)).isoformat() for index in range(days)]
    values = values if values is not None else [42.0] * days
    return {
        "latitude": 28.5,
        "longitude": 77.25,
        "elevation": 243.0,
        "utc_offset_seconds": 19800,
        "timezone": "Asia/Kolkata",
        "timezone_abbreviation": "GMT+5:30",
        "daily_units": {"time": "iso8601", "temperature_2m_max": unit},
        "daily": {"time": times, "temperature_2m_max": values},
    }


def _client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: recorded.append(seconds))
    return recorded


def _success_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_full_year_payload(2024))


def _fail_if_called(request: httpx.Request) -> httpx.Response:
    pytest.fail("network was attempted")


def test_success_returns_validated_payload_preserving_null() -> None:
    payload = _full_year_payload(2024)
    payload["daily"]["temperature_2m_max"][100] = None
    client = _client(lambda _: httpx.Response(200, json=payload))
    result = fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert len(result["tmax"]) == 366
    assert result["tmax"][100] is None
    assert result["tmax"][0] == 42.0
    assert result["dates"][0] == "2024-01-01"
    assert result["grid_lat"] == 28.5
    assert result["grid_lon"] == 77.25
    assert result["elevation"] == 243.0
    assert result["utc_offset_seconds"] == 19800


def test_retries_once_on_429_then_succeeds(sleeps: list[float]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "2"}, json={"error": True})
        return httpx.Response(200, json=_full_year_payload(2024))

    client = _client(handler)
    fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert calls == 2
    assert sleeps == [2.0]


def test_gives_up_after_three_500s(sleeps: list[float]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": True})

    client = _client(handler)
    with pytest.raises(UpstreamError):
        fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert calls == 3
    assert sleeps == [1.0, 2.0]


def test_transport_timeout_then_success(sleeps: list[float]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("connection timed out", request=request)
        return httpx.Response(200, json=_full_year_payload(2024))

    client = _client(handler)
    result = fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert calls == 2
    assert sleeps == [1.0]
    assert len(result["tmax"]) == 366


def test_400_raises_immediately_and_logs_reason_server_side(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            400, json={"error": True, "reason": "Invalid value: bad variable tempeture_2m_max"}
        )

    with caplog.at_level(logging.WARNING):
        client = _client(handler)
        with pytest.raises(UpstreamError) as excinfo:
            fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert calls == 1
    assert "tempeture_2m_max" not in str(excinfo.value)
    assert "bad variable" not in str(excinfo.value)
    assert "tempeture_2m_max" in caplog.text


@pytest.mark.parametrize(
    "sabotage",
    [
        "malformed-json",
        "not-an-object",
        "missing-daily",
        "time-not-list",
        "value-not-number",
        "mismatched-lengths",
        "wrong-length",
        "wrong-unit",
    ],
)
def test_validation_failures_raise_upstream_error(sabotage: str) -> None:
    payload = _full_year_payload(2024)
    if sabotage == "malformed-json":
        response = httpx.Response(200, text="not json")
    elif sabotage == "not-an-object":
        response = httpx.Response(200, json=[1, 2, 3])
    elif sabotage == "missing-daily":
        del payload["daily"]
        response = httpx.Response(200, json=payload)
    elif sabotage == "time-not-list":
        payload["daily"]["time"] = "nope"
        response = httpx.Response(200, json=payload)
    elif sabotage == "value-not-number":
        payload["daily"]["temperature_2m_max"][0] = "hot"
        response = httpx.Response(200, json=payload)
    elif sabotage == "mismatched-lengths":
        payload["daily"]["time"] = payload["daily"]["time"][:-1]
        response = httpx.Response(200, json=payload)
    elif sabotage == "wrong-length":
        payload["daily"]["time"] = payload["daily"]["time"][:-1]
        payload["daily"]["temperature_2m_max"] = payload["daily"]["temperature_2m_max"][:-1]
        response = httpx.Response(200, json=payload)
    else:
        payload["daily_units"]["temperature_2m_max"] = "K"
        response = httpx.Response(200, json=payload)
    client = _client(lambda _: response)
    with pytest.raises(UpstreamError):
        fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)


@pytest.mark.parametrize(
    ("start_year", "end_year"),
    [
        (2024, 2023),
        (1939, 1939),
        (2024, date.today().year + 1),
        (1900, 1950),
    ],
)
def test_invalid_year_ranges_raise_valueerror_without_network(
    start_year: int, end_year: int
) -> None:
    client = _client(_fail_if_called)
    with pytest.raises(ValueError):
        fetch_daily_tmax("28.50_77.25", start_year, end_year, client=client)


def test_request_has_exactly_the_fixed_parameters_and_constant_host() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_full_year_payload(2024))

    client = _client(handler)
    fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    request = captured["request"]
    assert request.url.host == "archive-api.open-meteo.com"
    assert request.url.scheme == "https"
    assert str(request.url).startswith(ARCHIVE_URL + "?")
    params = request.url.params
    assert params["latitude"] == "28.5"
    assert params["longitude"] == "77.25"
    assert params["start_date"] == "2024-01-01"
    assert params["end_date"] == "2024-12-31"
    assert params["daily"] == "temperature_2m_max"
    assert params["temperature_unit"] == "celsius"
    assert params["timezone"] == "auto"
    assert params["models"] == "era5"
    assert len(params) == 8


def test_injected_client_stays_open() -> None:
    client = _client(_success_handler)
    fetch_daily_tmax("28.50_77.25", 2024, 2024, client=client)
    assert not client.is_closed


@pytest.mark.parametrize("cell_id", ["abc", "28.50", "999.00_0.00", "28.50_77.25_1", "x_y"])
def test_invalid_cell_ids_fail_in_regions_before_network(cell_id: str) -> None:
    client = _client(_fail_if_called)
    with pytest.raises(RegionError):
        fetch_daily_tmax(cell_id, 2024, 2024, client=client)
