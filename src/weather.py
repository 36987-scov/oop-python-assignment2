"""Reusable functions for fetching and parsing weather data."""

import time

import matplotlib.pyplot as plt
import pandas as pd
import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
MET_UNIT_SYMBOLS = {"celsius": "°C", "mm": "mm"}
DEFAULT_TIMEOUT = 10
MAX_RETRIES = 3          # retries after the first attempt (4 attempts in total)
BACKOFF_SECONDS = 1.0    # first wait; doubles after each failed attempt
MAX_FORECAST_DAYS = 16
DAILY_VARIABLES = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
    "weather_code",
]

# WMO weather interpretation codes, from the Open-Meteo forecast API
# documentation: https://open-meteo.com/en/docs
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Slight or moderate thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class LocationNotFoundError(Exception):
    """Raised when a geocoding search returns no matching places."""


def parse_geocoding_results(data: dict) -> list[dict]:
    """Turn an Open-Meteo geocoding response into a list of candidate places.

    Args:
        data: JSON response from the Open-Meteo geocoding API.

    Returns:
        A list of candidate places, each with name, admin1, country,
        latitude, longitude, timezone and population. Empty if nothing
        was found.
    """
    candidates = []
    for place in data.get("results", []):
        candidates.append({
            "name": place["name"],
            "admin1": place.get("admin1"),
            "country": place.get("country"),
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "timezone": place.get("timezone"),
            "population": place.get("population"),
        })
    return candidates


class WeatherAPIError(Exception):
    """Raised when a weather API request fails and will not be retried."""


def fetch_json(url: str, params: dict, user_agent: str,
               timeout: float = DEFAULT_TIMEOUT,
               max_retries: int = MAX_RETRIES,
               backoff: float = BACKOFF_SECONDS) -> dict:
    """Send a GET request and return the decoded JSON body.

    Connection errors, timeouts and HTTP 5xx responses are retried up to
    max_retries times, waiting backoff, 2*backoff, 4*backoff ... seconds
    between attempts. HTTP 4xx responses are not retried, because the
    request itself is wrong and repeating it cannot succeed.

    Raises:
        WeatherAPIError: on a 4xx response, or when all attempts fail.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params,
                                    headers={"User-Agent": user_agent},
                                    timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            status = error.response.status_code
            if status < 500:
                raise WeatherAPIError(
                    f"{url} returned HTTP {status}: {error.response.text[:200]}"
                ) from error
            last_error = error
        except (requests.ConnectionError, requests.Timeout) as error:
            last_error = error
        if attempt < max_retries:
            time.sleep(backoff * 2 ** attempt)
    raise WeatherAPIError(
        f"{url} failed after {max_retries + 1} attempts: {last_error}"
    ) from last_error


def geocode(name: str, user_agent: str, count: int = 5,
            country_code: str | None = None) -> list[dict]:
    """Search Open-Meteo for places matching a name.

    Args:
        name: Place name to search for, e.g. "Mukono".
        user_agent: User-Agent header identifying the caller.
        count: Maximum number of candidates to return.
        country_code: Optional ISO-3166-1 alpha-2 code (e.g. "UG")
            to restrict results to one country; None searches worldwide.

    Returns:
        A list of candidates (see parse_geocoding_results);
        empty when nothing matches.
    """
    if not name.strip():
        raise ValueError("Location name must not be empty.")
    params = {"name": name, "count": count, "language": "en", "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    data = fetch_json(GEOCODING_URL, params, user_agent)
    return parse_geocoding_results(data)


def choose_location(candidates: list[dict], choice: int) -> dict:
    """Return the candidate the user picked by its list number.

    Raises:
        LocationNotFoundError: if there are no candidates at all.
        ValueError: if choice is not a valid list number.
    """
    if not candidates:
        raise LocationNotFoundError("No places matched the search.")
    if not 0 <= choice < len(candidates):
        raise ValueError(
            f"LOCATION_CHOICE must be between 0 and {len(candidates) - 1}, "
            f"got {choice}."
        )
    return candidates[choice]


def get_forecast(lat: float, lon: float, days: int, user_agent: str,
                 timezone: str = "auto") -> dict:
    """Request a daily forecast from Open-Meteo.

    Args:
        lat: Latitude in degrees, -90 to 90.
        lon: Longitude in degrees, -180 to 180.
        days: Number of forecast days, 1 to MAX_FORECAST_DAYS.
        user_agent: User-Agent header identifying the caller.
        timezone: Time zone name (e.g. "Africa/Kampala") so daily values
            follow local days; "auto" lets the API choose.

    Returns:
        The decoded JSON response, including "daily" and "daily_units".

    Raises:
        ValueError: if lat, lon or days are out of range.
    """
    _check_coordinates(lat, lon)
    if not 1 <= days <= MAX_FORECAST_DAYS:
        raise ValueError(
            f"days must be between 1 and {MAX_FORECAST_DAYS}, got {days}."
        )
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(DAILY_VARIABLES),
        "forecast_days": days,
        "timezone": timezone,
    }
    return fetch_json(FORECAST_URL, params, user_agent)


def describe_weather_code(code: int | None) -> str:
    """Translate a WMO weather code into a readable description."""
    if code is None:
        return "No data"
    return WEATHER_CODES.get(int(code), f"Unknown code {code}")


def forecast_to_dataframe(forecast: dict) -> pd.DataFrame:
    """Convert an Open-Meteo daily forecast into a tidy DataFrame.

    Column names include the units reported by the API in "daily_units".

    Args:
        forecast: JSON response returned by get_forecast.

    Returns:
        One row per day: date, weather description, max and min
        temperature, precipitation sum and maximum wind speed.
    """
    daily = forecast["daily"]
    units = forecast["daily_units"]
    return pd.DataFrame({
        "Date": pd.to_datetime(daily["time"]),
        "Weather": [describe_weather_code(c) for c in daily["weather_code"]],
        f"Max temperature ({units['temperature_2m_max']})":
            daily["temperature_2m_max"],
        f"Min temperature ({units['temperature_2m_min']})":
            daily["temperature_2m_min"],
        f"Precipitation ({units['precipitation_sum']})":
            daily["precipitation_sum"],
        f"Max wind speed ({units['wind_speed_10m_max']})":
            daily["wind_speed_10m_max"],
    })


def _find_column(df: pd.DataFrame, prefix: str) -> str:
    """Return the first column whose name starts with prefix."""
    for column in df.columns:
        if column.startswith(prefix):
            return column
    raise KeyError(f"No column starting with {prefix!r}.")


def plot_forecast(df: pd.DataFrame, title: str) -> plt.Figure:
    """Plot the daily temperature range with precipitation bars.

    Temperature uses the left y-axis and precipitation the right one,
    because the two quantities have different units and scales.

    Args:
        df: DataFrame returned by forecast_to_dataframe.
        title: Chart title.

    Returns:
        The matplotlib Figure, so callers can display or save it.
    """
    max_col = _find_column(df, "Max temperature")
    min_col = _find_column(df, "Min temperature")
    rain_col = _find_column(df, "Precipitation")

    fig, temp_ax = plt.subplots(figsize=(10, 5))
    rain_ax = temp_ax.twinx()

    rain_ax.bar(df["Date"], df[rain_col], color="tab:blue", alpha=0.3,
                label=rain_col)
    temp_ax.fill_between(df["Date"], df[min_col], df[max_col],
                         color="tab:orange", alpha=0.2,
                         label="Temperature range")
    temp_ax.plot(df["Date"], df[max_col], color="tab:red", marker="o",
                 label=max_col)
    temp_ax.plot(df["Date"], df[min_col], color="tab:orange", marker="o",
                 label=min_col)

    # Draw the temperature lines in front of the rain bars.
    temp_ax.set_zorder(rain_ax.get_zorder() + 1)
    temp_ax.patch.set_visible(False)

    temp_ax.set_xlabel("Date")
    temp_ax.set_ylabel(max_col.replace("Max temperature", "Temperature"))
    rain_ax.set_ylabel(rain_col)
    temp_ax.set_title(title)

    lines, line_labels = temp_ax.get_legend_handles_labels()
    bars, bar_labels = rain_ax.get_legend_handles_labels()
    temp_ax.legend(lines + bars, line_labels + bar_labels, loc="upper left")

    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def _unit(column: str) -> str:
    """Return the unit inside the brackets of a column name, e.g. "°C"."""
    return column[column.rfind("(") + 1:-1]


def summarise_forecast(df: pd.DataFrame, place: str) -> str:
    """Write a short plain-text summary of a daily forecast.

    Args:
        df: DataFrame returned by forecast_to_dataframe.
        place: Location name to show in the first line.

    Returns:
        A multi-line summary. If several conditions are equally common,
        pandas returns them sorted, and the first is reported.
    """
    max_col = _find_column(df, "Max temperature")
    min_col = _find_column(df, "Min temperature")
    rain_col = _find_column(df, "Precipitation")
    wind_col = _find_column(df, "Max wind speed")

    warmest = df.loc[df[max_col].idxmax()]
    wettest = df.loc[df[rain_col].idxmax()]
    windiest = df.loc[df[wind_col].idxmax()]
    rainy_days = int((df[rain_col] > 0).sum())
    date_format = "%a %d %b"

    lines = [
        f"Forecast for {place}, {df['Date'].min():{date_format}} "
        f"to {df['Date'].max():{date_format}}:",
        f"- Temperatures from {df[min_col].min():.1f} to "
        f"{df[max_col].max():.1f} {_unit(max_col)}; warmest day "
        f"{warmest['Date']:{date_format}}.",
        f"- Rain expected on {rainy_days} of {len(df)} days, "
        f"{df[rain_col].sum():.1f} {_unit(rain_col)} in total; wettest day "
        f"{wettest['Date']:{date_format}} "
        f"({wettest[rain_col]:.1f} {_unit(rain_col)}).",
        f"- Strongest wind {windiest[wind_col]:.1f} {_unit(wind_col)} "
        f"on {windiest['Date']:{date_format}}.",
        f"- Most common conditions: {df['Weather'].mode()[0]}.",
    ]
    return "\n".join(lines)


def _check_coordinates(lat: float, lon: float) -> None:
    """Raise ValueError if lat or lon is outside the valid range."""
    if not -90 <= lat <= 90:
        raise ValueError(f"Latitude must be between -90 and 90, got {lat}.")
    if not -180 <= lon <= 180:
        raise ValueError(f"Longitude must be between -180 and 180, got {lon}.")


def get_met_forecast(lat: float, lon: float, user_agent: str) -> dict:
    """Request the MET Norway Locationforecast 2.0 compact forecast.

    Coordinates are rounded to 4 decimals, as MET Norway's terms of
    service require. The user_agent must identify the app and a contact.

    Raises:
        ValueError: if lat or lon is out of range.
        WeatherAPIError: if the request fails (see fetch_json).
    """
    _check_coordinates(lat, lon)
    params = {"lat": round(lat, 4), "lon": round(lon, 4)}
    return fetch_json(MET_URL, params, user_agent)


def met_to_daily_dataframe(data: dict, timezone: str) -> pd.DataFrame:
    """Aggregate a MET Norway compact forecast into local daily values.

    MET timestamps are UTC; they are converted to the location's time zone
    before grouping, so each row covers one local calendar day. Precipitation
    uses each step's next_1_hours amount where available, otherwise its
    next_6_hours amount (later forecast days are only 6-hourly). Max/min
    temperatures are taken from the instantaneous samples, so days with few
    samples (shown in "Hourly samples") are less precise.

    Args:
        data: JSON returned by get_met_forecast.
        timezone: Time zone name, e.g. "Africa/Kampala".

    Returns:
        One row per local day: Date, max and min temperature,
        precipitation and the number of samples used.
    """
    units = data["properties"]["meta"]["units"]
    temp_unit = MET_UNIT_SYMBOLS.get(units["air_temperature"],
                                     units["air_temperature"])
    rain_unit = MET_UNIT_SYMBOLS.get(units["precipitation_amount"],
                                     units["precipitation_amount"])

    rows = []
    for step in data["properties"]["timeseries"]:
        step_data = step["data"]
        precipitation = None
        for period in ("next_1_hours", "next_6_hours"):
            if period in step_data:
                precipitation = step_data[period]["details"].get(
                    "precipitation_amount")
                break
        rows.append({
            "time": step["time"],
            "temperature": step_data["instant"]["details"]["air_temperature"],
            "precipitation": precipitation,
        })

    hourly = pd.DataFrame(rows)
    local_time = pd.to_datetime(hourly["time"], utc=True).dt.tz_convert(timezone)
    hourly["Date"] = local_time.dt.tz_localize(None).dt.normalize()

    daily = hourly.groupby("Date").agg(
        max_temp=("temperature", "max"),
        min_temp=("temperature", "min"),
        precipitation=("precipitation", "sum"),
        samples=("temperature", "size"),
    ).reset_index()
    return daily.rename(columns={
        "max_temp": f"Max temperature ({temp_unit})",
        "min_temp": f"Min temperature ({temp_unit})",
        "precipitation": f"Precipitation ({rain_unit})",
        "samples": "Hourly samples",
    })


def compare_forecasts(open_meteo: pd.DataFrame, met: pd.DataFrame) -> pd.DataFrame:
    """Join two daily forecasts on Date and add Open-Meteo minus MET differences.

    Only columns present in both DataFrames (same name, same unit) are
    compared, so values in different units are never subtracted.
    """
    shared = [c for c in met.columns if c in open_meteo.columns and c != "Date"]
    merged = open_meteo[["Date", *shared]].merge(
        met[["Date", *shared]], on="Date",
        suffixes=(" [Open-Meteo]", " [MET]"))
    for column in shared:
        merged[f"{column} difference"] = (
            merged[f"{column} [Open-Meteo]"] - merged[f"{column} [MET]"]
        ).round(1)
    return merged