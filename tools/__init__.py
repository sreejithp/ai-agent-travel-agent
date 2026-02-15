# =============================================================================
# tools/__init__.py
# =============================================================================
# This package contains FastMCP tool wrappers.
#
# ARCHITECTURAL ROLE:
#   tools/ is the "translation layer" between the agent framework and the
#   core business logic.  Each file here:
#     1. Imports a pure function from core/
#     2. Wraps it in a FastMCP tool decorator
#     3. Handles serialization (converting dataclasses → dicts for JSON)
#     4. Enforces Context Budget Discipline (summarizing, filtering)
#
# WHAT TOOLS DO NOT DO:
#   - They do NOT contain business logic (that's in core/)
#   - They do NOT make decisions (that's the agent's job)
#   - They do NOT know about Google ADK (they're framework-agnostic)
#
# WHY FASTMCP?
#   FastMCP is a lightweight framework for exposing Python functions as
#   MCP (Model Context Protocol) tools.  MCP is an open standard for
#   connecting AI models to external capabilities.  The agent calls
#   tools via MCP, and FastMCP handles the protocol details.
#
# TOOL CONTRACT QUALITY:
#   Each tool has:
#     - A clear, descriptive name (e.g., "get_user_profile", not "get_data")
#     - A detailed docstring (the LLM reads this to decide WHEN to call it)
#     - Typed parameters (so the LLM knows WHAT to pass)
#     - A documented return format (so the LLM knows what it'll GET back)
#
#   Tool contracts are arguably THE most important part of an agentic
#   system.  A well-named tool with a good docstring will be called
#   correctly; a badly-named one will be misused or ignored.
# =============================================================================
