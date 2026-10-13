# OOP with Python: Assignment 2 (Advent 2026)

MSDS coursework: two mini-projects in Jupyter notebooks, with reusable code in `src/` and offline tests in `tests/`.

## Project structure

```
notebooks/project1_weather.ipynb   Mini-Project 1: weather forecast notebook
src/weather.py                     Reusable functions for Mini-Project 1
tests/test_weather.py              Offline pytest checks for src/weather.py
data/sample_*.json                 Saved API responses used by the tests
requirements.txt                   Pinned dependencies
```
notebooks/project2_tax_engine.ipynb Mini-Project 2: Uganda tax engine notebook
src/tax_engine.py                   Money, tax errors, schedules and tax classes
tests/test_tax_engine.py            Boundary, property-based and worked-example tests


## Setup (Windows)

1. Install Python 3.14 (developed with 3.14.8).
2. Clone the repository and open a terminal in its folder.
3. Create and activate a virtual environment, then install the dependencies:

```
   py -V:3.14 -m venv .venv
   .venv\Scripts\activate.bat
   python -m pip install -r requirements.txt
```

4. Set your own contact email, used in the API User-Agent header. Open a new terminal afterwards so the variable is available:

```
   setx WEATHER_CONTACT_EMAIL "your.email@example.com"
```

   The email is never stored in the code. If it is not set, the notebook shows a warning.

## How to run

**Notebook:** start Jupyter with `jupyter notebook`, open `notebooks/project1_weather.ipynb` and run all cells. The only cell to edit is the configuration cell (location, country code, choice of candidate, forecast days). The notebook calls live APIs, so it needs internet access.

**Tests:** from the project folder, run:

```
python -m pytest -v
```

The tests use the saved responses in `data/`, so they run offline.

**Tax engine:** open `notebooks/project2_tax_engine.ipynb` and run all cells. It needs no internet access. The tests in `tests/test_tax_engine.py` run with the same `python -m pytest -v` command; all 30 tests (both projects) should pass.

## Libraries

The brief allows urllib, requests, json, datetime, time, os, pandas and matplotlib. Two further libraries are used:

- **pytest**: runs the offline checks in `tests/`.
- **jinja2**: required by pandas to render the formatted forecast table (installed with Jupyter).
- - **hypothesis**: generates hundreds of test inputs to check that PAYE is never negative, never exceeds income and never falls as income rises (Mini-Project 2).

## Data sources

- Open-Meteo Geocoding and Forecast APIs (data under CC BY 4.0; location data based on GeoNames): https://open-meteo.com
- MET Norway Locationforecast 2.0 (data under CC BY 4.0): https://api.met.no

## Summary of findings"

### Mini-Project 1: Weather forecast with Python web APIs

Results below are from the run on 12 October 2026; live forecasts change on each run.

- **Geocoding and ambiguity:** searching "Mukono" returned five places worldwide, including a fuzzy match ("Mokono", DR Congo). With the Uganda filter, three candidates remained, including "Mukono Landing" from prefix matching; candidate 0 (population 191,300) is Mukono town, chosen with `LOCATION_CHOICE`.
- **urllib vs requests:** both returned identical results. `requests` needed two steps instead of six and decodes the response using the declared charset, but does not raise on 4xx/5xx errors without `raise_for_status()`. Responses were `application/json; charset=utf-8`, typically in about 1 second.
- **Forecast (12–18 October 2026, Africa/Kampala):** temperatures from 18.2 to 27.6 °C (warmest Wednesday 14 October); rain on all 7 days, 44.0 mm in total, heaviest on Friday 16 October (14.5 mm); a thunderstorm forecast on Thursday 15 October; strongest wind 16.8 km/h.
- **Reliability:** an invalid request (HTTP 400) failed immediately without retries (0.8 s); a tiny timeout failed after 3 attempts in 1.5 s, matching the backoff waits; a simulated network failure took 13.7 s, mostly due to the operating system's handling of refused connections.
- **Second source:** MET Norway agreed with Open-Meteo on daily maximum temperatures to within about 1.3 °C, but rainfall differed by up to 11.9 mm, reflecting model differences for tropical showers. MET's first day covered only the remaining night hours.
- **Tests:** 8 offline pytest checks on saved API responses all pass.
### Mini-Project 2: Uganda tax engine

- PAYE follows two dated resident schedules: FY 2025/26 (URA rates page) and, from 1 July 2026, the Income Tax (Amendment) Act 2026, which raised the nil band to UGX 335,000 and added a 25% band. Dates outside these years raise `NoScheduleForDateError` instead of guessing.
- All six brief-specified band boundaries give the expected tax (for example UGX 33,750 at 485,000 and UGX 2,888,250 at 10,000,000), and Hypothesis confirms over 300 generated incomes per property that tax is never negative, never exceeds income and never decreases as income rises.
- A payroll example (UGX 1,000,000 gross) shows the deduction order at work: PAYE is UGX 2,250 lower in October than November because the LST instalment is deducted before PAYE.
- The rental module reproduces URA's own worked example exactly (UGX 381,600).
- `Decimal` avoids float errors such as `0.1 + 0.2 = 0.30000000000000004`.




### AI assistance: 
I used AI to assist with explanations and debugging of code. The resulting implementation was tested, and the outputs of the code reviewed.
