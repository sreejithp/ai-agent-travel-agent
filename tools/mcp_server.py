# =============================================================================
# tools/mcp_server.py  —  FastMCP Tool Server (ALL tools in one place)
# =============================================================================
#
# WHAT THIS FILE DOES:
#   Defines ALL MCP tools that the agent can call.  Each tool is a thin
#   wrapper around a core/ function — it handles input/output formatting
#   and enforces Context Budget Discipline.
#
# HOW IT WORKS (the flow):
#   1. The Google ADK agent decides it needs information (e.g., weather)
#   2. It calls a tool by name via MCP (e.g., "get_weather_forecast")
#   3. FastMCP routes the call to the decorated function below
#   4. The function calls core/ logic, formats the result, and returns it
#   5. The agent receives a clean, summarized response
#
# TOOL NAMING CONVENTIONS:
#   - get_*   → Read-only retrieval (idempotent, safe to retry)
#   - search_* → Query with filters (idempotent, safe to retry)
#   - analyze_* → Compute derived insights (idempotent, safe to retry)
#   All tools in this project are read-only.  If we had write operations
#   (e.g., "book_flight"), we'd use make_* or create_* prefixes and
#   add idempotency guards.
#
# CONTEXT BUDGET DISCIPLINE:
#   Every tool returns a DICT (not raw JSON, not a dataclass).
#   The dict contains ONLY what the agent needs for reasoning.
#   No tool returns unbounded lists or raw data dumps.
#
# RUNNING THIS SERVER:
#   This module creates a FastMCP server instance that can be:
#     a) Run standalone:  python -m tools.mcp_server
#     b) Connected to the Google ADK agent via stdio transport
# =============================================================================

import json
import logging
import sys

from fastmcp import FastMCP
from dataclasses import asdict

# --- Import core logic ---
# Notice: we import from core/, never from agent/.
# The tools layer depends on core/ and nothing else.
from core.user_profile import get_profile, list_available_users
from core.weather import get_forecast, analyze_weather
from core.flights import search_flights, analyze_flights
from core.hotels import search_hotels, evaluate_hotels

# =============================================================================
# Logging Setup
# =============================================================================
# We log to STDERR because the MCP server communicates with the agent via
# STDOUT (stdin/stdout is the MCP transport).  If we logged to stdout, our
# log messages would corrupt the MCP JSON protocol and crash the agent.
#
# STDERR is safe — it's visible in the terminal but doesn't interfere with
# the MCP message stream.
#
# ANSI COLOR CODES:
#   We use ANSI escape sequences to color-code log lines in the terminal:
#     - CYAN for incoming requests (tool name + parameters)
#     - GREEN for response JSON
#     - YELLOW for intermediate status/progress messages
#   This makes it easy to visually scan tool calls vs responses in the output.
#
#   These codes work in virtually all modern terminals (macOS Terminal, iTerm2,
#   VS Code terminal, Linux terminals).  On Windows, they work in Windows
#   Terminal and PowerShell 7+.
# =============================================================================

# ANSI color codes for terminal output
_CYAN = "\033[36m"     # Requests (tool calls with params)
_GREEN = "\033[32m"    # Responses (JSON output)
_YELLOW = "\033[33m"   # Status/progress messages
_RESET = "\033[0m"     # Reset to default terminal color

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MCP] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)


def _log_request(tool_name: str, **params) -> None:
    """Log an incoming tool call with its parameters in CYAN."""
    param_str = ", ".join(f"{k}={v!r}" for k, v in params.items())
    logging.info(f"{_CYAN}{tool_name} called with: {param_str}{_RESET}")


def _log_status(message: str) -> None:
    """Log an intermediate status message in YELLOW."""
    logging.info(f"{_YELLOW}  → {message}{_RESET}")


def _log_response(tool_name: str, result: dict) -> dict:
    """Log the tool response as compact JSON in GREEN, then return it."""
    logging.info(f"{_GREEN}  ← {tool_name} response: {json.dumps(result, separators=(',', ':'))}{_RESET}")
    return result


# =============================================================================
# Create the FastMCP server instance
# =============================================================================
# The name "maui-travel-advisor" becomes the server identity in MCP.
# The agent connects to this server and discovers available tools.
mcp = FastMCP("maui-travel-advisor")


# =============================================================================
# TOOL 1: get_user_profile
# =============================================================================
# This is the FIRST tool the agent should call (Stage 2).
# Without a user profile, the agent can't personalize anything.
#
# The docstring is critical — the LLM reads it to decide WHEN to call this
# tool.  Notice how specific it is: it tells the agent exactly what data
# it will get and why it's needed.
# =============================================================================
@mcp.tool()
def get_user_profile(user_id: str) -> dict:
    """Retrieve a traveler's profile containing their preferences and constraints.

    WHEN TO CALL THIS: Call this FIRST, before any other tool. The user's
    preferences (temperature, budget, brands, comfort level) are required
    to interpret weather, flight, and hotel data meaningfully.

    Args:
        user_id: The user's identifier (e.g., "alex", "jordan", "sam").
                 Use "alex" as default if no user is specified.

    Returns:
        A dict with fields:
          - name: The user's full name
          - preferred_temp_min_f / preferred_temp_max_f: Ideal temperature range (°F)
          - airfare_budget_soft: Ideal max airfare (would like to stay under)
          - airfare_budget_hard: Absolute max airfare (deal-breaker above)
          - hotel_budget_min / hotel_budget_max: Acceptable nightly rate range
          - preferred_hotel_brands: List of loyalty-program brands
          - trip_length_nights: Desired trip duration
          - flexibility_days: How many days the travel dates can shift
          - comfort_priority: 1-10 scale (10 = very comfort-sensitive)

        Returns an error message if the user_id is not found.
    """
    _log_request("get_user_profile", user_id=user_id)

    profile = get_profile(user_id)
    if profile is None:
        available = list_available_users()
        _log_status(f"User not found. Available: {available}")
        return _log_response("get_user_profile", {
            "error": f"User '{user_id}' not found.",
            "available_users": available,
            "hint": "Try one of the available user IDs listed above.",
        })
    # Convert dataclass → dict for JSON serialization over MCP.
    # asdict() recursively converts nested dataclasses too.
    _log_status(f"Found profile for {profile.name}")
    return _log_response("get_user_profile", asdict(profile))


# =============================================================================
# TOOL 2: get_weather_forecast
# =============================================================================
# This tool demonstrates Context Budget Discipline beautifully.
# It does NOT return 30 raw DayForecast objects.  Instead, it:
#   1. Fetches raw forecast data (core/weather.py → get_forecast)
#   2. Analyzes it against user preferences (core/weather.py → analyze_weather)
#   3. Returns a SUMMARY with just the fields the agent needs
#
# The agent gets: averages, storm counts, best/worst windows, and a
# narrative summary.  NOT: 30 temperature readings and precipitation values.
# =============================================================================
@mcp.tool()
def get_weather_forecast(
    destination: str,
    start_date: str,
    days: int = 30,
    user_id: str = "alex",
) -> dict:
    """Get a summarized weather forecast analyzed against user preferences.

    WHEN TO CALL THIS: After retrieving the user profile. The weather
    analysis is personalized — it scores conditions against the user's
    temperature preferences and comfort level.

    The tool summarizes raw data into actionable insights:
    - Average temperatures for the period
    - Number of rainy and storm-risk days
    - Best and worst travel windows
    - A narrative summary

    Args:
        destination: The travel destination (e.g., "Maui, HI").
        start_date: Start date for the forecast in ISO format (e.g., "2025-07-10").
        days: Number of days to forecast (default: 30, max recommended: 45).
        user_id: The user ID to personalize the analysis for.

    Returns:
        A dict with:
          - destination, period: Where and when
          - avg_high_f, avg_low_f: Temperature averages
          - rainy_days, storm_risk_days: Counts of problematic days
          - best_window, worst_window: Recommended and avoid date ranges
          - summary: Human-readable 2-3 sentence analysis
    """
    _log_request("get_weather_forecast",
                 destination=destination, start_date=start_date,
                 days=days, user_id=user_id)

    # Step 1: Get user profile for personalized analysis
    profile = get_profile(user_id)
    if profile is None:
        _log_status(f"User '{user_id}' not found")
        return _log_response("get_weather_forecast", {
            "error": f"User '{user_id}' not found. Cannot personalize weather analysis."
        })

    # Step 2: Fetch raw forecast data
    forecasts = get_forecast(destination, start_date, days)
    _log_status(f"Got {len(forecasts)} days of forecast data")

    # Step 3: Analyze against user preferences
    summary = analyze_weather(forecasts, profile, destination)
    _log_status(f"Analysis: best_window={summary.best_window}, "
                f"storm_risk_days={summary.storm_risk_days}")

    # Step 4: Return SUMMARIZED data (Context Budget Discipline)
    # We explicitly exclude daily_forecasts from the output — the agent
    # doesn't need 30 individual day records.  The summary fields are enough.
    result = asdict(summary)
    # Remove the raw daily data to keep the response lean
    result.pop("daily_forecasts", None)
    return _log_response("get_weather_forecast", result)


# =============================================================================
# TOOL 3: search_and_analyze_flights
# =============================================================================
# This tool combines search + analysis in one call.
# WHY NOT TWO SEPARATE TOOLS?
#   Because the agent would always call them together, and splitting them
#   would waste a round-trip (LLM call + tool call).  In agent design,
#   fewer round-trips = faster + cheaper.
#
#   However, in the core/ layer, search and analyze ARE separate functions
#   (for testability).  The tool just composes them.
# =============================================================================
@mcp.tool()
def search_and_analyze_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    user_id: str = "alex",
) -> dict:
    """Search for flights and analyze them against the user's budget.

    WHEN TO CALL THIS: After retrieving the user profile and weather data.
    You need the weather data to know WHICH dates to search (best window),
    and the profile to evaluate affordability.

    Returns pre-analyzed results including:
    - Price range and average across all options
    - Count of flights within soft/hard budget limits
    - Warnings about red-eye flights for comfort-sensitive travelers
    - A narrative summary of the best options

    Args:
        origin: Departure airport code (e.g., "SFO", "LAX", "JFK").
        destination: Arrival airport code (e.g., "OGG" for Maui).
        start_date: Earliest acceptable departure date (ISO format).
        end_date: Latest acceptable departure date (ISO format).
        user_id: User ID for budget analysis.

    Returns:
        A dict with:
          - search_window: The date range searched
          - cheapest_price, average_price: Price statistics
          - summary: Narrative analysis of options vs budget
          - options: Top 5 flight options (limited for context budget)
            Each option includes: airline, dates, price, times, stops, duration
    """
    _log_request("search_and_analyze_flights",
                 origin=origin, destination=destination,
                 start_date=start_date, end_date=end_date, user_id=user_id)

    # Get profile for budget analysis
    profile = get_profile(user_id)
    if profile is None:
        _log_status(f"User '{user_id}' not found")
        return _log_response("search_and_analyze_flights", {"error": f"User '{user_id}' not found."})

    # Search flights
    flights = search_flights(
        origin=origin,
        destination=destination,
        start_date=start_date,
        end_date=end_date,
        trip_length_nights=profile.trip_length_nights,
    )
    _log_status(f"Found {len(flights)} flight options")

    # Analyze against user's budget
    result = analyze_flights(flights, profile)
    _log_status(f"Analysis: cheapest=${result.cheapest_price}, avg=${result.average_price}")

    # Convert to dict and LIMIT options to top 5
    # This is Context Budget Discipline: the agent doesn't need 20 options,
    # it needs the best 5 with analysis.
    result_dict = asdict(result)

    # Sort options: cheapest first, then limit
    result_dict["options"] = sorted(
        result_dict["options"],
        key=lambda x: x["price_usd"],
    )[:5]  # Only top 5!

    return _log_response("search_and_analyze_flights", result_dict)


# =============================================================================
# TOOL 4: search_and_evaluate_hotels
# =============================================================================
# Similar composition pattern to flights: search + evaluate in one call.
#
# SPECIAL FEATURE: is_storm_period parameter
#   The agent can (and should) pass this based on weather analysis.
#   If True, it triggers storm discounts — which are then FLAGGED
#   in the output so the agent can reason about them.
# =============================================================================
@mcp.tool()
def search_and_evaluate_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    user_id: str = "alex",
    is_storm_period: bool = False,
) -> dict:
    """Search for hotels and evaluate them against user preferences.

    WHEN TO CALL THIS: After weather and flight analysis. You need to
    know the travel dates (from weather/flight analysis) to search for
    the right check-in/check-out period.

    Returns hotels scored and ranked by:
    - Budget fit (within min/max range)
    - Brand loyalty match
    - Guest rating quality
    - Storm discount warnings (if applicable)

    Args:
        destination: Where to search (e.g., "Maui, HI").
        check_in: Check-in date (ISO format, e.g., "2025-07-21").
        check_out: Check-out date (ISO format, e.g., "2025-07-28").
        user_id: User ID for preference matching.
        is_storm_period: Whether dates overlap with storm risk.
            If True, some hotels will show storm-season discounts.
            These discounts are flagged so you can warn the user.

    Returns:
        A dict with:
          - summary: Narrative evaluation of options
          - options: Hotels sorted by fit score (best first)
            Each includes: name, brand, nightly_rate, total_cost, rating,
            location, has_storm_discount, discount_reason
    """
    _log_request("search_and_evaluate_hotels",
                 destination=destination, check_in=check_in,
                 check_out=check_out, user_id=user_id,
                 is_storm_period=is_storm_period)

    profile = get_profile(user_id)
    if profile is None:
        _log_status(f"User '{user_id}' not found")
        return _log_response("search_and_evaluate_hotels", {"error": f"User '{user_id}' not found."})

    # Search hotels
    hotels = search_hotels(
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        is_storm_period=is_storm_period,
    )
    _log_status(f"Found {len(hotels)} hotels")

    # Evaluate against user preferences
    result = evaluate_hotels(hotels, profile)
    _log_status(f"Top hotel: {result.options[0].name if result.options else 'none'}")

    # Convert and limit to top 5 options
    result_dict = asdict(result)
    result_dict["options"] = result_dict["options"][:5]

    return _log_response("search_and_evaluate_hotels", result_dict)


# =============================================================================
# TOOL 5: synthesize_travel_recommendation
# =============================================================================
# This is the FINAL tool call (Stage 6).  It takes all gathered data and
# produces a structured recommendation.
#
# NOTE: The agent could skip this tool and write its own recommendation
# from the data it has.  But using this tool ensures:
#   1. The recommendation logic is deterministic (in core/)
#   2. The scoring is consistent (not subject to LLM mood)
#   3. The structure is complete (all required fields)
# =============================================================================
@mcp.tool()
def synthesize_travel_recommendation(
    user_id: str,
    weather_destination: str = "Maui, HI",
    weather_start_date: str = "2025-07-10",
    weather_days: int = 30,
    flight_origin: str = "SFO",
    flight_destination: str = "OGG",
) -> dict:
    """Synthesize all data into a final, personalized travel recommendation.

    WHEN TO CALL THIS: As the LAST tool call, after gathering weather,
    flight, and hotel data. This tool combines everything into a structured
    recommendation with:
    - A recommended travel window
    - Confidence level (High/Medium/Low)
    - Detailed reasoning for the recommendation
    - 1-2 alternative windows
    - Explanations for why other periods were rejected

    This tool performs the full analysis pipeline internally, so you don't
    need to pass raw data from previous tool calls. Just provide the same
    parameters you used for weather and flight searches.

    Args:
        user_id: The user to generate the recommendation for.
        weather_destination: Destination for weather lookup.
        weather_start_date: Start date for weather analysis.
        weather_days: Days to forecast.
        flight_origin: Departure airport code.
        flight_destination: Arrival airport code.

    Returns:
        A complete recommendation dict with:
          - recommended_window: Best travel dates
          - confidence: "High", "Medium", or "Low"
          - summary: 2-3 sentence personalized summary
          - reasoning: Detailed explanation of why
          - alternative_windows: 1-2 other good options
          - rejected_options: Periods that were considered and discarded
          - weather_summary, flight_summary, hotel_summary: Component summaries
    """
    _log_request("synthesize_travel_recommendation",
                 user_id=user_id, weather_destination=weather_destination,
                 weather_start_date=weather_start_date, weather_days=weather_days,
                 flight_origin=flight_origin, flight_destination=flight_destination)

    from core.synthesis import synthesize_recommendation

    profile = get_profile(user_id)
    if profile is None:
        _log_status(f"User '{user_id}' not found")
        return _log_response("synthesize_travel_recommendation", {"error": f"User '{user_id}' not found."})

    # Run the full analysis pipeline
    forecasts = get_forecast(weather_destination, weather_start_date, weather_days)
    weather = analyze_weather(forecasts, profile, weather_destination)

    flights_raw = search_flights(
        flight_origin,
        flight_destination,
        weather_start_date,
        (
            __import__("datetime").datetime.strptime(weather_start_date, "%Y-%m-%d")
            + __import__("datetime").timedelta(days=weather_days)
        ).strftime("%Y-%m-%d"),
        profile.trip_length_nights,
    )
    flights = analyze_flights(flights_raw, profile)

    # Determine if the recommended window overlaps with storm period
    is_storm = weather.storm_risk_days > 0
    best_start = weather.best_window.split(" to ")[0] if " to " in weather.best_window else weather_start_date
    best_end_date = (
        __import__("datetime").datetime.strptime(best_start, "%Y-%m-%d")
        + __import__("datetime").timedelta(days=profile.trip_length_nights)
    ).strftime("%Y-%m-%d")

    hotels_raw = search_hotels(
        weather_destination, best_start, best_end_date, is_storm_period=False
    )
    hotels = evaluate_hotels(hotels_raw, profile)

    # Synthesize everything
    recommendation = synthesize_recommendation(profile, weather, flights, hotels)
    _log_status(f"Recommendation: window={recommendation.recommended_window}, "
                f"confidence={recommendation.confidence}")
    return _log_response("synthesize_travel_recommendation", asdict(recommendation))


# =============================================================================
# Server entry point
# =============================================================================
# When run directly (python -m tools.mcp_server), start the MCP server.
# The agent connects to this server via stdio transport.
# =============================================================================
if __name__ == "__main__":
    mcp.run()
