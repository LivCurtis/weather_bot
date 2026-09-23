# weather_bot

Looks up a place name via the [Open-Meteo](https://open-meteo.com/) geocoding and forecast APIs, and returns either a plain-language weather summary for a given date, or a recommendation for the best day this week to do something outdoors.

## Setup

This project uses a Python [virtual environment](https://docs.python.org/3/library/venv.html) to keep its dependencies isolated from the rest of your system. This is standard practice for Python projects, and required on some systems (e.g. Homebrew's Python on macOS refuses `pip install` outside of one).

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

The `source`/`Activate` step needs to be re-run in each new terminal session before using the project (you'll see `(.venv)` appear in your prompt when it's active).

## Usage

```bash
python main.py --location "Manchester, UK" --date 2026-09-30
```

`--date` defaults to today and accepts any `YYYY-MM-DD` date up to 16 days ahead (the limit of Open-Meteo's forecast APIs — past dates and dates further out aren't supported).

```
$ python main.py --location Berlin
Berlin, Germany on 2026-09-23: overcast, with a high of 19.5°C and a low of 8.1°C. 0% chance of precipitation (0.0 mm expected), winds up to 8.7 km/h.
```

The underlying function can also be imported and used directly. `date` is optional and defaults to today:

```python
from forecast import get_weather_summary

get_weather_summary("Tokyo", "2026-09-30")
get_weather_summary("Tokyo")
```

It raises `LocationNotFoundError` if the place name can't be resolved, and `DateOutOfRangeError` for dates outside the forecast window.

### Best day for an activity

```bash
python main.py --location "Manchester, UK" --activity picnic --days 7
```

```
$ python main.py --location Barcelona --activity beach
🏖️ Best day for beach in Barcelona, Spain over the next 7 days: Friday 2026-09-25 (mainly clear, suitability 100/100).
```

`--activity` accepts `picnic`, `running`, `beach`, `stargazing`, `hiking`, `sightseeing`, `cycling`, or `gardening`, plus common synonyms (`run`, `jog`, `swim`, `sunbathing`, `stars`, `astronomy`, `hike`, `trek`, `camping`, `walking`, `tour`, `bike`, `garden`, …), case-insensitively — see `ACTIVITY_ALIASES` in `forecast.py` for the full list. Each day in the window is scored out of 100 on temperature, precipitation chance, wind, and (for stargazing) cloud cover, weighted by what that activity actually needs — see `ACTIVITIES` in `forecast.py` to tweak the profiles or add your own. `--days` defaults to 7 and is capped at 16.

This is also available as a function:

```python
from forecast import get_best_day_summary, recommend_best_day

get_best_day_summary("Tokyo", "running", days=10)
recommend_best_day("Tokyo", "running", days=10)  # full ranked breakdown
```

Geocoding and forecast responses are cached locally (`.cache`) for an hour and retried automatically on failure.

## Tests

The test suite mocks all network calls, so it runs offline:

```bash
pip install -r requirements-dev.txt
pytest
```

## Project layout

| File | Purpose |
| --- | --- |
| `forecast.py` | Geocoding, forecast lookup, and summary formatting |
| `main.py` | Command-line entry point |
| `tests/` | Unit tests |
| `requirements.txt` | Runtime dependencies |
| `requirements-dev.txt` | Runtime + test dependencies |

## Troubleshooting

- `ModuleNotFoundError: No module named 'openmeteo_requests'` (or similar) — the virtual environment either hasn't been created, hasn't been activated, or the dependencies haven't been installed. Repeat the setup steps above.
- If your editor's "Run" button still fails after activating the venv in your terminal, point its Python interpreter setting at `.venv/bin/python` (`.venv\Scripts\python.exe` on Windows) rather than the system Python.
- `Could not find a location matching '...'` — the geocoding API matches on place name only, so very small towns or unusual spellings may not resolve. Try a nearby larger city, or a different spelling.
