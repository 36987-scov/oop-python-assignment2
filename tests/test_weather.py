"""Offline tests for the parsing functions in src/weather.py.

They use saved API responses in data/, so they run without a network.
Run them from the project folder with:  python -m pytest -v
"""

import json
import os

import pandas as pd
import pytest

from src.weather import (
    LocationNotFoundError,
    choose_location,
    compare_forecasts,
    describe_weather_code,
    forecast_to_dataframe,
    met_to_daily_dataframe,
    parse_geocoding_results,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TIMEZONE = "Africa/Kampala"


def load_sample(filename: str) -> dict:
    """Load one saved API response from the data/ folder."""
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as file:
        return json.load(file)


def test_parse_geocoding_keeps_every_candidate():
    candidates = parse_geocoding_results(load_sample("sample_geocoding.json"))
    assert len(candidates) == 5
    assert candidates[0]["name"] == "Mukono"
    assert candidates[0]["country"] == "Uganda"
    assert set(candidates[0]) == {"name", "admin1", "country", "latitude",
                                  "longitude", "timezone", "population"}


def test_parse_geocoding_handles_missing_results_key():
    data = load_sample("sample_geocoding_empty.json")
    assert "results" not in data          # the real API omits the key
    assert parse_geocoding_results(data) == []


def test_choose_location_rejects_no_candidates_and_bad_choice():
    with pytest.raises(LocationNotFoundError):
        choose_location([], 0)
    candidates = parse_geocoding_results(load_sample("sample_geocoding.json"))
    with pytest.raises(ValueError):
        choose_location(candidates, 99)
    assert choose_location(candidates, 0) == candidates[0]


def test_describe_weather_code():
    assert describe_weather_code(0) == "Clear sky"
    assert describe_weather_code(95) == "Slight or moderate thunderstorm"
    assert describe_weather_code(61.0) == "Slight rain"   # float from JSON
    assert describe_weather_code(42) == "Unknown code 42"
    assert describe_weather_code(None) == "No data"


def test_forecast_dataframe_shape_and_unit_columns():
    df = forecast_to_dataframe(load_sample("sample_forecast.json"))
    assert len(df) == 7
    assert list(df.columns) == [
        "Date", "Weather", "Max temperature (°C)", "Min temperature (°C)",
        "Precipitation (mm)", "Max wind speed (km/h)",
    ]
    assert not df["Weather"].str.startswith("Unknown").any()


def test_forecast_dataframe_values_match_json():
    data = load_sample("sample_forecast.json")
    df = forecast_to_dataframe(data)
    assert df["Max temperature (°C)"].tolist() == data["daily"]["temperature_2m_max"]
    assert df["Precipitation (mm)"].tolist() == data["daily"]["precipitation_sum"]
    assert (df["Max temperature (°C)"] >= df["Min temperature (°C)"]).all()


def test_met_daily_uses_local_dates_and_keeps_every_step():
    data = load_sample("sample_met.json")
    daily = met_to_daily_dataframe(data, TIMEZONE)
    steps = data["properties"]["timeseries"]

    first_utc = pd.Timestamp(steps[0]["time"])
    first_local_day = first_utc.tz_convert(TIMEZONE).tz_localize(None).normalize()
    assert daily["Date"].iloc[0] == first_local_day
    assert daily["Hourly samples"].sum() == len(steps)
    assert (daily["Max temperature (°C)"] >= daily["Min temperature (°C)"]).all()


def test_compare_forecasts_only_subtracts_matching_units():
    open_meteo = forecast_to_dataframe(load_sample("sample_forecast.json"))
    met = met_to_daily_dataframe(load_sample("sample_met.json"), TIMEZONE)
    merged = compare_forecasts(open_meteo, met)

    assert not any("wind" in column.lower() for column in merged.columns)
    column = "Max temperature (°C)"
    expected = (merged[f"{column} [Open-Meteo]"] - merged[f"{column} [MET]"]).round(1)
    assert merged[f"{column} difference"].equals(expected)