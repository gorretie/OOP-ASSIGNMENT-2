# Weather Forecast and Uganda Tax Projects

This repository contains two Python projects:

1. A weather forecasting client that geocodes a location with Open-Meteo,
   retrieves a daily forecast in local time, and presents the results in a
   table and chart.
2. An object-oriented Uganda tax engine featuring Decimal-based UGX values,
   versioned PAYE schedules, payroll, VAT, corporate income tax, and a scenario
   planner.

## Project files

- `weather_forecast.ipynb` — weather-client examples and report.
- `src/weather_client.py` — the reusable `WeatherForecastClient` and
  `WeatherRequestError`.
- `uganda_tax_engine.ipynb` — tax-engine examples, analysis, and report.
- `src/tax_engine.py` — tax domain models, value objects, and calculators.
- `tests/test_weather_client.py` — offline tests for the weather client.
- `tests/test_tax_engine.py` — tax-boundary, validation, and property tests.
- `samples/` — saved geocoding and forecast JSON responses used by the tests.
- `requirements.txt` — dependencies for the client and notebooks.
- `requirements-dev.txt` — project dependencies, plus pytest, Jupyter, and
  Hypothesis.

## Set up on Windows

Use Python 3.10 or later. In PowerShell, from the project folder, create and
activate a virtual environment, then install the development dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

If PowerShell does not recognize `py`, install Python and enable the Python
Launcher, or create the virtual environment using your Python executable:

```powershell
python -m venv .venv
```

If your machine's PowerShell policy prevents script activation, use the
environment's Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

## Configure and run the notebooks

1. Open either notebook in Jupyter or VS Code, then select the `.venv` Python
   kernel.
2. In `weather_forecast.ipynb`, set the location and candidate index. Before
   enabling the MET Norway request, enter your university email address in
   `CONTACT_EMAIL`.
3. In `uganda_tax_engine.ipynb`, review the tax date, schedule version, and
   example income values in the configuration cell. The assignment PAYE
   schedule differs from the published reference schedule; read the notebook's
   discussion before interpreting the example results.
4. Select **Restart & Run All**. The weather notebook makes live API requests
   and requires internet access; the tax notebook runs locally.

From PowerShell, you can also launch Jupyter from the project directory:

```powershell
python -m jupyter notebook weather_forecast.ipynb
```

To run the tax project, open `uganda_tax_engine.ipynb` in the same way.

The weather notebook makes live API requests. Avoid rerunning its request
cells unnecessarily, and follow each provider's rate limits and caching
guidance. Location names and coordinates are sent to the selected API
providers.

## Run tests

With the virtual environment activated, run:

```powershell
python -m pytest tests -q
```

Alternatively, run the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

The weather tests use saved sample responses and mocked HTTP transports. The
tax tests use Decimal-based examples and Hypothesis-generated inputs. Both test
modules run offline and do not send requests to external services.

## Findings summary

- The client parses geocoding candidates, handles responses without
  `results`, and caches each lookup during a run.
- Forecast parsing validates daily fields and array lengths, labels units,
  converts local date strings, and maps WMO weather codes to descriptions.
- Requests use timeouts and bounded retries for connection and server errors.
  Client-side HTTP errors are not retried, and final transport failures raise
  `WeatherRequestError`.
- The weather notebook demonstrates both `urllib` and `requests`, reports live
  HTTP metadata, and handles invalid cities, invalid coordinates,
  simulated-network failures, and very short timeouts.
- The pytest suite covers parsing, validation, caching, forecast queries,
  retry behavior, and MET Norway identification and coordinate rounding, as
  well as tax-engine boundaries and properties. The combined suite currently
  completes with **42 tests passed**.
- Live forecasts depend on external APIs and are not guaranteed to be
  available or accurate. Use of the free Open-Meteo API is subject to its
  current non-commercial terms and attribution requirements. MET Norway
  requires an identifying User-Agent and appropriate data attribution. Check
  both providers' current terms before using this code in a product.
- The tax engine includes an immutable, Decimal-backed UGX value object, an
  abstract `Tax` interface, versioned resident and non-resident PAYE schedules,
  composed payroll, VAT, and corporate-tax calculators, and a salary/dividend
  scenario comparison. Tests cover the assignment's PAYE boundaries and use
  Hypothesis to check that tax is non-negative, monotonic, and no greater than
  income. The assignment's resident PAYE schedule differs from the published
  FY2025/26 table; the notebook presents both profiles explicitly and does not
  treat the assignment example as statutory advice. Before real-world use,
  verify rates and tax treatment against current URA guidance.

## Academic integrity and AI-use declaration

AI assistance was used to draft and refine this README and project documentation, help develop unit tests, and assist with the GitHub Actions workflow configuration. AI-generated suggestions and code were reviewed and validated by running the project test suite and executing the analysis notebooks. The numerical outputs remain dependent on the supplied datasets and the assumptions stated in each project; AI assistance does not independently validate those assumptions or establish that illustrative data represent real-world conditions.