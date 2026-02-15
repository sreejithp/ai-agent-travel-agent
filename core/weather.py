# =============================================================================
# core/weather.py  —  Weather Data & Analysis Logic
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Provides weather forecasts for Maui — either from MOCK data or from the
#   LIVE Open-Meteo API — and analyzes them against user preferences.
#
# DATA SOURCE TOGGLE:
#   Set the environment variable USE_LIVE_WEATHER=true to use real weather
#   data from the Open-Meteo API (free, no API key needed).
#   Leave it unset or set to "false" to use deterministic mock data.
#
#   This toggle exists so you can:
#     - Develop and test offline with predictable mock data
#     - Demo with real weather when you have internet access
#     - Compare agent behavior between mock and real scenarios
#
# WHY OPEN-METEO?
#   - Completely free, no API key required
#   - Reliable, well-documented REST API
#   - Provides up to 16 days of forecast data
#   - Returns temperature, precipitation, wind, weather codes
#   - No rate limiting for reasonable usage
#
# KEY DESIGN DECISIONS:
#
# 1. BOTH providers return the SAME DayForecast dataclass.
#    The analysis layer (analyze_weather) doesn't know or care whether
#    the data came from a mock or a real API.  This is the Strategy
#    Pattern: swap the data source, keep the analysis unchanged.
#
# 2. WHY SUMMARIZE INSTEAD OF DUMPING RAW DATA?
#    This is "Context Budget Discipline" — one of the hardest lessons in
#    agent design.  An LLM has a finite context window.  If you dump 30
#    days of raw weather JSON into it, you:
#      a) waste tokens ($$)
#      b) risk the agent missing important patterns in the noise
#      c) make the agent's reasoning slower and less reliable
#
#    Instead, this module does the heavy lifting: it computes averages,
#    identifies the best/worst windows, and returns a SUMMARY.
#
# 3. THE SEPARATION OF "FETCH" AND "ANALYZE":
#    - get_forecast() returns raw-ish data (list of DayForecast)
#    - analyze_weather() takes that data + user preferences and produces
#      a WeatherSummary with a best_window recommendation
#    This separation means you can test the analysis logic independently
#    of the data source.
# =============================================================================

from datetime import datetime, timedelta
import os
import random

from core.models import DayForecast, WeatherSummary, UserProfile


# =============================================================================
# WMO Weather Code Mapping
# =============================================================================
# The Open-Meteo API returns WMO (World Meteorological Organization) weather
# codes instead of human-readable strings.  This mapping converts them.
#
# Reference: https://www.nodc.noaa.gov/archive/arc0021/0002199/1.1/data/0-data/
# =============================================================================
_WMO_CODE_TO_CONDITION: dict[int, str] = {
    0: "Clear",
    1: "Mainly Clear",
    2: "Partly Cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing Rime Fog",
    51: "Light Drizzle",
    53: "Moderate Drizzle",
    55: "Dense Drizzle",
    56: "Freezing Drizzle",
    57: "Heavy Freezing Drizzle",
    61: "Slight Rain",
    63: "Moderate Rain",
    65: "Heavy Rain",
    66: "Freezing Rain",
    67: "Heavy Freezing Rain",
    71: "Slight Snow",
    73: "Moderate Snow",
    75: "Heavy Snow",
    77: "Snow Grains",
    80: "Slight Showers",
    81: "Moderate Showers",
    82: "Violent Showers",
    85: "Slight Snow Showers",
    86: "Heavy Snow Showers",
    95: "Thunderstorms",
    96: "Thunderstorms with Hail",
    99: "Heavy Thunderstorms with Hail",
}

# WMO codes that indicate storm risk (used to set is_storm_risk flag)
_STORM_CODES = {65, 66, 67, 82, 95, 96, 99}


def _celsius_to_fahrenheit(celsius: float) -> int:
    """Convert Celsius to Fahrenheit, rounded to nearest integer."""
    return round(celsius * 9 / 5 + 32)


def _kmh_to_mph(kmh: float) -> int:
    """Convert km/h to mph, rounded to nearest integer."""
    return round(kmh * 0.621371)


def _mm_to_precip_pct(mm: float) -> int:
    """Convert precipitation mm to a rough 'chance of rain' percentage.

    Open-Meteo gives precipitation_sum in mm, not probability.
    We convert: 0mm → 0%, 1mm → ~20%, 5mm+ → 80-100%.
    This is a rough heuristic, not meteorologically precise.
    """
    if mm <= 0:
        return 5   # Trace moisture is always possible in Hawaii
    elif mm < 1:
        return 25
    elif mm < 3:
        return 45
    elif mm < 5:
        return 65
    elif mm < 10:
        return 80
    else:
        return 95


# =============================================================================
# PUBLIC API: get_forecast (dispatcher)
# =============================================================================
def get_forecast(destination: str, start_date: str, days: int = 30) -> list[DayForecast]:
    """Get weather forecast — dispatches to mock or live based on env var.

    Toggle via environment variable:
        USE_LIVE_WEATHER=true   → calls Open-Meteo API (real data, needs internet)
        USE_LIVE_WEATHER=false  → uses mock data (deterministic, offline)

    Both providers return the same list[DayForecast] format, so the
    analysis layer doesn't need to know which one was used.

    Args:
        destination: The location (e.g., "Maui, HI").
        start_date: ISO date string for forecast start (e.g., "2025-07-10").
        days: Number of days to forecast (default 30; live API caps at 16).

    Returns:
        A list of DayForecast objects, one per day.
    """
    use_live = os.environ.get("USE_LIVE_WEATHER", "false").lower() == "true"

    if use_live:
        return get_forecast_live(destination, start_date, days)
    else:
        return get_forecast_mock(destination, start_date, days)


# =============================================================================
# LIVE PROVIDER: Open-Meteo API
# =============================================================================
def get_forecast_live(destination: str, start_date: str, days: int = 16) -> list[DayForecast]:
    """Fetch real weather forecast from the Open-Meteo API.

    Open-Meteo is a free, open-source weather API that requires NO API key.
    It provides up to 16 days of forecast data.

    HOW IT WORKS:
      1. We map destination names to coordinates (lat/lon)
      2. We call the Open-Meteo REST API with daily parameters
      3. We parse the JSON response into DayForecast objects
      4. We convert units (Celsius→Fahrenheit, km/h→mph)

    IMPORTANT LIMITATIONS:
      - Max 16 days of forecast (Open-Meteo's free tier limit)
      - Requires internet access
      - Real weather doesn't have the nice "storm window" pattern
        that the mock data has — agent behavior will differ!

    Args:
        destination: Location name (currently supports "Maui" variants).
        start_date: ISO date string (e.g., "2025-07-10").
        days: Number of days (capped at 16 by Open-Meteo).

    Returns:
        A list of DayForecast objects with real weather data.
    """
    import urllib.request
    import json

    # --- Map destination to coordinates ---
    # In production, you'd use a geocoding API.  For this project,
    # we hardcode Maui's coordinates (it's always Maui!).
    COORDINATES = {
        "maui": (20.798363, -156.331924),
    }

    # Normalize destination name to find coordinates
    dest_lower = destination.lower()
    lat, lon = None, None
    for key, coords in COORDINATES.items():
        if key in dest_lower:
            lat, lon = coords
            break

    if lat is None:
        # Fallback to Maui if destination not recognized
        lat, lon = COORDINATES["maui"]

    # Open-Meteo caps at 16 forecast days
    forecast_days = min(days, 16)

    # --- Build the API URL ---
    # We request daily aggregates: max/min temp, precipitation, wind, weather code
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,temperature_2m_min,"
        f"precipitation_sum,wind_speed_10m_max,weather_code"
        f"&forecast_days={forecast_days}"
        f"&timezone=Pacific%2FHonolulu"  # Hawaii timezone
    )

    # --- Make the HTTP request ---
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
    except Exception as e:
        # If the API call fails, fall back to mock data gracefully.
        # This is a RESILIENCE pattern: the agent keeps working even
        # if the weather service is down.
        print(f"⚠ Open-Meteo API call failed: {e}. Falling back to mock data.")
        return get_forecast_mock(destination, start_date, days)

    # --- Parse the response into DayForecast objects ---
    daily = data.get("daily", {})
    dates = daily.get("time", [])
    temp_maxs = daily.get("temperature_2m_max", [])
    temp_mins = daily.get("temperature_2m_min", [])
    precip_sums = daily.get("precipitation_sum", [])
    wind_maxs = daily.get("wind_speed_10m_max", [])
    weather_codes = daily.get("weather_code", [])

    forecasts = []
    for i in range(len(dates)):
        wmo_code = weather_codes[i] if i < len(weather_codes) else 0
        precip_mm = precip_sums[i] if i < len(precip_sums) else 0

        forecasts.append(DayForecast(
            date=dates[i],
            high_f=_celsius_to_fahrenheit(temp_maxs[i]) if i < len(temp_maxs) else 80,
            low_f=_celsius_to_fahrenheit(temp_mins[i]) if i < len(temp_mins) else 70,
            condition=_WMO_CODE_TO_CONDITION.get(wmo_code, "Unknown"),
            precipitation_pct=_mm_to_precip_pct(precip_mm),
            wind_mph=_kmh_to_mph(wind_maxs[i]) if i < len(wind_maxs) else 10,
            is_storm_risk=wmo_code in _STORM_CODES,
        ))

    return forecasts


# =============================================================================
# MOCK PROVIDER: Deterministic fake data
# =============================================================================
def get_forecast_mock(destination: str, start_date: str, days: int = 30) -> list[DayForecast]:
    """Generate a mock weather forecast for Maui.

    The mock data creates a realistic pattern designed to test agent reasoning:
      - Days 1-7:   Nice weather (low 70s to mid 80s, mostly sunny)
      - Days 8-12:  Storm window (rain, higher winds, storm risk)
      - Days 13-20: Mixed conditions (some good, some meh)
      - Days 21-30: Great weather again (best window)

    This pattern is INTENTIONAL — it forces the agent to reason about
    timing, trade-offs, and the user's storm tolerance.

    Args:
        destination: The location (e.g., "Maui, HI").
        start_date: ISO date string for forecast start (e.g., "2025-07-10").
        days: Number of days to forecast (default 30).

    Returns:
        A list of DayForecast objects, one per day.
    """
    # Seed the random number generator for reproducibility.
    # This makes the "mock" data deterministic — same inputs, same outputs.
    # That's a form of idempotency: the agent gets consistent results.
    random.seed(42)

    start = datetime.strptime(start_date, "%Y-%m-%d")
    forecasts = []

    for i in range(days):
        current_date = start + timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")

        # --- Phase-based weather generation ---
        # Each phase simulates a different weather pattern.  This is much
        # more realistic than pure random — real weather has *trends*.
        if i < 7:
            # Phase 1: Nice early-period weather
            high = random.randint(82, 87)
            low = random.randint(70, 74)
            condition = random.choice(["Sunny", "Sunny", "Partly Cloudy"])
            precip = random.randint(5, 20)
            wind = random.randint(5, 12)
            storm = False

        elif i < 12:
            # Phase 2: STORM WINDOW — this is the "trap" period
            # The agent must flag this and steer users away (especially
            # high-comfort users like Jordan).
            high = random.randint(78, 83)
            low = random.randint(72, 76)
            condition = random.choice(["Rain", "Thunderstorms", "Heavy Rain"])
            precip = random.randint(60, 95)
            wind = random.randint(15, 30)
            storm = True  # Explicitly flagged as required by the spec

        elif i < 20:
            # Phase 3: Mixed/recovery period — some good days, some rain
            high = random.randint(80, 86)
            low = random.randint(71, 75)
            condition = random.choice(
                ["Partly Cloudy", "Sunny", "Scattered Showers", "Partly Cloudy"]
            )
            precip = random.randint(15, 45)
            wind = random.randint(8, 15)
            storm = False

        else:
            # Phase 4: BEST WINDOW — ideal conditions
            # This is where the agent should steer most users.
            high = random.randint(83, 88)
            low = random.randint(71, 75)
            condition = random.choice(["Sunny", "Sunny", "Clear", "Partly Cloudy"])
            precip = random.randint(5, 15)
            wind = random.randint(5, 10)
            storm = False

        forecasts.append(DayForecast(
            date=date_str,
            high_f=high,
            low_f=low,
            condition=condition,
            precipitation_pct=precip,
            wind_mph=wind,
            is_storm_risk=storm,
        ))

    return forecasts


# =============================================================================
# ANALYSIS (shared by both providers)
# =============================================================================
def analyze_weather(
    forecasts: list[DayForecast],
    user_profile: UserProfile,
    destination: str = "Maui, HI",
) -> WeatherSummary:
    """Analyze a forecast against a user's preferences.

    This is where the INTELLIGENCE lives.  It doesn't just average the
    temperatures — it scores each day against what the user actually wants
    and identifies the best/worst windows.

    KEY INSIGHT:
      "Good weather" is subjective.  88°F is great for Sam (who loves heat)
      but bad for Jordan (who tops out at 80°F).  This function makes that
      subjectivity explicit by using the UserProfile as a lens.

    NOTE: This function works identically whether the forecasts came from
    the mock provider or the live Open-Meteo API.  That's the power of the
    Strategy Pattern — swap the data source, keep the analysis unchanged.

    Args:
        forecasts: List of daily forecasts (from get_forecast).
        user_profile: The traveler's preferences.
        destination: Where they're going.

    Returns:
        A WeatherSummary with best/worst windows and a narrative summary.
    """
    if not forecasts:
        return WeatherSummary(
            destination=destination,
            period="N/A",
            avg_high_f=0,
            avg_low_f=0,
            rainy_days=0,
            storm_risk_days=0,
            best_window="N/A",
            worst_window="N/A",
            summary="No forecast data available.",
        )

    # --- Compute basic statistics ---
    total_high = sum(f.high_f for f in forecasts)
    total_low = sum(f.low_f for f in forecasts)
    n = len(forecasts)

    rainy_days = sum(1 for f in forecasts if f.precipitation_pct > 40)
    storm_days = sum(1 for f in forecasts if f.is_storm_risk)

    # --- Find best and worst windows ---
    # We use a sliding window of trip_length_nights to find the best
    # contiguous block of days.  This is smarter than just picking
    # individual good days — you need CONSECUTIVE good days for a trip.
    trip_len = user_profile.trip_length_nights

    # If we have fewer days than the trip length, use what we have
    if n <= trip_len:
        best_start = 0
        worst_start = 0
    else:
        best_score = -999
        worst_score = 999
        best_start = 0
        worst_start = 0

        for i in range(n - trip_len):
            window = forecasts[i : i + trip_len]
            score = _score_weather_window(window, user_profile)
            if score > best_score:
                best_score = score
                best_start = i
            if score < worst_score:
                worst_score = score
                worst_start = i

    best_window_start = forecasts[best_start].date
    best_window_end = forecasts[min(best_start + trip_len - 1, n - 1)].date
    worst_window_start = forecasts[worst_start].date
    worst_window_end = forecasts[min(worst_start + trip_len - 1, n - 1)].date

    # --- Note data source in summary ---
    is_live = os.environ.get("USE_LIVE_WEATHER", "false").lower() == "true"
    source_note = "(live data from Open-Meteo)" if is_live else "(mock data)"

    # --- Generate human-readable summary ---
    summary_parts = []
    summary_parts.append(
        f"Over the next {n} days {source_note}, {destination} will see average highs "
        f"of {total_high // n}°F and lows of {total_low // n}°F."
    )

    if storm_days > 0:
        summary_parts.append(
            f"⚠ WARNING: {storm_days} days have storm risk. "
            f"Avoid the period around {forecasts[worst_start].date}."
        )

    summary_parts.append(
        f"Best weather window for your preferences: "
        f"{best_window_start} to {best_window_end}."
    )

    return WeatherSummary(
        destination=destination,
        period=f"{forecasts[0].date} to {forecasts[-1].date}",
        avg_high_f=total_high // n,
        avg_low_f=total_low // n,
        rainy_days=rainy_days,
        storm_risk_days=storm_days,
        best_window=f"{best_window_start} to {best_window_end}",
        worst_window=f"{worst_window_start} to {worst_window_end}",
        summary=" ".join(summary_parts),
        daily_forecasts=forecasts,
    )


def _score_weather_window(
    window: list[DayForecast], profile: UserProfile
) -> float:
    """Score a contiguous block of days for a specific user.

    This is the core SCORING HEURISTIC.  It quantifies "how good is this
    weather window for THIS person?"

    Scoring factors:
      1. Temperature alignment: How close are temps to the user's ideal range?
      2. Storm penalty: Storm days get a heavy negative score.
      3. Rain penalty: Rainy days are mildly penalized.
      4. Comfort weighting: High-comfort users are penalized MORE for bad weather.

    The scores are arbitrary units — they only matter relative to each other.
    We're not trying to produce a universal "weather goodness" number; we're
    trying to RANK windows for a specific user.

    Args:
        window: A list of consecutive DayForecasts.
        profile: The user whose preferences define "good."

    Returns:
        A numeric score (higher = better).
    """
    score = 0.0

    for day in window:
        # --- Temperature scoring ---
        # If the high is within the user's preferred range, full points.
        # If it's outside, we penalize proportionally to how far outside.
        if profile.preferred_temp_min_f <= day.high_f <= profile.preferred_temp_max_f:
            score += 10  # Perfect temperature day
        else:
            # How many degrees outside the comfort zone?
            if day.high_f < profile.preferred_temp_min_f:
                diff = profile.preferred_temp_min_f - day.high_f
            else:
                diff = day.high_f - profile.preferred_temp_max_f
            score -= diff * 1.5  # 1.5 points penalty per degree outside range

        # --- Storm penalty ---
        # Storms are serious.  The penalty scales with the user's comfort
        # priority — a comfort-priority-9 person gets a 45-point penalty
        # per storm day, while a comfort-priority-3 person gets only 15.
        if day.is_storm_risk:
            score -= 5 * profile.comfort_priority  # Heavy penalty, scaled by sensitivity

        # --- Rain penalty ---
        # Lighter than storms, but still unpleasant.
        if day.precipitation_pct > 40:
            score -= 3 * (profile.comfort_priority / 5)  # Scaled penalty

        # --- Wind bonus/penalty ---
        # Light breezes are pleasant in Maui; heavy wind is not.
        if day.wind_mph > 20:
            score -= 5
        elif day.wind_mph < 10:
            score += 2  # Light breeze bonus

    return score
