# =============================================================================
# agent/__init__.py
# =============================================================================
# This package contains the Google ADK agent configuration.
#
# ARCHITECTURAL ROLE:
#   The agent/ layer is the "brain" that orchestrates everything.  It:
#     1. Receives the user's question ("Is it a good time to go to Maui?")
#     2. Reasons about what information is missing
#     3. Calls tools (via MCP) to gather that information
#     4. Synthesizes the results into a recommendation
#
# WHAT THE AGENT IS NOT:
#   - It is NOT the business logic (that's in core/)
#   - It is NOT the tool implementations (that's in tools/)
#   - It does NOT contain scoring algorithms or data processing
#
# WHAT THE AGENT IS:
#   - A coordinator that decides WHICH tools to call and WHEN
#   - An interpreter that makes sense of tool outputs
#   - A communicator that presents results to the user
#
# THE LLM'S ROLE:
#   The LLM (OpenAI GPT-4o, connected via LiteLlm) is the "reasoning
#   engine" inside the agent.  It reads the system prompt (which defines
#   the agent's personality and process) and the tool descriptions (which
#   tell it what capabilities are available).  Then it autonomously
#   decides how to proceed.
#
#   The key insight: the LLM doesn't need to be "smart" about weather or
#   flights.  It just needs to be smart about WHEN to ask for help (tools)
#   and HOW to interpret the answers.
# =============================================================================
