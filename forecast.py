"""Look up a place and return a plain-language weather forecast summary."""

import datetime as dt

import openmeteo_requests
import pandas as pd
import requests_cache
from retry_requests import retry

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Open-Meteo's forecast APIs top out at 16 days ahead.
MAX_FORECAST_DAYS = 16

# WMO weather interpretation codes, as used by Open-Meteo.
# See https://open-meteo.com/en/docs
WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}

_cache_session = requests_cache.CachedSession(".cache", expire_after=3600)
_retry_session = retry(_cache_session, retries=5, backoff_factor=0.2)
_openmeteo = openmeteo_requests.Client(session=_retry_session)


class LocationNotFoundError(Exception):
    """Raised when a location name can't be resolved to coordinates."""


class DateOutOfRangeError(Exception):
    """Raised when the date falls outside the available forecast window."""


def geocode(location):
    """Resolve a place name to coordinates.

    Accepts either a bare name ("Manchester") or a qualified one
    ("Manchester, UK").

    Returns:
        A dict with "name", "country", "latitude" and "longitude".

    Raises:
        LocationNotFoundError: if the name can't be resolved.
    """
    # The geocoding API matches on place name only, so "City, Country"
    # style queries return nothing — use just the part before the comma.
    query = location.split(",")[0].strip()

    response = _retry_session.get(
        GEOCODING_URL,
        params={
            "name": query,
            "count": 1,
            "language": "en",
            "format": "json",
        },
    )
    response.raise_for_status()

    results = response.json().get("results")
    if not results:
        raise LocationNotFoundError(
            f"Could not find a location matching '{location}'"
        )

    result = results[0]
    return {
        "name": result["name"],
        "country": result.get("country", ""),
        "latitude": result["latitude"],
        "longitude": result["longitude"],
    }


def _validate_date(date):
    """Coerce `date` to a datetime.date and check it is forecastable."""
    target = dt.date.fromisoformat(date) if isinstance(date, str) else date
    days_ahead = (target - dt.date.today()).days

    if days_ahead < 0:
        raise DateOutOfRangeError(
            f"{target} is in the past — this function only covers "
            "forecasts, not historical weather."
        )
    if days_ahead >= MAX_FORECAST_DAYS:
        raise DateOutOfRangeError(
            f"{target} is more than {MAX_FORECAST_DAYS} days away — "
            "forecasts aren't available that far out."
        )

    return target, days_ahead


def get_weather_summary(location, date=None):
    """Return a one-line forecast summary for `location` on `date`.

    Args:
        location: a place name, e.g. "Manchester, UK".
        date: an ISO date string ("YYYY-MM-DD") or a datetime.date.
            Defaults to today.

    Returns:
        A human-readable summary string.

    Raises:
        LocationNotFoundError: if `location` can't be geocoded.
        DateOutOfRangeError: if `date` is in the past, or too far in the
            future for the forecast API to cover.
    """
    target_date, days_ahead = _validate_date(date or dt.date.today())
    place = geocode(location)

    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_probability_max",
            "wind_speed_10m_max",
        ],
        "timezone": "auto",
        "forecast_days": days_ahead + 1,
    }
    response = _openmeteo.weather_api(FORECAST_URL, params=params)[0]
    daily = response.Daily()

    daily_dates = pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    ).tz_convert(response.Timezone().decode())

    try:
        index = list(daily_dates.date).index(target_date)
    except ValueError:
        raise DateOutOfRangeError(
            f"No forecast data returned for {target_date}"
        )

    # Variable order matches the "daily" list requested above.
    code = int(daily.Variables(0).ValuesAsNumpy()[index])
    temp_max = daily.Variables(1).ValuesAsNumpy()[index]
    temp_min = daily.Variables(2).ValuesAsNumpy()[index]
    precip_sum = daily.Variables(3).ValuesAsNumpy()[index]
    precip_chance = daily.Variables(4).ValuesAsNumpy()[index]
    wind_max = daily.Variables(5).ValuesAsNumpy()[index]

    condition = WEATHER_CODES.get(code, "unknown conditions")
    where = f"{place['name']}, {place['country']}".strip(", ")

    return (
        f"{where} on {target_date.isoformat()}: {condition}, "
        f"with a high of {temp_max:.1f}°C and a low of "
        f"{temp_min:.1f}°C. {precip_chance:.0f}% chance of "
        f"precipitation ({precip_sum:.1f} mm expected), "
        f"winds up to {wind_max:.1f} km/h."
    )
