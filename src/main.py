"""Quant-Ollama: Local-first autonomous financial analyst."""

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Annotated, TypedDict

import ollama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from config import get_settings
from graph.edges import should_continue
from logging_config import LogTimer, get_logger, start_request

logger = get_logger(__name__)
settings = get_settings()


# Ollama Launch Controller
class OllamaManager:
    def __enter__(self):
        self.proc = None
        try:
            ollama.list()  # Check if already running
            logger.info("ollama_already_running", status="connected")
        except Exception as e:
            logger.info("ollama_startup_required", reason=str(e))
            # Start and capture the process ID
            self.proc = subprocess.Popen(
                ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            logger.info("ollama_starting", pid=self.proc.pid)
            time.sleep(3)  # Wait for engine to spin up
            logger.info("ollama_started", pid=self.proc.pid)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Only kill it if WE started it
        if self.proc:
            logger.info("ollama_shutdown_initiated", pid=self.proc.pid)
            self.proc.terminate()
            self.proc.wait()
            logger.info("ollama_shutdown_complete", pid=self.proc.pid)


class AgentState(TypedDict):
    """State for the financial analyst agent."""

    messages: Annotated[list, add_messages]


def get_server_path() -> str:
    """
    Get absolute path to the MCP finance server.

    Uses settings.mcp_server_path if configured, otherwise auto-detects.
    """
    return settings.mcp_server_path


async def create_agent():
    """Create and return the configured agent graph."""
    logger.info("agent_creation_started", environment=settings.environment)

    # Initialize Ollama model with settings
    ollama_config = settings.get_ollama_config()
    model = ChatOllama(**ollama_config)
    logger.info(
        "llm_initialized",
        model=settings.ollama_model,
        host=settings.ollama_host,
        temperature=settings.ollama_temperature,
    )

    # Use absolute path for MCP server to work from any directory
    server_path = get_server_path()
    logger.info("mcp_server_path_resolved", path=server_path)

    client = MultiServerMCPClient(
        {
            "finance": {
                "command": "python",
                "args": [server_path],
                "transport": settings.mcp_transport,
            }
        }
    )
    logger.info("mcp_client_created", transport=settings.mcp_transport)

    tools = await client.get_tools()
    logger.info("mcp_tools_loaded", tool_count=len(tools), tool_names=[t.name for t in tools])

    tool_node = ToolNode(tools)

    def agent_node(state):
        """Agent reasoning node - decides whether to call tools or respond."""
        response = model.bind_tools(tools).invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    graph.add_edge("tools", "agent")

    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)

    logger.info("agent_creation_complete", nodes=["agent", "tools"])
    return app, client


async def main():
    """Main entry point for the CLI."""
    logger.info("application_started")

    # Clear terminal and show banner
    os.system("cls" if os.name == "nt" else "clear")
    banner = """========================================
      Quant-Ollama Financial Analyst
========================================

A local-first, autonomous financial analyst designed to be your 'Sanity Check' layer.
Powered by Llama 3.2, LangGraph, and MCP.

Ask for about a stock ticker to get started!
(e.g., "Tell me about AAPL and recent news associated with it.")

Type 'quit' or 'exit' to end the session.
----------------------------------------"""
    print(f"{banner}\n")

    with OllamaManager():
        # Create the agent
        app, client = await create_agent()
        config = {"configurable": {"thread_id": "main"}}
        logger.info("interactive_session_started", thread_id="main")

        while True:
            try:
                user_input = input("You: ").strip()

                if user_input.lower() in ("quit", "exit"):
                    logger.info("user_requested_exit")
                    break

                if not user_input:
                    continue

                # Start new request with correlation ID
                req_id = start_request()
                logger.info(
                    "user_query_received", query=user_input[:100], query_length=len(user_input)
                )

                with LogTimer(logger, "agent_invocation", query=user_input[:50]):
                    result = await app.ainvoke(
                        {"messages": [("user", user_input)]},
                        config=config,
                    )

                response = result["messages"][-1]
                response_preview = response.content[:200] if response.content else ""
                logger.info(
                    "agent_response_generated",
                    response_length=len(response.content) if response.content else 0,
                    response_preview=response_preview,
                )

                print(f"\nAnalyst: {response.content}\n")

            except KeyboardInterrupt:
                logger.info("keyboard_interrupt_received")
                break
            except Exception as e:
                logger.error(
                    "unexpected_error_in_main_loop",
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )
                print(f"\nError: {e}\n")

        print("Goodbye!")
        logger.info("application_shutdown")


if __name__ == "__main__":
    asyncio.run(main())
