"""Unit tests for LangGraph node factory functions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from langchain_core.messages import HumanMessage

from graph.nodes import _parse_mcp_result, make_parse_query_node
from graph.state import AgentState

# --- AgentState ---


def test_agent_state_fields():
    """AgentState TypedDict has the expected keys."""
    annotations = AgentState.__annotations__
    assert "messages" in annotations
    assert "tickers" in annotations
    assert "mode" in annotations
    assert "retrieved_financials" in annotations
    assert "analyst_signals" in annotations
    assert "data_quality" in annotations
    assert "prefetch_done" in annotations


# --- _parse_mcp_result ---


def test_parse_mcp_result_text_content():
    import json

    payload = {"ticker": "AAPL", "current_price": 195.0}
    result = [{"type": "text", "text": json.dumps(payload)}]
    parsed = _parse_mcp_result(result)
    assert parsed["ticker"] == "AAPL"
    assert parsed["current_price"] == 195.0


def test_parse_mcp_result_dict_passthrough():
    payload = {"ticker": "MSFT", "error": "rate_limit"}
    parsed = _parse_mcp_result(payload)
    assert parsed == payload


def test_parse_mcp_result_unexpected_format():
    parsed = _parse_mcp_result("unexpected string")
    assert "error" in parsed


def test_parse_mcp_result_invalid_json():
    result = [{"type": "text", "text": "not valid json {{{{"}]
    parsed = _parse_mcp_result(result)
    assert "error" in parsed


# --- make_parse_query_node ---


def _run_parse(text: str) -> dict:
    node = make_parse_query_node()
    state = {"messages": [HumanMessage(content=text)]}
    return node(state)


def test_parse_single_ticker():
    result = _run_parse("Analyze AAPL please")
    assert result["tickers"] == ["AAPL"]
    assert result["mode"] == "single"


def test_parse_two_tickers_compare():
    result = _run_parse("Compare AAPL vs MSFT")
    assert "AAPL" in result["tickers"]
    assert "MSFT" in result["tickers"]
    assert result["mode"] == "compare"


def test_parse_no_tickers_chat():
    result = _run_parse("What is the P/E ratio?")
    assert result["tickers"] == []
    assert result["mode"] == "chat"


def test_parse_blocklist_words_filtered():
    # BUY, SELL, HOLD, ETF are in the blocklist
    result = _run_parse("Should I buy or sell?")
    assert result["tickers"] == []
    assert result["mode"] == "chat"


def test_parse_takes_first_two_tickers():
    result = _run_parse("Compare AAPL MSFT NVDA GOOGL")
    assert len(result["tickers"]) == 2
    assert result["mode"] == "compare"


def test_parse_no_human_message():
    from langchain_core.messages import AIMessage

    node = make_parse_query_node()
    state = {"messages": [AIMessage(content="some AI response")]}
    result = node(state)
    assert result["tickers"] == []
    assert result["mode"] == "chat"


def test_parse_ticker_case_insensitive_input():
    # Input must already be uppercase for regex to match; lowercase letters aren't captured
    result = _run_parse("analyze aapl")
    assert result["tickers"] == []
    assert result["mode"] == "chat"


def test_parse_mixed_case_with_uppercase_ticker():
    result = _run_parse("What do you think of NVDA today?")
    assert "NVDA" in result["tickers"]
    assert result["mode"] == "single"
