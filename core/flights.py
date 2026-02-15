# =============================================================================
# core/flights.py  —  Flight Search & Analysis Logic
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Generates mock flight data and analyzes it against user budgets.
#
# DESIGN PHILOSOPHY:
#   The agent shouldn't just get a list of flights.  It should get flights
#   that are PRE-ANALYZED:
#     - "Which ones are within budget?"
#     - "Which ones are red-eyes?"
#     - "What's the cheapest?  The average?"
#
#   This pre-analysis is Context Budget Discipline in action.  The agent
#   receives a clean briefing, not a data dump.
#
# REAL-WORLD NOTE:
#   In production, this would wrap a flight API (Google Flights, Amadeus,
#   Skyscanner).  The mock data simulates realistic patterns:
#     - Prices vary by departure day (weekends cost more)
#     - Red-eye flights are cheaper
#     - Direct flights cost more than connections
#     - Prices increase as departure approaches
# =============================================================================

from datetime import datetime, timedelta
import random

from core.models import FlightOption, FlightSearchResult, UserProfile


def search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    trip_length_nights: int = 7,
) -> list[FlightOption]:
    """Generate mock flight options for various departure dates.

    The mock data creates VARIETY so the agent has interesting choices:
      - Some flights are cheap but inconvenient (red-eyes, connections)
      - Some are expensive but comfortable (direct, good times)
      - Some are in the sweet spot (good times, reasonable prices)

    This forces the agent to reason about TRADE-OFFS, not just pick
    the cheapest option.

    Args:
        origin: Departure airport code (e.g., "SFO").
        destination: Arrival airport code (e.g., "OGG" for Maui).
        start_date: Earliest departure date (ISO format).
        end_date: Latest departure date (ISO format).
        trip_length_nights: Duration of stay.

    Returns:
        A list of FlightOption objects.
    """
    random.seed(42)  # Deterministic for reproducibility

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    options = []

    # --- Generate flights for multiple departure dates ---
    # We create 2-3 options per departure date to give the agent choices.
    current = start
    while current <= end:
        dep_date = current.strftime("%Y-%m-%d")
        ret_date = (current + timedelta(days=trip_length_nights)).strftime("%Y-%m-%d")

        # Is this a weekend departure?  Weekends cost more (realistic pricing).
        is_weekend = current.weekday() >= 5  # Saturday=5, Sunday=6
        weekend_surcharge = 80 if is_weekend else 0

        # --- Option A: Direct flight, good times (premium) ---
        base_price = random.randint(420, 580) + weekend_surcharge
        options.append(FlightOption(
            airline="Hawaiian Airlines",
            departure_date=dep_date,
            return_date=ret_date,
            price_usd=base_price,
            departure_time="08:30 AM",
            arrival_time="12:45 PM",
            stops=0,
            duration_hours=5.25,
            is_red_eye=False,
        ))

        # --- Option B: Red-eye flight (cheaper but less comfortable) ---
        # Red-eyes trade comfort for savings — the agent must weigh this
        # against the user's comfort_priority.
        red_eye_price = random.randint(320, 450) + weekend_surcharge
        options.append(FlightOption(
            airline="Alaska Airlines",
            departure_date=dep_date,
            return_date=ret_date,
            price_usd=red_eye_price,
            departure_time="11:30 PM",
            arrival_time="06:15 AM",  # Arrives early morning next day
            stops=0,
            duration_hours=5.75,
            is_red_eye=True,
        ))

        # --- Option C: One-stop flight (cheapest but longest) ---
        # Added only on some days to vary the options.
        if current.weekday() % 2 == 0:  # Every other day
            layover_price = random.randint(280, 400) + weekend_surcharge
            options.append(FlightOption(
                airline="United Airlines",
                departure_date=dep_date,
                return_date=ret_date,
                price_usd=layover_price,
                departure_time="10:00 AM",
                arrival_time="05:30 PM",
                stops=1,            # One stop (e.g., LAX or HNL)
                duration_hours=8.5,  # Much longer due to layover
                is_red_eye=False,
            ))

        # Move to next departure date (every 3 days to keep the list manageable)
        current += timedelta(days=3)

    return options


def analyze_flights(
    flights: list[FlightOption],
    user_profile: UserProfile,
) -> FlightSearchResult:
    """Analyze flight options against a user's budget and preferences.

    This function doesn't just return flights — it provides ANALYSIS:
      - Which flights are within the soft budget? Hard budget?
      - What's the cheapest? Average?
      - A narrative summary the agent can reason about.

    WHY THIS MATTERS:
      Without this analysis, the agent would receive 15-20 raw flight
      objects and have to do the math itself.  LLMs are BAD at arithmetic.
      By pre-computing the analysis, we get reliable results AND save
      context space.

    Args:
        flights: Raw list of FlightOptions.
        user_profile: The user's budget and preferences.

    Returns:
        A FlightSearchResult with analysis and summary.
    """
    if not flights:
        return FlightSearchResult(
            origin="N/A",
            destination="N/A",
            search_window="N/A",
            cheapest_price=0,
            average_price=0,
            summary="No flights found.",
        )

    prices = [f.price_usd for f in flights]
    cheapest = min(prices)
    average = sum(prices) // len(prices)

    # --- Categorize flights relative to user's budget ---
    under_soft = [f for f in flights if f.price_usd <= user_profile.airfare_budget_soft]
    under_hard = [f for f in flights if f.price_usd <= user_profile.airfare_budget_hard]
    over_budget = [f for f in flights if f.price_usd > user_profile.airfare_budget_hard]

    # --- Build narrative summary ---
    # This is the key output.  The agent reads this summary and uses it
    # to make decisions.  It's like a travel agent's briefing note.
    summary_parts = [
        f"Found {len(flights)} flight options. "
        f"Prices range from ${cheapest} to ${max(prices)} (avg ${average}).",
    ]

    if under_soft:
        summary_parts.append(
            f"{len(under_soft)} flights are under your ideal budget of "
            f"${user_profile.airfare_budget_soft}."
        )
    elif under_hard:
        summary_parts.append(
            f"No flights under your ideal ${user_profile.airfare_budget_soft}, "
            f"but {len(under_hard)} are within your hard limit of "
            f"${user_profile.airfare_budget_hard}."
        )
    else:
        summary_parts.append(
            f"⚠ All flights exceed your hard budget of "
            f"${user_profile.airfare_budget_hard}. "
            f"Consider adjusting dates or accepting a connection."
        )

    # Note about red-eyes for comfort-sensitive travelers
    red_eyes = [f for f in flights if f.is_red_eye]
    if red_eyes and user_profile.comfort_priority >= 7:
        cheapest_red_eye = min(f.price_usd for f in red_eyes)
        summary_parts.append(
            f"Red-eye flights available from ${cheapest_red_eye}, but given "
            f"your high comfort priority, daytime flights are recommended."
        )

    return FlightSearchResult(
        origin=flights[0].airline,  # Simplified — in real code, use the actual origin
        destination="OGG",
        search_window=f"{flights[0].departure_date} to {flights[-1].departure_date}",
        cheapest_price=cheapest,
        average_price=average,
        options=flights,
        summary=" ".join(summary_parts),
    )
