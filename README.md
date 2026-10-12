# Weather Forecast Project

This repository contains two Python mini-projects:

1. A weather forecast client that geocodes a place with Open-Meteo, fetches a
   local-time daily forecast, and displays a table and chart.
2. An object-oriented Uganda tax engine with Decimal-based UGX values, versioned
   PAYE schedules, payroll, VAT, corporate income tax, and a scenario planner.

## Project files

- `weather_forecast.ipynb` — run the examples and view the report.
- `src/weather_client.py` — reusable `WeatherForecastClient` and
  `WeatherRequestError`.
- `uganda_tax_engine.ipynb` — tax-engine examples, analysis, and report.
- `src/tax_engine.py` — tax domain models, value objects, and calculators.
- `tests/test_weather_client.py` — offline pytest tests for the client.
- `tests/test_tax_engine.py` — tax boundary, validation, and property tests.
- `samples/` — saved geocoding and forecast JSON used by the tests.
- `requirements.txt` — packages needed by the client and notebook.
- `requirements-dev.txt` — project dependencies plus pytest, Jupyter, and
  Hypothesis.

## Set up on Windows

Use Python 3.10 or newer. From PowerShell, in the project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If PowerShell does not recognize `py`, install Python and enable its Python
Launcher, or create the virtual environment with your Python executable:

```powershell
python -m venv .venv
```

If script activation is restricted by your machine's PowerShell policy, you can
run the environment's Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Configure and run the notebooks

1. Open either notebook in Jupyter or VS Code and select the `.venv` Python
   kernel.
2. In `weather_forecast.ipynb`, set the location and candidate index. Before
   enabling the MET Norway request, enter your own university email in
   `CONTACT_EMAIL`.
3. In `uganda_tax_engine.ipynb`, review the tax date, schedule version, and
   example income values in its configuration cell. The assignment PAYE
   schedule is deliberately distinct from the published reference schedule;
   see the notebook discussion before interpreting its example results.
4. Choose **Restart & Run All**. The weather notebook makes live API requests
   and needs internet access. The tax notebook runs locally.

From PowerShell, you can also launch Jupyter from the project directory:

```powershell
python -m jupyter notebook weather_forecast.ipynb
```

Open `uganda_tax_engine.ipynb` the same way to run the tax project.

The notebook makes live API requests. Avoid repeatedly running its request
cells; honor provider rate limits and caching guidance. Location names and
coordinates are sent to the selected API providers.

## Run tests

With the project environment activated:

```powershell
python -m pytest tests -q
```

Or without activating it:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The weather tests use saved sample responses and mocked HTTP transports. The
tax tests use decimal-valued examples and Hypothesis-generated inputs. Both
test modules run offline and do not send requests to external services.

## Findings summary

- The client parses geocoding candidates, including responses with no
  `results`, and caches each lookup during a run.
- Forecast parsing validates the daily fields and array lengths, labels units,
  converts local date strings, and maps WMO weather codes to descriptions.
- Requests use timeouts and bounded retries for connection and server errors;
  client-side HTTP errors fail without retries. Final transport failures use
  `WeatherRequestError`.
- The notebook demonstrates both `urllib` and `requests`, reports live HTTP
  metadata, and handles invalid-city, invalid-coordinate, simulated-network,
  and tiny-timeout cases.
- The pytest suite covers the parsers, validation, caching, forecast query,
  retry behavior, and MET Norway identification/coordinate rounding, along
  with the tax engine boundaries and properties. The combined suite currently
  completes with **42 tests passed**.
- Live forecasts depend on the external APIs and are not guaranteed to be
  available or accurate. Open-Meteo free API use is subject to its current
  non-commercial terms and attribution requirements; MET Norway requires an
  identifying User-Agent and appropriate data attribution. Check both
  providers' current terms before using this code in a product.
- The tax engine uses an immutable, Decimal-backed UGX value object; an
  abstract `Tax` interface; versioned resident and non-resident PAYE schedules;
  composed payroll, VAT, and corporate tax calculators; and a salary/dividend
  scenario comparison. Tests exercise the assignment's PAYE boundaries and
  Hypothesis properties for non-negative, monotonic tax that does not exceed
  income. The assignment's supplied resident PAYE schedule differs from the
  published FY2025/26 table; the notebook makes both profiles explicit rather
  than presenting the assignment example as statutory advice. Run
  `python -m pytest tests -q` to execute both suites. Verify rates and tax
  treatment with current URA guidance before real-world use.

## Academic integrity and AI-use declaration

AI coding assistance was used to help scaffold and revise the weather client,
tax-engine module, notebooks, tests, and this setup documentation. The
repository owner should review and understand every implementation decision,
verify rates against current URA publications, and be prepared to explain the
code independently.
