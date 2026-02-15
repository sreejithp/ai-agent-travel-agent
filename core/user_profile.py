# =============================================================================
# core/user_profile.py  —  User Profile Storage & Retrieval
# =============================================================================
#
# WHAT THIS MODULE DOES:
#   Manages user profiles — the traveler's preferences and constraints that
#   drive every decision the agent makes.
#
# WHY IT'S IN core/ (AND NOT IN tools/):
#   The *logic* of looking up a user's preferences is pure business logic.
#   It doesn't need MCP, Google ADK, or the internet.  The tools/ layer
#   will wrap this in an MCP tool, but the actual work happens here.
#
# WHY MOCK DATA?
#   In a real system, this would hit a database or user service.  For this
#   demo, we use a hardcoded dictionary.  But notice: the INTERFACE is
#   clean (get_profile(user_id) -> UserProfile).  Swapping in a real DB
#   later requires changing only this module — not the agent, not the tools.
#
# IDEMPOTENCY:
#   get_profile() is a pure read.  Calling it 100 times returns the same
#   result.  This is important because the agent might retry tool calls
#   if something goes wrong.
# =============================================================================

from core.models import UserProfile


# -----------------------------------------------------------------------------
# Mock user database
# -----------------------------------------------------------------------------
# In production, this would be a database query.  The mock data is designed
# to create interesting trade-offs for the agent:
#   - "alex" has a tight budget but flexible dates
#   - "jordan" has money but hates heat
#   - "sam" is a luxury traveler with strong brand loyalty
#
# Each profile is crafted so that the agent's recommendation will differ
# depending on who's asking — which is the whole point of personalization.
# -----------------------------------------------------------------------------
_MOCK_PROFILES: dict[str, UserProfile] = {
    "alex": UserProfile(
        name="Alex Chen",
        preferred_temp_min_f=72,
        preferred_temp_max_f=85,
        airfare_budget_soft=450,       # Would *like* to pay under $450
        airfare_budget_hard=650,       # Absolutely won't pay over $650
        hotel_budget_min=120,          # Won't stay anywhere under $120/night
        hotel_budget_max=250,          # Max $250/night
        preferred_hotel_brands=["Marriott", "Hilton"],  # Has loyalty points
        trip_length_nights=7,
        flexibility_days=5,            # Very flexible — can shift ±5 days
        comfort_priority=6,            # Moderate comfort needs
    ),
    "jordan": UserProfile(
        name="Jordan Rivera",
        preferred_temp_min_f=68,
        preferred_temp_max_f=80,       # Doesn't like it too hot!
        airfare_budget_soft=600,
        airfare_budget_hard=900,
        hotel_budget_min=200,
        hotel_budget_max=400,
        preferred_hotel_brands=["Hyatt", "Four Seasons"],
        trip_length_nights=5,          # Shorter trip
        flexibility_days=2,            # Less flexible
        comfort_priority=9,            # Very comfort-sensitive
    ),
    "sam": UserProfile(
        name="Sam Patel",
        preferred_temp_min_f=75,
        preferred_temp_max_f=90,       # Loves the heat
        airfare_budget_soft=800,
        airfare_budget_hard=1200,
        hotel_budget_min=300,
        hotel_budget_max=600,
        preferred_hotel_brands=["Four Seasons", "Ritz-Carlton"],
        trip_length_nights=10,         # Long luxury vacation
        flexibility_days=7,            # Very flexible
        comfort_priority=8,
    ),
}


def get_profile(user_id: str) -> UserProfile | None:
    """Retrieve a user's travel profile by ID.

    Args:
        user_id: The unique identifier for the user (e.g., "alex").

    Returns:
        A UserProfile if found, or None if the user doesn't exist.

    Note:
        This function is IDEMPOTENT — calling it multiple times with the
        same user_id always returns the same result.  This is critical
        for agent reliability: if a tool call is retried, it won't
        produce different results or side effects.
    """
    return _MOCK_PROFILES.get(user_id.lower())


def list_available_users() -> list[str]:
    """List all known user IDs.

    This is a convenience function so the agent (or a tool) can discover
    which users exist.  In production, you'd never expose this — but for
    a demo, it helps the agent pick a valid user.
    """
    return list(_MOCK_PROFILES.keys())
