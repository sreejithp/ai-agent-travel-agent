# =============================================================================
# agent/maui_agent.py  —  Google ADK Agent Configuration (with OpenAI LLM)
# =============================================================================
#
# WHAT THIS FILE DOES:
#   Configures and creates the Google ADK agent — the coordinator that
#   receives user queries, reasons about them, calls MCP tools, and
#   produces recommendations.
#
# KEY ARCHITECTURE DECISION — ADK + OpenAI:
#   We use Google ADK as the AGENT FRAMEWORK (orchestration, tool calling,
#   session management) but OpenAI GPT-4o as the LLM (reasoning engine).
#
#   Why is this possible?  Google ADK supports non-Gemini models through
#   its LiteLlm integration.  LiteLlm is a universal LLM proxy that lets
#   you call OpenAI, Anthropic, Cohere, etc. with a unified interface.
#
#   Think of it this way:
#     - ADK = the car (steering, brakes, navigation)
#     - LLM = the engine (OpenAI GPT-4o instead of Gemini)
#     - MCP = the fuel lines (connecting tools to the engine)
#
#   You can swap engines without redesigning the car.
#
# HOW IT WORKS (simplified):
#
#   ┌──────────────────────────────────────────────────────────────────┐
#   │                       Google ADK Agent                          │
#   │                                                                  │
#   │  ┌─────────────┐    ┌──────────────┐    ┌───────────────────┐  │
#   │  │  System      │    │  LLM         │    │  Tool             │  │
#   │  │  Prompt      │───▶│  (GPT-4o)   │───▶│  Connections      │  │
#   │  │  (persona)   │    │  via LiteLlm │    │  (MCP servers)    │  │
#   │  └─────────────┘    └──────────────┘    └───────────────────┘  │
#   │                            │                     │              │
#   │                            │                     │              │
#   │                    reasons about          calls tools via       │
#   │                    the task               MCP protocol          │
#   └──────────────────────────────────────────────────────────────────┘
#                                                      │
#                                                      ▼
#                                          ┌─────────────────────┐
#                                          │  FastMCP Server     │
#                                          │  (tools/mcp_server) │
#                                          │                     │
#                                          │  • get_user_profile │
#                                          │  • get_weather      │
#                                          │  • search_flights   │
#                                          │  • search_hotels    │
#                                          │  • synthesize       │
#                                          └─────────────────────┘
#                                                      │
#                                                      ▼
#                                          ┌─────────────────────┐
#                                          │  core/ (pure Python)│
#                                          │  Business logic     │
#                                          └─────────────────────┘
#
# THE AGENT-TOOL RELATIONSHIP:
#   The agent is like a MANAGER who can't do any work directly.
#   It can only:
#     1. Think about what needs to be done (LLM reasoning)
#     2. Ask specialists (tools) to gather information
#     3. Interpret what the specialists report back
#     4. Present a final answer to the user
#
#   This is by design!  The agent's value is in its JUDGMENT
#   (what to ask, how to interpret), not in its data access.
#
# MCP CONNECTION:
#   The agent connects to the FastMCP server using "stdio" transport.
#   This means:
#     - ADK starts the MCP server as a subprocess
#     - They communicate via stdin/stdout (like pipes)
#     - The agent discovers available tools automatically
#     - No network calls — everything is local
# =============================================================================

import os
import sys

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters

from agent.prompt import TRAVEL_ADVISOR_PROMPT


def create_agent() -> Agent:
    """Create and configure the Maui travel advisor agent.

    This function:
      1. Sets up the MCP connection to our FastMCP tool server
      2. Configures OpenAI GPT-4o as the reasoning engine (via LiteLlm)
      3. Creates an ADK Agent with the system prompt and tools
      4. Returns the agent ready to handle user queries

    ARCHITECTURE NOTE:
      The agent itself has NO business logic.  It has:
        - A system prompt (from agent/prompt.py) that defines its behavior
        - Tool connections (to tools/mcp_server.py) for external capabilities
        - A model (OpenAI GPT-4o via LiteLlm) for reasoning

      This is the "clean separation" the project demands:
        agent/ → orchestration only
        tools/ → MCP wrappers only
        core/  → actual logic

    Returns:
        A configured Google ADK Agent instance.
    """

    # =========================================================================
    # Step 1: Configure the MCP tool connection
    # =========================================================================
    # StdioServerParameters tells ADK HOW to start and communicate with
    # our FastMCP server.
    #
    # "command": "uv" — we use uv to run the subprocess
    # "args": ["run", "python", "tools/mcp_server.py"]
    #
    # WHY "uv run" INSTEAD OF BARE "python"?
    #   When ADK spawns the MCP server as a subprocess, that subprocess
    #   needs access to the same virtual environment (fastmcp, core/, etc.).
    #   Using "uv run" ensures the subprocess:
    #     a) Automatically uses the project's .venv
    #     b) Has all dependencies available (fastmcp, etc.)
    #     c) Doesn't require manual venv activation
    #   Without "uv run", the subprocess might use the system Python,
    #   which won't have fastmcp installed — and the tools would fail.
    #
    # ADK will:
    #   a) Start this as a subprocess via uv
    #   b) Send tool-call requests via stdin
    #   c) Read tool results from stdout
    #   d) Make all discovered tools available to the LLM
    # =========================================================================

    # Find the absolute path to the MCP server script
    # This ensures it works regardless of where the script is run from
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mcp_server_path = os.path.join(project_root, "tools", "mcp_server.py")

    mcp_tools = MCPToolset(
        connection_params=StdioServerParameters(
            command="uv",                          # Use uv to manage the subprocess
            args=["run", "python", mcp_server_path],  # uv run ensures correct .venv
        ),
    )

    # =========================================================================
    # Step 2: Create the ADK Agent with OpenRouter model
    # =========================================================================
    # The Agent constructor takes:
    #   - name: Identifier for logging and debugging
    #   - model: Which LLM to use for reasoning
    #   - instruction: The system prompt (defines behavior)
    #   - tools: List of tool sources (MCP servers, functions, etc.)
    #
    # MODEL CHOICE — OpenAI GPT-4o via OpenRouter + LiteLlm:
    #   Google ADK natively supports Gemini models, but it also provides
    #   a LiteLlm wrapper that lets you use ANY LLM provider.
    #
    #   WHAT IS OPENROUTER?
    #     OpenRouter (openrouter.ai) is a unified API gateway that gives
    #     you access to 100+ models from OpenAI, Anthropic, Google, Meta,
    #     Mistral, etc. — all through ONE API key and ONE base URL.
    #
    #     Benefits:
    #       - Single API key for all providers (no separate OpenAI/Anthropic keys)
    #       - Easy model switching (just change the model string)
    #       - Usage tracking and cost management in one dashboard
    #       - Fallback routing (if one provider is down, it can route elsewhere)
    #
    #   HOW THE CHAIN WORKS:
    #     ADK Agent → LiteLlm → OpenRouter API → OpenAI GPT-4o
    #
    #   The "openrouter/openai/gpt-4o" string tells LiteLlm:
    #     - Provider: "openrouter" (route through OpenRouter's gateway)
    #     - Model:    "openai/gpt-4o" (the specific model to call)
    #
    #   LiteLlm reads OPENROUTER_API_KEY from the environment automatically.
    #
    #   OTHER MODELS YOU COULD USE (just change the string below):
    #     - "openrouter/openai/gpt-4o-mini"           → Cheaper, faster
    #     - "openrouter/anthropic/claude-3.5-sonnet"   → Anthropic's Claude
    #     - "openrouter/google/gemini-2.0-flash-001"   → Google Gemini
    #     - "openrouter/meta-llama/llama-3-70b"        → Open-source Meta model
    #     - "openrouter/mistralai/mistral-large"       → Mistral's flagship
    #
    #   To switch models, just change the string below.  Nothing else changes.
    #   That's the power of the ADK + LiteLlm + OpenRouter architecture.
    # =========================================================================
    agent = Agent(
        name="maui_travel_advisor",                            # Used in logs and traces
        model=LiteLlm(model="openrouter/openai/gpt-4o"),      # GPT-4o via OpenRouter
        instruction=TRAVEL_ADVISOR_PROMPT,                     # System prompt from prompt.py
        tools=[mcp_tools],                                     # Our FastMCP tool server
    )

    return agent
