# Maui Travel Advisor Agent

> **"Is it a good time to go to Maui?"**

An AI agent that transforms this deceptively simple question into a personalized, evidence-based travel recommendation.

## What This Project Teaches

This is not a Maui app. It's a lesson in **building agents that think before they answer**.

The key insight: *"good time"* is subjective. The agent's first job is to figure out what "good" means for the specific person asking.

### Core Concepts Demonstrated

1. **Epistemic Awareness** — The agent recognizes what it doesn't know before acting
2. **Tool-Maximalist Architecture** — All data gathering happens through structured MCP tools
3. **Context Budget Discipline** — Tools return summaries, not data dumps
4. **Separation of Concerns** — Business logic is framework-agnostic
5. **Personalized Reasoning** — Every decision is filtered through user preferences

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (entry point)                     │
│                                                                   │
│  Creates the agent, manages the conversation loop, streams output │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    agent/ (orchestration layer)                   │
│                                                                   │
│  maui_agent.py  — Google ADK agent configuration                  │
│  prompt.py      — System prompt (the agent's "personality")       │
│                                                                   │
│  Role: Decides WHAT to do and WHEN (no business logic here)       │
└─────────────────────────────────────────────────────────────────┘
                              │ calls tools via MCP protocol
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    tools/ (MCP tool layer)                        │
│                                                                   │
│  mcp_server.py  — FastMCP server with 5 tools:                    │
│    • get_user_profile              (Stage 2)                      │
│    • get_weather_forecast          (Stage 3)                      │
│    • search_and_analyze_flights    (Stage 4)                      │
│    • search_and_evaluate_hotels    (Stage 5)                      │
│    • synthesize_travel_recommendation (Stage 6)                   │
│                                                                   │
│  Role: Thin wrappers — serializes data, enforces context budget   │
└─────────────────────────────────────────────────────────────────┘
                              │ imports pure functions
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    core/ (business logic layer)                   │
│                                                                   │
│  models.py       — Data models (UserProfile, DayForecast, etc.)   │
│  user_profile.py — Profile storage and retrieval                  │
│  weather.py      — Weather forecast generation and analysis       │
│  flights.py      — Flight search and budget analysis              │
│  hotels.py       — Hotel search, scoring, anomaly detection       │
│  synthesis.py    — Final recommendation synthesis                 │
│                                                                   │
│  Role: ALL logic lives here. Zero framework imports.              │
│  Rule: Can be imported in a bare Python REPL with no internet.    │
└─────────────────────────────────────────────────────────────────┘
```

### Why This Layering Matters

| Layer | Depends On | Does NOT Depend On |
|-------|-----------|-------------------|
| `core/` | Python stdlib only | ADK, MCP, network |
| `tools/` | `core/`, FastMCP | ADK, network |
| `agent/` | ADK, `tools/` (via MCP) | `core/` directly |
| `main.py` | `agent/` | `core/`, `tools/` |

If you can `import core.weather` in a Python REPL with no internet, the architecture is correct.

## Agent Decision Flow (The 6 Stages)

```
User: "Is it a good time to go to Maui?"
                │
                ▼
    ┌───────────────────────┐
    │ Stage 1: REFLECTION   │  "I can't answer yet — 'good' depends on YOU"
    │ (Epistemic awareness) │  Agent recognizes the question is underspecified
    └───────────┬───────────┘
                ▼
    ┌───────────────────────┐
    │ Stage 2: PROFILE      │  → get_user_profile("alex")
    │ (Who is asking?)      │  Retrieves: temps, budgets, brands, comfort
    └───────────┬───────────┘
                ▼
    ┌───────────────────────┐
    │ Stage 3: WEATHER      │  → get_weather_forecast("Maui, HI", ...)
    │ (What's the climate?) │  Returns: best/worst windows, storm warnings
    └───────────┬───────────┘
                ▼
    ┌───────────────────────┐
    │ Stage 4: FLIGHTS      │  → search_and_analyze_flights("SFO", "OGG", ...)
    │ (Can they afford it?) │  Returns: prices vs budget, red-eye warnings
    └───────────┬───────────┘
                ▼
    ┌───────────────────────┐
    │ Stage 5: HOTELS       │  → search_and_evaluate_hotels("Maui, HI", ...)
    │ (Where to stay?)      │  Returns: brand matches, storm discounts flagged
    └───────────┬───────────┘
                ▼
    ┌───────────────────────┐
    │ Stage 6: SYNTHESIS    │  → synthesize_travel_recommendation(...)
    │ (The recommendation)  │  Returns: window, alternatives, rejections
    └───────────────────────┘
```

## Setup & Running

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (blazing-fast Python package manager)
- An OpenRouter API key (for GPT-4o LLM access via [OpenRouter](https://openrouter.ai))

### Install uv (if you don't have it)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Installation

```bash
# Clone and enter the project
cd maui

# Install all dependencies (uv auto-creates .venv for you)
uv sync

# Set up your API key
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
```

That's it. `uv sync` reads `pyproject.toml`, resolves dependencies, creates a
`.venv`, and installs everything. No manual `venv` creation or activation needed.

### Running the Agent

```bash
uv run python main.py
```

`uv run` automatically activates the `.venv` and runs the command inside it.
No need to manually `source .venv/bin/activate`.

### Other Useful uv Commands

```bash
uv run pytest              # Run tests
uv add <package>           # Add a new dependency
uv sync --dev              # Install dev dependencies (pytest, etc.)
uv lock                    # Regenerate the lockfile after pyproject.toml changes
```

Then type: **"Is it a good time to go to Maui?"**

Watch the agent:
1. Reflect on what "good" means
2. Retrieve a user profile
3. Check the weather
4. Search for flights
5. Evaluate hotels
6. Synthesize a personalized recommendation

## Mock Data Design

All data is mocked (no external APIs needed), but the mocks are designed to create **interesting trade-offs**:

### Weather Pattern
- **Days 1-7**: Nice weather (sunny, 82-87°F)
- **Days 8-12**: Storm window (rain, thunderstorms, 15-30mph winds)
- **Days 13-20**: Mixed recovery (some good, some rain)
- **Days 21-30**: Best window (sunny, 83-88°F, light winds)

### User Profiles
| User | Budget | Temp Pref | Comfort | Interesting Trade-off |
|------|--------|-----------|---------|----------------------|
| Alex | Tight ($450 soft) | 72-85°F | Medium (6) | Flexible dates, needs cheap flights |
| Jordan | Moderate ($600) | 68-80°F | Very High (9) | Hates heat AND storms |
| Sam | Generous ($800) | 75-90°F | High (8) | Loves heat, wants luxury |

### Hotels
- Budget options with no brand loyalty match
- Mid-range with Marriott/Hilton (loyalty programs)
- Luxury with Four Seasons/Ritz-Carlton
- **Storm discounts** on premium hotels (30% off — deal or red flag?)

## API Choices & Justification

| Component | Choice | Why |
|-----------|--------|-----|
| Agent Framework | Google ADK | Course requirement; clean agent abstraction |
| Tool Protocol | FastMCP | Course requirement; standard MCP implementation |
| LLM | OpenAI GPT-4o (via OpenRouter + LiteLlm) | Strong reasoning, excellent tool-calling; OpenRouter enables easy model switching |
| Weather API | Mock (core/weather.py) | Deterministic, no API key needed, designed for interesting scenarios |
| Flight API | Mock (core/flights.py) | Realistic pricing patterns without API dependency |
| Hotel API | Mock (core/hotels.py) | Brand loyalty + storm discounts create teaching moments |

## Key Design Decisions

### 1. Combined Search+Analyze Tools
Instead of `search_flights` + `analyze_flights` as two separate tools, we expose `search_and_analyze_flights`. Why? The agent would always call them together, so combining them saves one LLM round-trip (faster and cheaper).

### 2. Two-Tier Budget Model
Soft ceiling (ideal) vs hard ceiling (maximum). This enables nuanced recommendations like "It's over your ideal budget but still within your limit."

### 3. Storm Discount Flagging
Hotels with storm discounts have `has_storm_discount=True`. A naive agent says "great deal!" A smart agent says "the price is low because the weather is bad."

### 4. Sliding Window Weather Analysis
Instead of scoring individual days, we score contiguous blocks matching the trip length. Because you need 7 consecutive good days, not 7 scattered ones.

### 5. Confidence Levels
The recommendation includes High/Medium/Low confidence. This is epistemic honesty — the system tells you how sure it is, not just what it thinks.
