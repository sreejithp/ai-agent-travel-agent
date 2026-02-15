# =============================================================================
# main.py  —  Entry Point for the Maui Travel Advisor Agent
# =============================================================================
#
# HOW TO RUN:
#   uv run python main.py
#
# WHAT HAPPENS:
#   1. Creates the Google ADK agent with OpenAI GPT-4o (agent/maui_agent.py)
#   2. Sets up an interactive session
#   3. Sends the user's query to the agent
#   4. Streams the agent's response (including tool calls and reasoning)
#   5. Displays the final recommendation
#
# THE AGENT LOOP:
#   When the agent receives "Is it a good time to go to Maui?", it will
#   autonomously:
#     a) Recognize the question is underspecified (Stage 1)
#     b) Call get_user_profile (Stage 2)
#     c) Call get_weather_forecast (Stage 3)
#     d) Call search_and_analyze_flights (Stage 4)
#     e) Call search_and_evaluate_hotels (Stage 5)
#     f) Call synthesize_travel_recommendation (Stage 6)
#     g) Present the final recommendation
#
#   You'll see each stage happening in real-time in the console output.
#
# GOOGLE ADK CONCEPTS USED:
#   - Runner: Manages the agent's execution lifecycle
#   - SessionService: Tracks conversation state across turns
#   - Content/Part: ADK's message format (like ChatGPT's messages)
#   - Event stream: Real-time updates as the agent thinks and acts
#
# LLM USED:
#   OpenAI GPT-4o (via LiteLlm adapter inside Google ADK).
#   ADK handles orchestration; GPT-4o handles reasoning.
# =============================================================================

import asyncio

from dotenv import load_dotenv

# Load environment variables from .env file (OPENROUTER_API_KEY, etc.)
# This must happen BEFORE creating the agent, because LiteLlm reads
# OPENROUTER_API_KEY from the environment when it initializes.
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.maui_agent import create_agent


async def run_agent():
    """Run the Maui travel advisor agent interactively.

    This function demonstrates the full agent lifecycle:
      1. SETUP: Create agent, runner, and session
      2. INPUT: Provide the user's question
      3. EXECUTION: The agent reasons and calls tools autonomously
      4. OUTPUT: Stream and display the results
    """

    # =========================================================================
    # Step 1: Create the agent
    # =========================================================================
    # This sets up the LLM (OpenAI GPT-4o), system prompt, and MCP tool
    # connections.  After this call, the agent is ready to receive queries.
    print("=" * 70)
    print("  MAUI TRAVEL ADVISOR AGENT")
    print("  Powered by Google ADK + OpenAI GPT-4o + FastMCP")
    print("=" * 70)
    print("\n🔧 Initializing agent...")
    agent = create_agent()

    # =========================================================================
    # Step 2: Create a Runner and Session
    # =========================================================================
    # Runner: Manages the agent's execution (sending messages, processing
    #         responses, handling tool calls, managing state).
    #
    # SessionService: Stores conversation history.  InMemorySessionService
    #                 keeps everything in RAM (good for demos, not for prod).
    #
    # Session: A single conversation thread.  In a web app, each user
    #          would have their own session.
    # =========================================================================
    session_service = InMemorySessionService()

    runner = Runner(
        agent=agent,                   # The agent to run
        app_name="maui_advisor",       # Application identifier
        session_service=session_service,  # Where to store conversation history
    )

    # Create a new session for this conversation
    session = await session_service.create_session(
        app_name="maui_advisor",
        user_id="demo_user",           # Identifies the human user
    )

    print("✅ Agent initialized and ready!\n")

    # =========================================================================
    # Step 3: Interactive loop
    # =========================================================================
    # The user types a question, and we send it to the agent.
    # The agent processes it asynchronously, calling tools as needed.
    # =========================================================================
    print("💬 Ask the agent about traveling to Maui!")
    print("   (Type 'quit' to exit)\n")
    print("-" * 70)

    while True:
        # Get user input
        try:
            user_input = input("\n🧑 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n👋 Goodbye!")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("\n👋 Goodbye!")
            break

        if not user_input:
            continue

        # =====================================================================
        # Step 4: Send the query to the agent
        # =====================================================================
        # Content: ADK's message format.  A Content object has:
        #   - role: "user" (from the human) or "model" (from the agent)
        #   - parts: List of Part objects (text, images, tool calls, etc.)
        #
        # We create a user message and send it to the runner.
        # The runner returns an async generator of Events — each event
        # is a piece of the agent's response (text, tool call, etc.).
        # =====================================================================
        user_message = types.Content(
            role="user",
            parts=[types.Part(text=user_input)],
        )

        print("\n🤖 Agent is thinking...\n")
        print("-" * 70)

        # =====================================================================
        # Step 5: Stream the agent's response
        # =====================================================================
        # The agent produces Events asynchronously:
        #   - Some events are text (the agent explaining its reasoning)
        #   - Some events are tool calls (the agent requesting data)
        #   - Some events are tool results (data coming back)
        #
        # We iterate over all events and display the final text responses.
        # In a production system, you'd also log tool calls for debugging.
        # =====================================================================
        final_response = ""

        async for event in runner.run_async(
            user_id="demo_user",
            session_id=session.id,
            new_message=user_message,
        ):
            # Each event can contain the agent's response content.
            # We look for text parts in the agent's final response.
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        # This is a text response from the agent
                        final_response = part.text

                    if hasattr(part, "function_call") and part.function_call:
                        # This is a tool call — the agent is requesting data
                        tool_name = part.function_call.name
                        print(f"  🔧 Calling tool: {tool_name}")

        # Display the final response
        print("-" * 70)
        if final_response:
            print(f"\n🤖 Agent:\n\n{final_response}")
        else:
            print("\n⚠️  No response generated. The agent may have encountered an error.")

        print("\n" + "=" * 70)


# =============================================================================
# Script entry point
# =============================================================================
# asyncio.run() starts the async event loop and runs our agent function.
# This is standard Python async boilerplate.
# =============================================================================
if __name__ == "__main__":
    asyncio.run(run_agent())
