# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""LangGraph edge definitions for routing decisions."""

from langchain_core.messages import AIMessage


def should_continue(state) -> str:
    """Determine if the agent should continue with tools or end."""
    last_message = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"


def route_after_parse(state) -> str:
    """Route to the appropriate next node based on parsed query mode.

    Returns:
        "single"  → prefetch node (one ticker detected)
        "compare" → prefetch_compare node (two tickers detected)
        "chat"    → agent node directly (no tickers, conversational query)
    """
    return str(state.get("mode", "chat"))
