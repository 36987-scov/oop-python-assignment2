"""Reusable functions for fetching and parsing weather data."""

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
DEFAULT_TIMEOUT = 10


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


def fetch_json(url: str, params: dict, user_agent: str,
               timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Send a GET request and return the decoded JSON body.

    Raises:
        requests.HTTPError: if the server returns a 4xx or 5xx status.
        requests.RequestException: for connection problems or timeouts.
    """
    response = requests.get(url, params=params,
                            headers={"User-Agent": user_agent},
                            timeout=timeout)
    response.raise_for_status()
    return response.json()


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