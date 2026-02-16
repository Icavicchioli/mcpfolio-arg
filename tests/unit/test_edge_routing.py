"""Unit tests for graph edge routing logic"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from langchain_core.messages import AIMessage, HumanMessage

from graph.edges import route_after_parse, should_continue


def test_should_continue_with_tool_calls():
    """Test routing when agent wants to call tools"""
    # Create AIMessage with tool_calls
    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "get_market_snapshot", "args": {"ticker": "AAPL"}, "id": "call_1"}],
    )

    state = {"messages": [ai_msg]}

    result = should_continue(state)

    assert result == "tools"


def test_should_continue_without_tool_calls():
    """Test routing when agent is done (no more tool calls)"""
    # AIMessage with no tool calls
    ai_msg = AIMessage(content="Analysis complete")

    state = {"messages": [ai_msg]}

    result = should_continue(state)

    assert result == "end"


def test_should_continue_multiple_messages():
    """Test routing considers last message"""
    human_msg = HumanMessage(content="Tell me about AAPL")
    ai_msg_with_tools = AIMessage(
        content="", tool_calls=[{"name": "get_news", "args": {"ticker": "MSFT"}, "id": "call_2"}]
    )

    state = {"messages": [human_msg, ai_msg_with_tools]}

    result = should_continue(state)

    assert result == "tools"


def test_should_continue_non_ai_message():
    """Test routing with non-AIMessage as last message"""
    human_msg = HumanMessage(content="Tell me about AAPL")

    state = {"messages": [human_msg]}

    result = should_continue(state)

    assert result == "end"


def test_route_after_parse_single():
    """Test routing to single-ticker prefetch node"""
    state = {"mode": "single"}
    assert route_after_parse(state) == "single"


def test_route_after_parse_compare():
    """Test routing to compare prefetch node"""
    state = {"mode": "compare"}
    assert route_after_parse(state) == "compare"


def test_route_after_parse_chat():
    """Test routing to agent directly for chat queries"""
    state = {"mode": "chat"}
    assert route_after_parse(state) == "chat"


def test_route_after_parse_missing_mode():
    """Test routing defaults to chat when mode is absent"""
    state = {}
    assert route_after_parse(state) == "chat"
