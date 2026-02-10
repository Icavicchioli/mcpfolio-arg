"""LangGraph edge definitions for routing decisions."""

from langchain_core.messages import AIMessage


def should_continue(state) -> str:
    """Determine if the agent should continue with tools or end."""
    last_message = state["messages"][-1]

    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"
