"""Tests for forecast.py.

All Open-Meteo network calls are mocked, so this suite runs offline.
"""

import datetime as dt

import numpy as np
import pytest

import forecast


# ---- _validate_date ---------------------------------------------------

def test_validate_date_accepts_today():
    target, days_ahead = forecast._validate_date(dt.date.today())
    assert target == dt.date.today()
    assert days_ahead == 0


def test_validate_date_accepts_iso_string():
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    target, days_ahead = forecast._validate_date(tomorrow.isoformat())
    assert target == tomorrow
    assert days_ahead == 1


def test_validate_date_rejects_past():
    yesterday = dt.date.today() - dt.timedelta(days=1)
    with pytest.raises(forecast.DateOutOfRangeError):
        forecast._validate_date(yesterday)


def test_validate_date_accepts_last_valid_day():
    last_valid = dt.date.today() + dt.timedelta(
        days=forecast.MAX_FORECAST_DAYS - 1
    )
    target, days_ahead = forecast._validate_date(last_valid)
    assert target == last_valid
    assert days_ahead == forecast.MAX_FORECAST_DAYS - 1


def test_validate_date_rejects_too_far_ahead():
    too_far = dt.date.today() + dt.timedelta(days=forecast.MAX_FORECAST_DAYS)
    with pytest.raises(forecast.DateOutOfRangeError):
        forecast._validate_date(too_far)


# ---- geocode ------------------------------------------------------------

class FakeResponse:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_geocode_strips_country_qualifier(monkeypatch):
    # The real API ignores a trailing ", Country" and returns no results,
    # so geocode() should search on the place name alone.
    captured = {}

    def fake_get(url, params):
        captured["params"] = params
        return FakeResponse({
            "results": [{
                "name": "Manchester",
                "country": "United Kingdom",
                "latitude": 53.48,
                "longitude": -2.24,
            }]
        })

    monkeypatch.setattr(forecast._retry_session, "get", fake_get)

    place = forecast.geocode("Manchester, UK")

    assert captured["params"]["name"] == "Manchester"
    assert place == {
        "name": "Manchester",
        "country": "United Kingdom",
        "latitude": 53.48,
        "longitude": -2.24,
    }


def test_geocode_raises_when_no_results(monkeypatch):
    monkeypatch.setattr(
        forecast._retry_session,
        "get",
        lambda url, params: FakeResponse({"results": []}),
    )

    with pytest.raises(forecast.LocationNotFoundError):
        forecast.geocode("Nowhereville123xyz")


# ---- get_weather_summary --------------------------------------------

class FakeVariable:
    def __init__(self, values):
        self._values = values

    def ValuesAsNumpy(self):
        return np.array(self._values)


class FakeDaily:
    """Mimics the openmeteo_requests Daily() flatbuffer accessor."""

    def __init__(self, start_timestamp, variable_values):
        self._start = start_timestamp
        self._variables = [FakeVariable(v) for v in variable_values]
        self._num_days = len(variable_values[0])

    def Time(self):
        return self._start

    def TimeEnd(self):
        return self._start + 86400 * self._num_days

    def Interval(self):
        return 86400

    def Variables(self, index):
        return self._variables[index]


class FakeWeatherResponse:
    def __init__(self, daily):
        self._daily = daily

    def Daily(self):
        return self._daily

    def Timezone(self):
        return b"UTC"


def test_get_weather_summary_formats_forecast(monkeypatch):
    today_start = int(
        dt.datetime.combine(
            dt.date.today(), dt.time(), tzinfo=dt.timezone.utc
        ).timestamp()
    )
    daily = FakeDaily(
        start_timestamp=today_start,
        variable_values=[
            [3],     # weather_code -> "overcast"
            [19.5],  # temperature_2m_max
            [8.1],   # temperature_2m_min
            [0.0],   # precipitation_sum
            [0],     # precipitation_probability_max
            [8.7],   # wind_speed_10m_max
        ],
    )

    monkeypatch.setattr(
        forecast,
        "geocode",
        lambda location: {
            "name": "Berlin",
            "country": "Germany",
            "latitude": 52.52,
            "longitude": 13.4,
        },
    )
    monkeypatch.setattr(
        forecast._openmeteo,
        "weather_api",
        lambda url, params: [FakeWeatherResponse(daily)],
    )

    summary = forecast.get_weather_summary("Berlin")

    assert "Berlin, Germany" in summary
    assert "overcast" in summary
    assert "19.5°C" in summary
    assert "8.1°C" in summary
    assert "8.7 km/h" in summary


def test_get_weather_summary_rejects_past_date():
    with pytest.raises(forecast.DateOutOfRangeError):
        forecast.get_weather_summary("Berlin", "2000-01-01")


def test_get_weather_summary_unknown_weather_code(monkeypatch):
    today_start = int(
        dt.datetime.combine(
            dt.date.today(), dt.time(), tzinfo=dt.timezone.utc
        ).timestamp()
    )
    daily = FakeDaily(
        start_timestamp=today_start,
        variable_values=[
            [-1],  # not a real WMO code
            [20.0],
            [10.0],
            [0.0],
            [0],
            [5.0],
        ],
    )

    monkeypatch.setattr(
        forecast,
        "geocode",
        lambda location: {
            "name": "Nowhere",
            "country": "",
            "latitude": 0.0,
            "longitude": 0.0,
        },
    )
    monkeypatch.setattr(
        forecast._openmeteo,
        "weather_api",
        lambda url, params: [FakeWeatherResponse(daily)],
    )

    summary = forecast.get_weather_summary("Nowhere")

    assert "unknown conditions" in summary


# ---- scoring helpers ----------------------------------------------------

def test_temp_score_within_range_is_perfect():
    assert forecast._temp_score(20, (15, 25)) == 100.0


def test_temp_score_decays_outside_range():
    assert forecast._temp_score(5, (15, 25)) == 20.0  # 10°C below -> -80
    assert forecast._temp_score(30, (15, 25)) == 60.0  # 5°C above -> -40


def test_inverse_score():
    assert forecast._inverse_score(0) == 100.0
    assert forecast._inverse_score(80) == 20.0
    assert forecast._inverse_score(150) == 0.0  # clamped, not negative


def test_wind_score():
    assert forecast._wind_score(5) == 100.0
    assert forecast._wind_score(30) == 60.0  # 10 km/h over -> -40


# ---- activity name resolution -------------------------------------------

def test_resolve_activity_accepts_canonical_name():
    assert forecast._resolve_activity("running") == "running"


def test_resolve_activity_is_case_insensitive():
    assert forecast._resolve_activity("RUNNING") == "running"


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("run", "running"),
        ("jog", "running"),
        ("swim", "beach"),
        ("sunbathing", "beach"),
        ("stars", "stargazing"),
        ("picnicking", "picnic"),
    ],
)
def test_resolve_activity_accepts_synonyms(alias, expected):
    assert forecast._resolve_activity(alias) == expected


def test_resolve_activity_rejects_unknown_name():
    with pytest.raises(ValueError):
        forecast._resolve_activity("skiing")


# ---- recommend_best_day / get_best_day_summary -------------------------

def test_recommend_best_day_rejects_unknown_activity():
    with pytest.raises(ValueError):
        forecast.recommend_best_day("Anywhere", "skiing")


def test_recommend_best_day_ranks_best_first(monkeypatch):
    today_start = int(
        dt.datetime.combine(
            dt.date.today(), dt.time(), tzinfo=dt.timezone.utc
        ).timestamp()
    )
    # Three days engineered to give picnic scores of 100, 64, 28 (in that
    # column order) — see _temp_score/_inverse_score/_wind_score above.
    daily = FakeDaily(
        start_timestamp=today_start,
        variable_values=[
            [1, 2, 3],          # weather_code
            [20, 5, 30],        # temperature_2m_max
            [20, 5, 30],        # temperature_2m_min (== max, for a clean avg)
            [0, 80, 50],        # precipitation_probability_max
            [5, 30, 15],        # wind_speed_10m_max
            [50, 50, 50],       # cloud_cover_mean (irrelevant to picnic)
        ],
    )

    monkeypatch.setattr(
        forecast,
        "geocode",
        lambda location: {
            "name": "Manchester",
            "country": "United Kingdom",
            "latitude": 53.48,
            "longitude": -2.24,
        },
    )
    monkeypatch.setattr(
        forecast._openmeteo,
        "weather_api",
        lambda url, params: [FakeWeatherResponse(daily)],
    )

    result = forecast.recommend_best_day("Manchester, UK", "picnic", days=3)
    ranked = result["ranked_days"]
    today = dt.date.today()

    assert [day["score"] for day in ranked] == [100.0, 64.0, 28.0]
    # Best day is today, second-best is today+2, worst is today+1.
    assert [day["date"] for day in ranked] == [
        today,
        today + dt.timedelta(days=2),
        today + dt.timedelta(days=1),
    ]


def test_get_best_day_summary_formats_output(monkeypatch):
    today_start = int(
        dt.datetime.combine(
            dt.date.today(), dt.time(), tzinfo=dt.timezone.utc
        ).timestamp()
    )
    daily = FakeDaily(
        start_timestamp=today_start,
        variable_values=[[0], [20.0], [20.0], [0.0], [5.0], [10.0]],
    )

    monkeypatch.setattr(
        forecast,
        "geocode",
        lambda location: {
            "name": "Manchester",
            "country": "United Kingdom",
            "latitude": 53.48,
            "longitude": -2.24,
        },
    )
    monkeypatch.setattr(
        forecast._openmeteo,
        "weather_api",
        lambda url, params: [FakeWeatherResponse(daily)],
    )

    summary = forecast.get_best_day_summary("Manchester, UK", "picnic", days=1)

    assert "🧺" in summary
    assert "picnic" in summary
    assert "Manchester, United Kingdom" in summary
    assert "100/100" in summary


def test_get_best_day_summary_accepts_synonym(monkeypatch):
    today_start = int(
        dt.datetime.combine(
            dt.date.today(), dt.time(), tzinfo=dt.timezone.utc
        ).timestamp()
    )
    daily = FakeDaily(
        start_timestamp=today_start,
        variable_values=[[0], [12.0], [12.0], [0.0], [5.0], [10.0]],
    )

    monkeypatch.setattr(
        forecast,
        "geocode",
        lambda location: {
            "name": "Berlin",
            "country": "Germany",
            "latitude": 52.52,
            "longitude": 13.4,
        },
    )
    monkeypatch.setattr(
        forecast._openmeteo,
        "weather_api",
        lambda url, params: [FakeWeatherResponse(daily)],
    )

    # "run" is a synonym for "running" — the output should use the
    # canonical name and its emoji, not the raw input.
    summary = forecast.get_best_day_summary("Berlin", "run", days=1)

    assert "🏃" in summary
    assert "running" in summary
