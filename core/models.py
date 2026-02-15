# =============================================================================
# core/models.py  —  Data Models (the "nouns" of the system)
# =============================================================================
#
# These dataclasses define the *shape* of every piece of information that flows
# through the system.  They carry no behavior — they're just structured bags of
# data with built-in validation via type hints.
#
# WHY DATACLASSES?
#   - They auto-generate __init__, __repr__, and __eq__ for free.
#   - They serve as living documentation: reading these classes tells you
#     exactly what data the system cares about.
#   - They make tool contracts crystal-clear: a tool returns a WeatherForecast,
#     not "some JSON blob."
#
# DESIGN PRINCIPLE — "No Phantom Fields":
#   If a field exists in a model, the agent *will* reason about it.
#   If the agent doesn't need a field, it shouldn't be in the model.
#   This keeps tool outputs lean (Context Budget Discipline).
# =============================================================================

from dataclasses import dataclass, field
from typing import Optional


# -----------------------------------------------------------------------------
# UserProfile — everything the agent needs to know about the traveler
# -----------------------------------------------------------------------------
# This is the FIRST thing the agent retrieves (Stage 2).  Without it, the
# agent cannot judge whether weather is "good," flights are "affordable,"
# or hotels are "acceptable."  It's the lens through which all data is
# interpreted.
# -----------------------------------------------------------------------------
@dataclass
class UserProfile:
    """A traveler's preferences and constraints.

    Every field here directly influences a downstream decision:
      - temp range  →  weather scoring
      - budgets     →  flight/hotel filtering
      - brand pref  →  hotel ranking
      - trip length →  date window calculations
    """

    name: str                          # Human-readable identifier

    # --- Weather preferences ---
    preferred_temp_min_f: int          # Lowest comfortable temp (Fahrenheit)
    preferred_temp_max_f: int          # Highest comfortable temp (Fahrenheit)
    # Example: someone who likes 72–85°F will score a 90°F day poorly.

    # --- Budget constraints ---
    # "Soft ceiling" = the price they'd *like* to stay under.
    # "Hard ceiling" = the absolute max they'd pay (deal-breaker above this).
    # This two-tier model lets the agent say "it's over your ideal budget
    # but still within your hard limit" — a nuanced, real-world distinction.
    airfare_budget_soft: int           # Ideal max airfare (USD)
    airfare_budget_hard: int           # Absolute max airfare (USD)
    hotel_budget_min: int              # Min acceptable nightly rate (too cheap = sketchy)
    hotel_budget_max: int              # Max acceptable nightly rate

    # --- Lodging preferences ---
    preferred_hotel_brands: list[str] = field(default_factory=list)
    # e.g., ["Marriott", "Hilton"] — loyalty programs matter to real travelers.

    # --- Trip parameters ---
    trip_length_nights: int = 7        # Default: one-week vacation
    flexibility_days: int = 3          # How many days they can shift travel dates
    # Flexibility lets the agent search a wider window and find better deals.

    # --- Comfort & safety ---
    # Scale 1-10: 1 = "I'll camp in a hurricane", 10 = "cancel if any rain"
    comfort_priority: int = 7


# -----------------------------------------------------------------------------
# DayForecast — a single day's weather summary
# -----------------------------------------------------------------------------
# The weather tool produces a list of these.  Note that we DON'T include
# raw data like barometric pressure or UV index — that would violate
# Context Budget Discipline (the agent doesn't need it for its decisions).
# -----------------------------------------------------------------------------
@dataclass
class DayForecast:
    """Weather data for one day, pre-summarized for agent consumption."""

    date: str                          # ISO format: "2025-07-15"
    high_f: int                        # Daily high temperature (Fahrenheit)
    low_f: int                         # Daily low temperature (Fahrenheit)
    condition: str                     # e.g., "Sunny", "Partly Cloudy", "Rain"
    precipitation_pct: int             # Chance of rain (0–100)
    wind_mph: int                      # Average wind speed
    is_storm_risk: bool = False        # Explicit flag for severe weather
    # WHY is_storm_risk?  The spec says "storm periods must be explicitly
    # flagged."  A boolean makes the agent's job trivial — no guessing.


# -----------------------------------------------------------------------------
# WeatherSummary — the tool's output for weather analysis
# -----------------------------------------------------------------------------
# This is what the weather TOOL returns.  Notice it doesn't return 30 raw
# DayForecasts and say "figure it out."  It returns a *summary* with the
# raw data available for drill-down.  That's Context Budget Discipline.
# -----------------------------------------------------------------------------
@dataclass
class WeatherSummary:
    """Summarized weather analysis for a destination over a date range."""

    destination: str                   # "Maui, HI"
    period: str                        # "2025-07-10 to 2025-08-10"
    avg_high_f: int                    # Average high across the period
    avg_low_f: int                     # Average low across the period
    rainy_days: int                    # Count of days with >40% precip chance
    storm_risk_days: int               # Count of days flagged as storm risk
    best_window: str                   # "2025-07-15 to 2025-07-22" — sweet spot
    worst_window: str                  # Dates to avoid
    summary: str                       # Human-readable 2-3 sentence summary
    daily_forecasts: list[DayForecast] = field(default_factory=list)
    # daily_forecasts is available if the agent wants detail, but the
    # summary fields above are sufficient for most reasoning.


# -----------------------------------------------------------------------------
# FlightOption — a single flight itinerary
# -----------------------------------------------------------------------------
@dataclass
class FlightOption:
    """One bookable flight itinerary."""

    airline: str                       # "Hawaiian Airlines"
    departure_date: str                # "2025-07-15"
    return_date: str                   # "2025-07-22"
    price_usd: int                     # Round-trip price
    departure_time: str                # "06:00 AM" — relevant for red-eye detection
    arrival_time: str                  # "11:30 AM"
    stops: int                         # 0 = direct, 1 = one stop, etc.
    duration_hours: float              # Total travel time
    is_red_eye: bool = False           # Flag for overnight flights
    # WHY is_red_eye?  Some users hate red-eyes; the profile's comfort
    # priority helps the agent decide whether to recommend them.


# -----------------------------------------------------------------------------
# FlightSearchResult — the tool's output for flight search
# -----------------------------------------------------------------------------
@dataclass
class FlightSearchResult:
    """Summarized flight search results with pre-analyzed options."""

    origin: str                        # "SFO"
    destination: str                   # "OGG" (Maui's airport code)
    search_window: str                 # "2025-07-10 to 2025-08-10"
    cheapest_price: int                # Best price found
    average_price: int                 # Market average
    options: list[FlightOption] = field(default_factory=list)
    summary: str = ""                  # "Prices range from $380–$720..."


# -----------------------------------------------------------------------------
# HotelOption — a single hotel listing
# -----------------------------------------------------------------------------
@dataclass
class HotelOption:
    """One bookable hotel option."""

    name: str                          # "Marriott Wailea Beach Resort"
    brand: str                         # "Marriott" — for loyalty matching
    nightly_rate: int                  # USD per night
    total_cost: int                    # nightly_rate × nights (pre-calculated convenience)
    rating: float                      # Guest rating out of 5.0
    location: str                      # "Wailea Beach" — helps with context
    has_storm_discount: bool = False   # Anomalous pricing flag
    # WHY has_storm_discount?  The spec says "anomalous pricing (e.g., storm
    # discounts) must be surfaced."  This flag lets the agent reason about
    # whether a low price is a deal or a red flag.
    discount_reason: Optional[str] = None  # "Storm season discount" if applicable


# -----------------------------------------------------------------------------
# HotelSearchResult — the tool's output for hotel evaluation
# -----------------------------------------------------------------------------
@dataclass
class HotelSearchResult:
    """Summarized hotel search results."""

    destination: str
    check_in: str
    check_out: str
    options: list[HotelOption] = field(default_factory=list)
    summary: str = ""


# -----------------------------------------------------------------------------
# TravelRecommendation — the agent's final output (Stage 6)
# -----------------------------------------------------------------------------
# This is the "deliverable."  It's not just "go on July 15" — it includes
# alternatives, reasoning, and rejection explanations.
# -----------------------------------------------------------------------------
@dataclass
class TravelRecommendation:
    """The agent's final, synthesized recommendation."""

    recommended_window: str            # "July 15–22, 2025"
    confidence: str                    # "High", "Medium", "Low"
    summary: str                       # 3-5 sentence personalized recommendation
    reasoning: str                     # Why this window was chosen

    # Alternatives give the user options (real advisors always do this)
    alternative_windows: list[str] = field(default_factory=list)
    # e.g., ["July 22–29 (slightly warmer, $50 more)", ...]

    # Rejections explain what was considered and discarded (transparency)
    rejected_options: list[str] = field(default_factory=list)
    # e.g., ["Aug 1–8: storm risk too high for your comfort level"]

    weather_summary: str = ""          # Quick weather recap for the rec window
    flight_summary: str = ""           # Quick flight recap
    hotel_summary: str = ""            # Quick hotel recap
