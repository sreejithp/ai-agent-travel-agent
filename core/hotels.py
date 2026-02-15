# =============================================================================
# core/hotels.py  —  Hotel Search & Evaluation Logic
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Generates mock hotel data for Maui and evaluates options against
#   user preferences (budget, brand loyalty, comfort needs).
#
# KEY CONCEPT — ANOMALOUS PRICING:
#   The spec requires us to "surface anomalous pricing (e.g., storm
#   discounts)."  This is a GREAT teaching moment:
#
#   A naive agent sees a cheap hotel and says "great deal!"  A SMART
#   agent asks "WHY is it cheap?"  If the price dropped because it's
#   storm season, the low price is a RED FLAG, not a bargain.
#
#   Our hotels include a `has_storm_discount` flag and `discount_reason`
#   field so the agent can reason about this trade-off explicitly.
#
# BRAND LOYALTY:
#   Real travelers have loyalty programs (Marriott Bonvoy, Hilton Honors).
#   A $250/night Marriott might be worth MORE to a Marriott loyalist than
#   a $220/night Hyatt because of points, upgrades, and status benefits.
#   The scoring function accounts for this.
# =============================================================================

import random
from core.models import HotelOption, HotelSearchResult, UserProfile


# -----------------------------------------------------------------------------
# Mock hotel inventory for Maui
# -----------------------------------------------------------------------------
# Each hotel has a base rate that gets modified by season/storm effects.
# The brands, locations, and ratings are chosen to create interesting
# decision points for the agent.
# -----------------------------------------------------------------------------
_MAUI_HOTELS = [
    {
        "name": "Marriott Wailea Beach Resort",
        "brand": "Marriott",
        "base_rate": 280,
        "rating": 4.3,
        "location": "Wailea Beach",
    },
    {
        "name": "Grand Hyatt Maui",
        "brand": "Hyatt",
        "base_rate": 350,
        "rating": 4.6,
        "location": "Ka'anapali",
    },
    {
        "name": "Four Seasons Resort Maui",
        "brand": "Four Seasons",
        "base_rate": 550,
        "rating": 4.8,
        "location": "Wailea",
    },
    {
        "name": "Hilton Garden Inn Maui",
        "brand": "Hilton",
        "base_rate": 180,
        "rating": 4.0,
        "location": "Kahului",
    },
    {
        "name": "Ritz-Carlton Kapalua",
        "brand": "Ritz-Carlton",
        "base_rate": 480,
        "rating": 4.7,
        "location": "Kapalua Bay",
    },
    {
        "name": "Courtyard by Marriott Maui",
        "brand": "Marriott",
        "base_rate": 160,
        "rating": 3.9,
        "location": "Kahului",
    },
    {
        "name": "Andaz Maui at Wailea",
        "brand": "Hyatt",
        "base_rate": 420,
        "rating": 4.5,
        "location": "Wailea",
    },
]


def search_hotels(
    destination: str,
    check_in: str,
    check_out: str,
    is_storm_period: bool = False,
) -> list[HotelOption]:
    """Search for available hotels at a destination.

    Args:
        destination: Where to search (e.g., "Maui, HI").
        check_in: Check-in date (ISO format).
        check_out: Check-out date (ISO format).
        is_storm_period: Whether the dates overlap with a storm window.
            This triggers discounted pricing on some hotels.

    Returns:
        A list of HotelOption objects.

    IDEMPOTENCY NOTE:
        Same inputs → same outputs (seeded random).  The agent can safely
        retry this tool without getting different results.
    """
    random.seed(42)

    from datetime import datetime
    nights = (
        datetime.strptime(check_out, "%Y-%m-%d")
        - datetime.strptime(check_in, "%Y-%m-%d")
    ).days

    options = []
    for hotel in _MAUI_HOTELS:
        # --- Calculate nightly rate ---
        rate = hotel["base_rate"]

        # Storm discount: some hotels lower prices during storm season
        # to attract budget travelers.  This is the "anomalous pricing"
        # the spec wants us to surface.
        storm_discount = False
        discount_reason = None
        if is_storm_period:
            # Higher-end hotels offer bigger discounts (they have more to lose)
            if hotel["base_rate"] > 300:
                rate = int(rate * 0.70)  # 30% off!
                storm_discount = True
                discount_reason = "Storm season discount — 30% off due to weather risk"
            elif hotel["base_rate"] > 200:
                rate = int(rate * 0.85)  # 15% off
                storm_discount = True
                discount_reason = "Storm season discount — 15% off"

        # Small random variation (±5%) to simulate real pricing fluctuation
        rate = int(rate * random.uniform(0.95, 1.05))

        options.append(HotelOption(
            name=hotel["name"],
            brand=hotel["brand"],
            nightly_rate=rate,
            total_cost=rate * nights,
            rating=hotel["rating"],
            location=hotel["location"],
            has_storm_discount=storm_discount,
            discount_reason=discount_reason,
        ))

    return options


def evaluate_hotels(
    hotels: list[HotelOption],
    user_profile: UserProfile,
) -> HotelSearchResult:
    """Evaluate hotels against user preferences and generate a summary.

    This is where brand loyalty, budget constraints, and anomalous pricing
    all come together.  The agent receives a narrative summary that captures
    the key trade-offs.

    SCORING APPROACH:
      Each hotel gets a composite score based on:
        1. Budget fit:    Is the rate within the user's range?
        2. Brand match:   Does the hotel brand match user loyalty?
        3. Quality:       Guest rating (higher = better)
        4. Storm warning: Discounted due to storms? Flag it.

    Args:
        hotels: List of available hotels.
        user_profile: The traveler's preferences.

    Returns:
        HotelSearchResult with sorted options and narrative summary.
    """
    if not hotels:
        return HotelSearchResult(
            destination="Maui, HI",
            check_in="N/A",
            check_out="N/A",
            summary="No hotels found.",
        )

    # --- Score and sort hotels ---
    scored_hotels = []
    for hotel in hotels:
        score = _score_hotel(hotel, user_profile)
        scored_hotels.append((score, hotel))

    # Sort by score descending (best first)
    scored_hotels.sort(key=lambda x: x[0], reverse=True)
    sorted_options = [h for _, h in scored_hotels]

    # --- Build narrative summary ---
    in_budget = [
        h for h in hotels
        if user_profile.hotel_budget_min <= h.nightly_rate <= user_profile.hotel_budget_max
    ]
    brand_matches = [
        h for h in hotels
        if h.brand in user_profile.preferred_hotel_brands
    ]
    storm_discounted = [h for h in hotels if h.has_storm_discount]

    summary_parts = [f"Found {len(hotels)} hotels in Maui."]

    if in_budget:
        rates = [h.nightly_rate for h in in_budget]
        summary_parts.append(
            f"{len(in_budget)} are within your ${user_profile.hotel_budget_min}–"
            f"${user_profile.hotel_budget_max}/night budget "
            f"(range: ${min(rates)}–${max(rates)}/night)."
        )
    else:
        summary_parts.append(
            f"⚠ No hotels fall within your ${user_profile.hotel_budget_min}–"
            f"${user_profile.hotel_budget_max}/night budget."
        )

    if brand_matches:
        brands = set(h.brand for h in brand_matches)
        summary_parts.append(
            f"Your preferred brand(s) ({', '.join(brands)}) "
            f"{'have' if len(brand_matches) > 1 else 'has'} "
            f"{len(brand_matches)} option(s) available."
        )

    if storm_discounted:
        summary_parts.append(
            f"⚠ {len(storm_discounted)} hotel(s) show storm-season discounts. "
            f"Lower prices may reflect weather risk — consider carefully."
        )

    # Highlight the top recommendation
    top = sorted_options[0]
    summary_parts.append(
        f"Top pick: {top.name} ({top.brand}) at ${top.nightly_rate}/night, "
        f"rated {top.rating}/5.0."
    )

    return HotelSearchResult(
        destination="Maui, HI",
        check_in=sorted_options[0].name if sorted_options else "N/A",  # Simplified
        check_out="N/A",
        options=sorted_options,
        summary=" ".join(summary_parts),
    )


def _score_hotel(hotel: HotelOption, profile: UserProfile) -> float:
    """Score a hotel for a specific user.

    Scoring breakdown:
      - Budget fit:     0–30 points (in range = 30, out = scaled penalty)
      - Brand loyalty:  0–20 points (preferred brand = 20)
      - Rating:         0–25 points (scaled from guest rating)
      - Storm warning:  -15 if discounted due to storms AND user is comfort-sensitive

    The weights reflect what real travelers care about:
      Budget > Quality > Brand > Anomalies

    Args:
        hotel: The hotel to score.
        profile: The user whose preferences define "good."

    Returns:
        A numeric score (higher = better).
    """
    score = 0.0

    # --- Budget fit (0-30 points) ---
    if profile.hotel_budget_min <= hotel.nightly_rate <= profile.hotel_budget_max:
        score += 30  # Within budget = full points
    elif hotel.nightly_rate < profile.hotel_budget_min:
        # Too cheap — user might see this as "sketchy"
        score += 10  # Some points (it's cheap, not terrible)
    else:
        # Over budget — penalize proportionally
        overage = hotel.nightly_rate - profile.hotel_budget_max
        score += max(0, 25 - overage * 0.3)  # Gradual penalty

    # --- Brand loyalty (0-20 points) ---
    if hotel.brand in profile.preferred_hotel_brands:
        score += 20  # Preferred brand = loyalty points, upgrades, familiarity

    # --- Rating quality (0-25 points) ---
    # Scale: 3.0 rating → 0 points, 5.0 rating → 25 points
    score += max(0, (hotel.rating - 3.0) * 12.5)

    # --- Storm discount warning ---
    # If a hotel is cheap because of storms AND the user is comfort-sensitive,
    # that "deal" is actually a problem.
    if hotel.has_storm_discount and profile.comfort_priority >= 7:
        score -= 15  # Penalize: the "deal" comes with weather risk

    return score
