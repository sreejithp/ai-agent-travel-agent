# =============================================================================
# core/weather.py  —  Weather Data & Analysis Logic
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Generates mock weather forecasts for Maui and analyzes them.
#
# KEY DESIGN DECISIONS:
#
# 1. WHY MOCK DATA INSTEAD OF A REAL API?
#    - A real weather API (OpenWeatherMap, WeatherAPI) would make this demo
#      dependent on API keys, rate limits, and network access.
#    - The mock data is *designed* to create interesting scenarios: a storm
#      window, a perfect weather window, and average days in between.
#    - The INTERFACE is identical to what a real API wrapper would provide,
#      so swapping in a real API is a one-module change.
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
#    identifies the best/worst windows, and returns a SUMMARY.  The agent
#    gets a clean, actionable briefing.
#
# 3. THE SEPARATION OF "FETCH" AND "ANALYZE":
#    - get_forecast() returns raw-ish data (list of DayForecast)
#    - analyze_weather() takes that data + user preferences and produces
#      a WeatherSummary with a best_window recommendation
#    This separation means you can test the analysis logic independently
#    of the data source.
# =============================================================================

from datetime import datetime, timedelta
import random

from core.models import DayForecast, WeatherSummary, UserProfile


def get_forecast(destination: str, start_date: str, days: int = 30) -> list[DayForecast]:
    """Generate a mock weather forecast for Maui.

    In production, this would call a weather API.  The mock data creates
    a realistic pattern:
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
    best_score = -999
    worst_score = 999
    best_start = 0
    worst_start = 0

    for i in range(len(forecasts) - trip_len):
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

    # --- Generate human-readable summary ---
    # This is what the agent will actually "read."  It's concise and
    # decision-relevant — not a data dump.
    summary_parts = []
    summary_parts.append(
        f"Over the next {n} days, {destination} will see average highs "
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
