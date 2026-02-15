# =============================================================================
# core/__init__.py
# =============================================================================
# This package contains ALL business logic for the Maui travel advisor.
#
# CRITICAL ARCHITECTURAL RULE:
#   Nothing in this package imports Google ADK, FastMCP, or any orchestration
#   framework. Every module here is pure Python — you can import it in a
#   bare Python REPL with zero internet access and it will work.
#
# Why?  Because the "brains" of the system (scoring, preferences, data models)
# should be testable, reusable, and framework-agnostic.  The agent framework
# is just the wiring; the core is the engine.
# =============================================================================
