# weather_bot

Fetches an hourly temperature forecast from the [Open-Meteo](https://open-meteo.com/) API using the UK Met Office seamless model, and prints it as a pandas DataFrame.

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
python main.py
```

By default it forecasts 7 days of hourly `temperature_2m` for the coordinates set in `main.py` (`latitude`/`longitude` in `params`). Edit those values to target a different location.

Responses are cached locally (`.cache`) for an hour and retried automatically on failure.

## Troubleshooting

- `ModuleNotFoundError: No module named 'openmeteo_requests'` (or similar) — the virtual environment either hasn't been created, hasn't been activated, or the dependencies haven't been installed. Repeat the setup steps above.
- If your editor's "Run" button still fails after activating the venv in your terminal, point its Python interpreter setting at `.venv/bin/python` (`.venv\Scripts\python.exe` on Windows) rather than the system Python.
