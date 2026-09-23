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

# Scoring profiles for recommend_best_day(). "ideal_temp" is the comfort
# range (°C) for the day's average temperature; "weights" say how much each
# factor (temp, precip chance, wind, cloud cover) matters for the activity,
# and must sum to 1.
ACTIVITIES = {
    "picnic": {
        "emoji": "🧺",
        "ideal_temp": (15, 25),
        "weights": {"temp": 0.4, "precip": 0.4, "wind": 0.2, "cloud": 0.0},
    },
    "running": {
        "emoji": "🏃",
        "ideal_temp": (8, 18),
        "weights": {"temp": 0.4, "precip": 0.3, "wind": 0.3, "cloud": 0.0},
    },
    "beach": {
        "emoji": "🏖️",
        "ideal_temp": (24, 32),
        "weights": {"temp": 0.5, "precip": 0.3, "wind": 0.2, "cloud": 0.0},
    },
    "stargazing": {
        "emoji": "🔭",
        "ideal_temp": (5, 25),
        "weights": {"temp": 0.1, "precip": 0.3, "wind": 0.1, "cloud": 0.5},
    },
    "hiking": {
        "emoji": "🥾",
        "ideal_temp": (10, 22),
        "weights": {"temp": 0.3, "precip": 0.4, "wind": 0.3, "cloud": 0.0},
    },
    "sightseeing": {
        "emoji": "🗺️",
        "ideal_temp": (12, 24),
        "weights": {"temp": 0.3, "precip": 0.5, "wind": 0.2, "cloud": 0.0},
    },
    "cycling": {
        "emoji": "🚴",
        "ideal_temp": (12, 24),
        "weights": {"temp": 0.3, "precip": 0.3, "wind": 0.4, "cloud": 0.0},
    },
    "gardening": {
        "emoji": "🌱",
        "ideal_temp": (15, 25),
        "weights": {"temp": 0.3, "precip": 0.5, "wind": 0.2, "cloud": 0.0},
    },
}

# Alternative spellings/phrasings that map onto an ACTIVITIES key.
ACTIVITY_ALIASES = {
    "picnicking": "picnic",
    "run": "running",
    "jog": "running",
    "jogging": "running",
    "beaching": "beach",
    "sunbathing": "beach",
    "swim": "beach",
    "swimming": "beach",
    "stars": "stargazing",
    "stargaze": "stargazing",
    "astronomy": "stargazing",
    "hike": "hiking",
    "trek": "hiking",
    "trekking": "hiking",
    "camping": "hiking",
    "sightsee": "sightseeing",
    "tour": "sightseeing",
    "touring": "sightseeing",
    "walking": "sightseeing",
    "bike": "cycling",
    "biking": "cycling",
    "bicycling": "cycling",
    "garden": "gardening",
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


def _temp_score(avg_temp, ideal_range):
    """100 within the ideal range, decaying 8 points per °C outside it."""
    low, high = ideal_range
    if low <= avg_temp <= high:
        return 100.0
    distance = low - avg_temp if avg_temp < low else avg_temp - high
    return max(0.0, 100 - distance * 8)


def _inverse_score(percentage):
    """100 at 0%, decaying to 0 at 100% — for precip chance/cloud cover."""
    return max(0.0, 100 - percentage)


def _wind_score(wind_speed_kmh, comfortable_max=20.0):
    """100 up to a comfortable speed, decaying 4 points per km/h beyond it."""
    if wind_speed_kmh <= comfortable_max:
        return 100.0
    return max(0.0, 100 - (wind_speed_kmh - comfortable_max) * 4)


def _resolve_activity(activity):
    """Normalize `activity` to a canonical ACTIVITIES key.

    Accepts a canonical name or a recognised synonym (see
    ACTIVITY_ALIASES), case-insensitively.
    """
    normalized = activity.strip().lower()
    if normalized in ACTIVITIES:
        return normalized
    if normalized in ACTIVITY_ALIASES:
        return ACTIVITY_ALIASES[normalized]

    valid = ", ".join(sorted(ACTIVITIES))
    raise ValueError(
        f"Unknown activity '{activity}'. Choose from: {valid} "
        "(synonyms like 'run' or 'swim' also work)."
    )


def recommend_best_day(location, activity, days=7):
    """Rank the next `days` forecastable days by suitability for `activity`.

    Args:
        location: a place name, e.g. "Manchester, UK".
        activity: one of the keys in ACTIVITIES (e.g. "picnic", "running",
            "beach", "stargazing"), or a recognised synonym (e.g. "run",
            "swim") — see ACTIVITY_ALIASES.
        days: how many days ahead to consider, capped at MAX_FORECAST_DAYS.

    Returns:
        A dict with "place" (as returned by geocode()), "activity" (the
        canonical activity name) and "ranked_days" — a list of {"date",
        "score", "condition", "temp_max"} dicts, best day first.

    Raises:
        ValueError: if `activity` isn't recognised.
        LocationNotFoundError: if `location` can't be geocoded.
    """
    activity = _resolve_activity(activity)
    days = max(1, min(days, MAX_FORECAST_DAYS))
    place = geocode(location)

    params = {
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "daily": [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "wind_speed_10m_max",
            "cloud_cover_mean",
        ],
        "timezone": "auto",
        "forecast_days": days,
    }
    response = _openmeteo.weather_api(FORECAST_URL, params=params)[0]
    daily = response.Daily()

    dates = pd.date_range(
        start=pd.to_datetime(daily.Time(), unit="s", utc=True),
        end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
        freq=pd.Timedelta(seconds=daily.Interval()),
        inclusive="left",
    ).tz_convert(response.Timezone().decode()).date

    # Variable order matches the "daily" list requested above.
    weather_codes = daily.Variables(0).ValuesAsNumpy()
    temp_max = daily.Variables(1).ValuesAsNumpy()
    temp_min = daily.Variables(2).ValuesAsNumpy()
    precip_chance = daily.Variables(3).ValuesAsNumpy()
    wind_max = daily.Variables(4).ValuesAsNumpy()
    cloud_cover = daily.Variables(5).ValuesAsNumpy()

    weights = ACTIVITIES[activity]["weights"]
    ideal_temp = ACTIVITIES[activity]["ideal_temp"]

    ranked_days = []
    for i, date in enumerate(dates):
        scores = {
            "temp": _temp_score((temp_max[i] + temp_min[i]) / 2, ideal_temp),
            "precip": _inverse_score(precip_chance[i]),
            "wind": _wind_score(wind_max[i]),
            "cloud": _inverse_score(cloud_cover[i]),
        }
        overall = sum(weights[factor] * scores[factor] for factor in weights)
        condition = WEATHER_CODES.get(
            int(weather_codes[i]), "unknown conditions"
        )
        ranked_days.append({
            "date": date,
            "score": round(overall, 1),
            "condition": condition,
            "temp_max": temp_max[i],
        })

    ranked_days.sort(key=lambda day: day["score"], reverse=True)
    return {"place": place, "activity": activity, "ranked_days": ranked_days}


def get_best_day_summary(location, activity, days=7):
    """Return a one-line recommendation for the best day to do `activity`.

    See recommend_best_day() for arguments and errors raised.
    """
    result = recommend_best_day(location, activity, days=days)
    place = result["place"]
    activity = result["activity"]
    best = result["ranked_days"][0]
    where = f"{place['name']}, {place['country']}".strip(", ")
    emoji = ACTIVITIES[activity]["emoji"]

    return (
        f"{emoji} Best day for {activity} in {where} over the next {days} "
        f"days: {best['date'].strftime('%A')} {best['date'].isoformat()} "
        f"({best['condition']}, high of {best['temp_max']:.1f}°C, "
        f"suitability {best['score']:.0f}/100)."
    )
