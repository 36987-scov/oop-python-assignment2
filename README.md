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

## Libraries

The brief allows urllib, requests, json, datetime, time, os, pandas and matplotlib. Two further libraries are used:

- **pytest**: runs the offline checks in `tests/`.
- **jinja2**: required by pandas to render the formatted forecast table (installed with Jupyter).

## Data sources

- Open-Meteo Geocoding and Forecast APIs (data under CC BY 4.0; location data based on GeoNames): https://open-meteo.com
- MET Norway Locationforecast 2.0 (data under CC BY 4.0): https://api.met.no

