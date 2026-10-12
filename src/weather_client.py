"""Reusable clients and parsers for the approved weather APIs."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any, ClassVar

import pandas as pd
import requests


class WeatherRequestError(Exception):
    """Raised when a weather API request fails or returns invalid JSON."""


class WeatherForecastClient:
    """Request, cache, and parse weather data from the approved APIs."""

    GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    MET_NORWAY_URL = (
        "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    )
    MAX_RETRIES = 2
    BACKOFF_SECONDS = 0.5
    WMO_DESCRIPTIONS: ClassVar[dict[int, str]] = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }

    def __init__(
        self,
        contact_email: str = "",
        timeout: float = 10.0,
        max_retries: int = MAX_RETRIES,
        backoff_seconds: float = BACKOFF_SECONDS,
        requester: Callable[..., requests.Response] | None = None,
    ) -> None:
        """Create a client with a timeout, retry limit, and optional test transport."""
        self.timeout = timeout
        self.max_retries = min(max(max_retries, 0), self.MAX_RETRIES)
        self.backoff_seconds = backoff_seconds
        self.requester = requester if requester is not None else requests.get
        self.contact_email = contact_email.strip()
        self.headers = {"User-Agent": "WeatherForecastAssignment/1.0"}
        if self.contact_email and self.contact_email != "YOUR_UNIVERSITY_EMAIL":
            self.headers["User-Agent"] = (
                f"WeatherForecastAssignment/1.0 ({self.contact_email})"
            )
        self._geocoding_cache: dict[
            tuple[str, int, str], tuple[dict[str, Any], dict[str, Any]]
        ] = {}

    def request_json(
        self,
        url: str,
        params: dict[str, Any],
        timeout: float | None = None,
        retries: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """GET JSON with a timeout, bounded retries, and response metadata."""
        request_timeout = self.timeout if timeout is None else timeout
        retry_limit = self.max_retries if retries is None else min(
            max(retries, 0), self.MAX_RETRIES
        )
        attempts = retry_limit + 1
        request_headers = headers if headers is not None else self.headers
        last_error: Exception | None = None
        for attempt in range(attempts):
            response: requests.Response | None = None
            started = time.perf_counter()
            try:
                response = self.requester(
                    url,
                    params=params,
                    timeout=request_timeout,
                    headers=request_headers,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("The API response JSON must be an object.")
                metadata = {
                    "status_code": response.status_code,
                    "content_type": response.headers.get(
                        "Content-Type", "not provided"
                    ),
                    "response_time_seconds": time.perf_counter() - started,
                }
                return payload, metadata
            except requests.HTTPError as error:
                status = response.status_code if response is not None else None
                if status is None or status < 500:
                    raise WeatherRequestError(
                        f"HTTP request to {url} failed with status "
                        f"{status}: {error}"
                    ) from error
                last_error = error
            except ValueError as error:
                raise WeatherRequestError(
                    f"Invalid JSON response from {url}: {error}"
                ) from error
            except requests.RequestException as error:
                last_error = error
            if attempt < attempts - 1:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise WeatherRequestError(
            f"GET {url} failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def request_json_urllib(
        self,
        url: str,
        params: dict[str, Any],
        timeout: float | None = None,
        retries: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """GET JSON using urllib with the same retry policy and metadata."""
        query_url = f"{url}?{urllib.parse.urlencode(params)}"
        request_timeout = self.timeout if timeout is None else timeout
        retry_limit = self.max_retries if retries is None else min(
            max(retries, 0), self.MAX_RETRIES
        )
        attempts = retry_limit + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            try:
                request = urllib.request.Request(
                    query_url, headers=self.headers, method="GET"
                )
                with urllib.request.urlopen(
                    request, timeout=request_timeout
                ) as response:
                    body = response.read()
                    metadata = {
                        "status_code": response.status,
                        "content_type": response.headers.get(
                            "Content-Type", "not provided"
                        ),
                        "response_time_seconds": time.perf_counter() - started,
                    }
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("The API response JSON must be an object.")
                return payload, metadata
            except urllib.error.HTTPError as error:
                if error.code < 500:
                    raise WeatherRequestError(
                        f"HTTP request to {url} failed with status "
                        f"{error.code}: {error}"
                    ) from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                raise WeatherRequestError(
                    f"Invalid JSON response from {url}: {error}"
                ) from error
            if attempt < attempts - 1:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise WeatherRequestError(
            f"GET {url} failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    def get_geocoding_payload(
        self, name: str, count: int = 10, language: str = "en"
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch and cache a geocoding response, including its metadata."""
        if not name.strip():
            raise ValueError("Location name must not be empty.")
        cache_key = (name, count, language)
        cached = self._geocoding_cache.get(cache_key)
        if cached is None:
            payload, metadata = self.request_json(
                self.GEOCODING_URL,
                {
                    "name": name,
                    "count": count,
                    "language": language,
                    "format": "json",
                },
                timeout=8.0,
            )
            cached = (payload, metadata)
            self._geocoding_cache[cache_key] = cached
        return cached

    def geocode(self, name: str) -> list[dict[str, Any]]:
        """Return validated location candidates for a name."""
        payload, _ = self.get_geocoding_payload(name)
        return self.parse_candidates(payload)

    @staticmethod
    def parse_candidates(
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return candidates with the fields required for a forecast lookup."""
        results = payload.get("results", [])
        if not isinstance(results, list):
            raise ValueError("Geocoding results must be a list when present.")
        return [
            result
            for result in results
            if isinstance(result, dict)
            and "name" in result
            and "latitude" in result
            and "longitude" in result
        ]

    def get_forecast(
        self, latitude: float, longitude: float, days: int
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch daily weather values for coordinates in their local timezone."""
        if days < 1:
            raise ValueError("Forecast days must be at least 1.")
        return self.request_json(
            self.FORECAST_URL,
            {
                "latitude": latitude,
                "longitude": longitude,
                "daily": (
                    "temperature_2m_max,temperature_2m_min,precipitation_sum,"
                    "wind_speed_10m_max,weather_code"
                ),
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=self.timeout,
        )

    @classmethod
    def weather_description(cls, code: int) -> str:
        """Translate an Open-Meteo WMO code to a readable description."""
        return cls.WMO_DESCRIPTIONS.get(
            code, f"Unknown weather code ({code})"
        )

    @classmethod
    def parse_forecast(cls, payload: dict[str, Any]) -> pd.DataFrame:
        """Validate daily arrays and return a DataFrame with units in headings."""
        daily = payload.get("daily")
        if not isinstance(daily, dict):
            raise ValueError("Forecast response is missing its daily object.")
        required = {
            "time": "Date (local)",
            "temperature_2m_max": "Max temperature (°C)",
            "temperature_2m_min": "Min temperature (°C)",
            "precipitation_sum": "Precipitation (mm)",
            "wind_speed_10m_max": "Max wind speed (km/h)",
            "weather_code": "WMO weather code",
        }
        missing = [key for key in required if key not in daily]
        if missing:
            raise ValueError(
                f"Forecast response is missing daily fields: {missing}"
            )
        if any(not isinstance(daily[key], list) for key in required):
            raise ValueError("Forecast daily fields must be arrays.")
        lengths = {len(daily[key]) for key in required}
        if len(lengths) != 1:
            raise ValueError("Forecast daily arrays have inconsistent lengths.")
        frame = pd.DataFrame(
            {label: daily[key] for key, label in required.items()}
        )
        frame["Date (local)"] = pd.to_datetime(frame["Date (local)"])
        frame["Weather"] = frame["WMO weather code"].map(
            cls.weather_description
        )
        return frame

    def get_met_norway_forecast(
        self, latitude: float, longitude: float
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Fetch MET Norway data with required contact and rounded coordinates."""
        if (
            not self.contact_email
            or self.contact_email == "YOUR_UNIVERSITY_EMAIL"
        ):
            raise ValueError(
                "Set contact_email to your real university email before "
                "contacting MET Norway."
            )
        return self.request_json(
            self.MET_NORWAY_URL,
            {"lat": round(latitude, 4), "lon": round(longitude, 4)},
            headers={
                "User-Agent": (
                    f"WeatherForecastAssignment/1.0 {self.contact_email}"
                )
            },
        )
