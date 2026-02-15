# =============================================================================
# core/synthesis.py  —  Recommendation Synthesis Logic (Stage 6)
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Takes all the analyzed data (weather, flights, hotels) and the user
#   profile, and produces a structured TravelRecommendation.
#
# WHY THIS IS IN core/ AND NOT LEFT TO THE LLM:
#   This is a subtle but important architectural decision.
#
#   You COULD let the LLM synthesize everything — it's good at writing
#   persuasive prose.  But the LOGIC of "which window is best" should be
#   deterministic and testable.
#
#   So we split the work:
#     - core/synthesis.py produces the STRUCTURED recommendation
#       (best window, alternatives, rejections, reasoning)
#     - The LLM agent then takes this structure and writes the
#       human-friendly narrative around it
#
#   This way:
#     1. The recommendation logic is unit-testable (no LLM involved)
#     2. The agent's prose is grounded in computed facts
#     3. If the agent hallucinates, the structure catches it
#
# EPISTEMIC HUMILITY:
#   The synthesizer assigns a CONFIDENCE level to its recommendation.
#   "High" means all signals align; "Medium" means trade-offs exist;
#   "Low" means the data is contradictory or insufficient.  This teaches
#   the agent (and the student) that honest uncertainty is a feature.
# =============================================================================

from core.models import (
    UserProfile,
    WeatherSummary,
    FlightSearchResult,
    HotelSearchResult,
    TravelRecommendation,
)


def synthesize_recommendation(
    user_profile: UserProfile,
    weather: WeatherSummary,
    flights: FlightSearchResult,
    hotels: HotelSearchResult,
) -> TravelRecommendation:
    """Produce a final travel recommendation by combining all data sources.

    This function implements the core DECISION LOGIC:
      1. Start with the best weather window
      2. Check if affordable flights exist for those dates
      3. Check if acceptable hotels are available
      4. Compute a confidence level based on alignment
      5. Suggest alternatives and explain rejections

    IMPORTANT: This function does NOT generate natural language prose.
    It produces a STRUCTURED recommendation that the agent will then
    narrate to the user.  Structure first, prose second.

    Args:
        user_profile: The traveler's preferences.
        weather: Analyzed weather data.
        flights: Analyzed flight data.
        hotels: Analyzed hotel data.

    Returns:
        A TravelRecommendation with all fields populated.
    """

    # =========================================================================
    # STEP 1: Identify candidate windows from weather
    # =========================================================================
    # The weather analysis already identified best/worst windows.
    # We use the best window as our primary recommendation.
    recommended_window = weather.best_window
    worst_window = weather.worst_window

    # =========================================================================
    # STEP 2: Check flight affordability for the recommended window
    # =========================================================================
    # Find flights that depart within or near the best weather window.
    best_start = weather.best_window.split(" to ")[0] if " to " in weather.best_window else ""

    # Filter flights for the recommended window
    window_flights = [
        f for f in flights.options
        if f.departure_date >= best_start
    ][:5]  # Limit to top 5 for analysis

    # Budget assessment
    affordable_flights = [
        f for f in window_flights
        if f.price_usd <= user_profile.airfare_budget_hard
    ]
    ideal_flights = [
        f for f in window_flights
        if f.price_usd <= user_profile.airfare_budget_soft
    ]

    flight_ok = len(affordable_flights) > 0
    flight_ideal = len(ideal_flights) > 0

    # =========================================================================
    # STEP 3: Check hotel availability and fit
    # =========================================================================
    # Filter hotels within budget
    budget_hotels = [
        h for h in hotels.options
        if user_profile.hotel_budget_min <= h.nightly_rate <= user_profile.hotel_budget_max
    ]
    brand_hotels = [
        h for h in budget_hotels
        if h.brand in user_profile.preferred_hotel_brands
    ]
    hotel_ok = len(budget_hotels) > 0
    hotel_ideal = len(brand_hotels) > 0

    # =========================================================================
    # STEP 4: Compute confidence level
    # =========================================================================
    # Confidence is based on how well all three dimensions align.
    # This is EPISTEMIC — the system is honest about how sure it is.
    confidence = _compute_confidence(
        weather_storm_days=weather.storm_risk_days,
        flight_ok=flight_ok,
        flight_ideal=flight_ideal,
        hotel_ok=hotel_ok,
        hotel_ideal=hotel_ideal,
    )

    # =========================================================================
    # STEP 5: Build reasoning narrative
    # =========================================================================
    reasoning_parts = []

    # Weather reasoning
    reasoning_parts.append(
        f"Weather: The period {recommended_window} offers the best conditions "
        f"for your temperature preference ({user_profile.preferred_temp_min_f}–"
        f"{user_profile.preferred_temp_max_f}°F). "
        f"Average highs: {weather.avg_high_f}°F."
    )
    if weather.storm_risk_days > 0:
        reasoning_parts.append(
            f"⚠ {weather.storm_risk_days} days in the forecast period have storm risk. "
            f"The worst period is {worst_window} — avoid these dates."
        )

    # Flight reasoning
    if flight_ideal:
        cheapest = min(f.price_usd for f in ideal_flights)
        reasoning_parts.append(
            f"Flights: Found options within your ideal budget. "
            f"Best price: ${cheapest}."
        )
    elif flight_ok:
        cheapest = min(f.price_usd for f in affordable_flights)
        reasoning_parts.append(
            f"Flights: Options available within your hard budget limit. "
            f"Best price: ${cheapest} (above your ideal of "
            f"${user_profile.airfare_budget_soft} but within "
            f"${user_profile.airfare_budget_hard})."
        )
    else:
        reasoning_parts.append(
            f"Flights: ⚠ No flights found within your "
            f"${user_profile.airfare_budget_hard} budget for this window."
        )

    # Hotel reasoning
    if hotel_ideal:
        top = brand_hotels[0]
        reasoning_parts.append(
            f"Hotels: {top.name} ({top.brand}) at ${top.nightly_rate}/night "
            f"matches your brand preference and budget."
        )
    elif hotel_ok:
        top = budget_hotels[0]
        reasoning_parts.append(
            f"Hotels: {top.name} at ${top.nightly_rate}/night fits your budget "
            f"(no preferred-brand match found in budget range)."
        )
    else:
        reasoning_parts.append(
            "Hotels: ⚠ No options within your budget range."
        )

    # =========================================================================
    # STEP 6: Generate alternatives and rejections
    # =========================================================================
    alternatives = _generate_alternatives(weather, flights, user_profile)
    rejections = _generate_rejections(weather, flights, user_profile)

    # =========================================================================
    # STEP 7: Assemble the final recommendation
    # =========================================================================
    return TravelRecommendation(
        recommended_window=recommended_window,
        confidence=confidence,
        summary=(
            f"Based on your preferences, {recommended_window} is the "
            f"{'best' if confidence == 'High' else 'most suitable'} time "
            f"to visit Maui. {confidence} confidence."
        ),
        reasoning="\n".join(reasoning_parts),
        alternative_windows=alternatives,
        rejected_options=rejections,
        weather_summary=weather.summary,
        flight_summary=flights.summary,
        hotel_summary=hotels.summary,
    )


def _compute_confidence(
    weather_storm_days: int,
    flight_ok: bool,
    flight_ideal: bool,
    hotel_ok: bool,
    hotel_ideal: bool,
) -> str:
    """Compute a confidence level for the recommendation.

    Confidence is NOT just "how good is the trip."  It's "how SURE are
    we that this is the right recommendation."  There's a difference:
      - High: Weather is great, flights are affordable, hotels fit perfectly
      - Medium: Most things work but there are trade-offs
      - Low: Significant issues in one or more dimensions

    This is an EPISTEMIC judgment — it tells the user (and the agent)
    how much trust to place in the recommendation.

    Returns: "High", "Medium", or "Low"
    """
    score = 0

    # Weather contributes to confidence
    if weather_storm_days == 0:
        score += 3
    elif weather_storm_days <= 2:
        score += 1

    # Flight affordability
    if flight_ideal:
        score += 3  # Under soft budget = high confidence
    elif flight_ok:
        score += 1  # Under hard budget = moderate confidence

    # Hotel fit
    if hotel_ideal:
        score += 3  # Brand match + budget = high confidence
    elif hotel_ok:
        score += 1  # Budget only = moderate confidence

    # Map score to confidence level
    if score >= 7:
        return "High"
    elif score >= 4:
        return "Medium"
    else:
        return "Low"


def _generate_alternatives(
    weather: WeatherSummary,
    flights: FlightSearchResult,
    profile: UserProfile,
) -> list[str]:
    """Generate 1-2 alternative travel windows.

    Alternatives are windows that are ALMOST as good as the primary
    recommendation.  They give the user options — because real travel
    advice is never "take it or leave it."

    Returns:
        A list of human-readable alternative descriptions.
    """
    alternatives = []

    # Look for the second-best weather window
    # (In a more sophisticated system, we'd run the full scoring pipeline
    # on multiple windows.  For the demo, we use heuristics.)
    if weather.daily_forecasts:
        # Find a good window that's NOT the best window
        best_start = weather.best_window.split(" to ")[0]
        for i in range(len(weather.daily_forecasts) - profile.trip_length_nights):
            window_start = weather.daily_forecasts[i].date
            if window_start == best_start:
                continue
            window = weather.daily_forecasts[i:i + profile.trip_length_nights]
            storms = sum(1 for d in window if d.is_storm_risk)
            rain = sum(1 for d in window if d.precipitation_pct > 40)
            if storms == 0 and rain <= 2:
                # Found a decent alternative
                window_end = weather.daily_forecasts[
                    i + profile.trip_length_nights - 1
                ].date
                alternatives.append(
                    f"{window_start} to {window_end}: Decent weather "
                    f"({rain} rainy day(s), no storm risk)"
                )
                if len(alternatives) >= 2:
                    break

    return alternatives


def _generate_rejections(
    weather: WeatherSummary,
    flights: FlightSearchResult,
    profile: UserProfile,
) -> list[str]:
    """Explain why certain periods were rejected.

    This is TRANSPARENCY — the agent doesn't just say "go on July 21"
    but also explains "don't go on July 18 because of storms."

    Real advisors do this.  It builds trust and helps the user understand
    the trade-offs.

    Returns:
        A list of human-readable rejection explanations.
    """
    rejections = []

    # Storm window rejection
    if weather.storm_risk_days > 0:
        rejections.append(
            f"Period around {weather.worst_window}: "
            f"{weather.storm_risk_days} storm-risk days. "
            f"With your comfort priority of {profile.comfort_priority}/10, "
            f"this window carries too much weather risk."
        )

    # Budget rejection — if the overall average is too high
    if flights.average_price > profile.airfare_budget_hard:
        rejections.append(
            f"Average airfare (${flights.average_price}) exceeds your hard "
            f"budget of ${profile.airfare_budget_hard}. Consider traveling "
            f"on weekdays for lower fares."
        )

    # Temperature rejection — if some periods are too hot/cold
    if weather.daily_forecasts:
        hot_days = sum(
            1 for f in weather.daily_forecasts
            if f.high_f > profile.preferred_temp_max_f + 5
        )
        if hot_days > 3:
            rejections.append(
                f"{hot_days} days forecast above "
                f"{profile.preferred_temp_max_f + 5}°F, which significantly "
                f"exceeds your preferred maximum of "
                f"{profile.preferred_temp_max_f}°F."
            )

    return rejections
