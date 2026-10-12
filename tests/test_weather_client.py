"""Offline tests for the reusable weather API client."""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests

from src.weather_client import WeatherForecastClient, WeatherRequestError


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def geocoding_sample() -> dict[str, Any]:
    """Load the saved geocoding response used by the notebook."""
    path = PROJECT_ROOT / "samples" / "geocoding_sample.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def forecast_sample() -> dict[str, Any]:
    """Load the saved forecast response used by the notebook."""
    path = PROJECT_ROOT / "samples" / "forecast_sample.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_response(
    payload: dict[str, Any], status_code: int = 200
) -> requests.Response:
    """Build a Requests response without making a network call."""
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode("utf-8")
    response.headers["Content-Type"] = "application/json"
    response.url = "https://example.test"
    return response


def test_parse_candidates_from_saved_sample(
    geocoding_sample: dict[str, Any],
) -> None:
    candidates = WeatherForecastClient.parse_candidates(geocoding_sample)

    assert len(candidates) == 1
    assert candidates[0]["name"] == "Dresden"
    assert candidates[0]["latitude"] == pytest.approx(51.0504)
    assert candidates[0]["longitude"] == pytest.approx(13.7373)


def test_parse_candidates_handles_missing_results() -> None:
    assert WeatherForecastClient.parse_candidates({}) == []


def test_parse_candidates_ignores_incomplete_entries() -> None:
    payload = {
        "results": [
            {"name": "Incomplete"},
            {"name": "Complete", "latitude": 1.0, "longitude": 2.0},
            "not a location",
        ]
    }

    assert WeatherForecastClient.parse_candidates(payload) == [
        {"name": "Complete", "latitude": 1.0, "longitude": 2.0}
    ]


def test_parse_candidates_rejects_non_list_results() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        WeatherForecastClient.parse_candidates({"results": "invalid"})


def test_parse_forecast_from_saved_sample(
    forecast_sample: dict[str, Any],
) -> None:
    frame = WeatherForecastClient.parse_forecast(forecast_sample)

    assert len(frame) == 3
    assert frame.loc[0, "Date (local)"] == pd.Timestamp("2026-10-12")
    assert frame.loc[0, "Max temperature (°C)"] == pytest.approx(15.4)
    assert frame.loc[1, "Min temperature (°C)"] == pytest.approx(6.7)
    assert frame.loc[1, "Precipitation (mm)"] == pytest.approx(3.4)
    assert frame.loc[1, "Max wind speed (km/h)"] == pytest.approx(19.8)
    assert frame.loc[1, "Weather"] == "Slight rain"


def test_weather_description_known_and_unknown_codes() -> None:
    assert WeatherForecastClient.weather_description(0) == "Clear sky"
    assert WeatherForecastClient.weather_description(99) == (
        "Thunderstorm with heavy hail"
    )
    assert WeatherForecastClient.weather_description(987) == (
        "Unknown weather code (987)"
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "missing its daily object"),
        ({"daily": {"time": ["2026-10-12"]}}, "missing daily fields"),
        (
            {
                "daily": {
                    "time": ["2026-10-12"],
                    "temperature_2m_max": "not an array",
                    "temperature_2m_min": [1],
                    "precipitation_sum": [0],
                    "wind_speed_10m_max": [2],
                    "weather_code": [0],
                }
            },
            "must be arrays",
        ),
    ],
)
def test_parse_forecast_rejects_invalid_payloads(
    payload: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        WeatherForecastClient.parse_forecast(payload)


def test_parse_forecast_rejects_inconsistent_array_lengths(
    forecast_sample: dict[str, Any],
) -> None:
    payload = json.loads(json.dumps(forecast_sample))
    payload["daily"]["temperature_2m_max"].pop()

    with pytest.raises(ValueError, match="inconsistent lengths"):
        WeatherForecastClient.parse_forecast(payload)


def test_geocode_uses_and_caches_saved_response(
    geocoding_sample: dict[str, Any],
) -> None:
    calls: list[dict[str, Any]] = []

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        calls.append({"url": url, "params": params, "timeout": timeout})
        return make_response(geocoding_sample)

    client = WeatherForecastClient(requester=requester)

    assert client.geocode("Dresden")[0]["name"] == "Dresden"
    assert client.geocode("Dresden")[0]["name"] == "Dresden"
    assert len(calls) == 1
    assert calls[0]["params"]["name"] == "Dresden"
    assert calls[0]["timeout"] == 8.0


def test_geocode_rejects_empty_name() -> None:
    client = WeatherForecastClient()

    with pytest.raises(ValueError, match="must not be empty"):
        client.geocode("  ")


def test_get_forecast_sends_expected_parameters() -> None:
    calls: list[dict[str, Any]] = []

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        calls.append({"url": url, "params": params, "timeout": timeout})
        return make_response({"daily": {}})

    client = WeatherForecastClient(timeout=4.0, requester=requester)
    client.get_forecast(51.05, 13.74, 7)

    assert calls[0]["url"] == client.FORECAST_URL
    assert calls[0]["params"]["latitude"] == 51.05
    assert calls[0]["params"]["longitude"] == 13.74
    assert calls[0]["params"]["forecast_days"] == 7
    assert calls[0]["params"]["timezone"] == "auto"
    assert "temperature_2m_max" in calls[0]["params"]["daily"]
    assert calls[0]["timeout"] == 4.0


def test_get_forecast_rejects_zero_days() -> None:
    client = WeatherForecastClient()

    with pytest.raises(ValueError, match="at least 1"):
        client.get_forecast(0.0, 0.0, 0)


def test_request_json_retries_server_error_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = [
        make_response({"error": "temporary"}, status_code=503),
        make_response({"ok": True}),
    ]
    calls = 0
    delays: list[float] = []

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        nonlocal calls
        response = responses[calls]
        calls += 1
        return response

    monkeypatch.setattr("src.weather_client.time.sleep", delays.append)
    client = WeatherForecastClient(
        max_retries=2, backoff_seconds=0.25, requester=requester
    )

    payload, metadata = client.request_json("https://example.test", {})

    assert payload == {"ok": True}
    assert metadata["status_code"] == 200
    assert calls == 2
    assert delays == [0.25]


def test_request_json_caps_retries_and_raises_custom_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        nonlocal calls
        calls += 1
        raise requests.ConnectionError("simulated offline")

    monkeypatch.setattr("src.weather_client.time.sleep", lambda _: None)
    client = WeatherForecastClient(
        max_retries=99, backoff_seconds=0, requester=requester
    )

    with pytest.raises(WeatherRequestError, match="3 attempt"):
        client.request_json("https://example.test", {})

    assert calls == 3


def test_request_json_does_not_retry_client_errors() -> None:
    calls = 0

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        nonlocal calls
        calls += 1
        return make_response({"error": "bad request"}, status_code=400)

    client = WeatherForecastClient(max_retries=2, requester=requester)

    with pytest.raises(WeatherRequestError, match="status 400"):
        client.request_json("https://example.test", {})

    assert calls == 1


def test_met_norway_requires_real_contact_email() -> None:
    client = WeatherForecastClient(contact_email="YOUR_UNIVERSITY_EMAIL")

    with pytest.raises(ValueError, match="real university email"):
        client.get_met_norway_forecast(51.05049, 13.73739)


def test_met_norway_identifies_client_and_rounds_coordinates() -> None:
    calls: list[dict[str, Any]] = []

    def requester(
        url: str,
        params: dict[str, Any],
        timeout: float,
        headers: dict[str, str],
    ) -> requests.Response:
        calls.append(
            {"url": url, "params": params, "headers": headers}
        )
        return make_response({"properties": {"timeseries": []}})

    client = WeatherForecastClient(
        contact_email="student@example.edu", requester=requester
    )
    client.get_met_norway_forecast(51.05049, 13.73739)

    assert calls[0]["url"] == client.MET_NORWAY_URL
    assert calls[0]["params"] == {"lat": 51.0505, "lon": 13.7374}
    assert "student@example.edu" in calls[0]["headers"]["User-Agent"]
