"""Unit tests for the advisor graph and system prompt."""

from src.graph.advisor import ADVISOR_SYSTEM_PROMPT, build_advisor_graph


def test_advisor_system_prompt_exists():
    """ADVISOR_SYSTEM_PROMPT is non-empty."""
    assert ADVISOR_SYSTEM_PROMPT
    assert len(ADVISOR_SYSTEM_PROMPT) > 100


def test_advisor_system_prompt_is_conversational():
    """ADVISOR_SYSTEM_PROMPT does NOT contain 'RECOMMENDATION:' (confirms it's conversational, not structured-output)."""
    assert "RECOMMENDATION:" not in ADVISOR_SYSTEM_PROMPT
    assert "CONFIDENCE:" not in ADVISOR_SYSTEM_PROMPT
    assert "FAIR_VALUE:" not in ADVISOR_SYSTEM_PROMPT


def test_advisor_system_prompt_mentions_all_tools():
    """ADVISOR_SYSTEM_PROMPT contains all 8 tool names (LLM knows what's available)."""
    tools = [
        "get_market_snapshot",
        "get_sentiment_data",
        "get_news",
        "get_trend_data",
        "get_fund_info",
        "get_earnings_calendar",
        "get_macro_context",
        "get_sector_peers",
    ]
    for tool in tools:
        assert tool in ADVISOR_SYSTEM_PROMPT, f"Tool {tool} not mentioned in ADVISOR_SYSTEM_PROMPT"


def test_build_advisor_graph_returns_compiled_graph():
    """build_advisor_graph returns a compiled graph with the expected nodes."""
    from unittest.mock import MagicMock

    # Mock model and tools
    mock_model = MagicMock()
    mock_tools = []
    mock_tools_by_name = {}

    graph = build_advisor_graph(mock_model, mock_tools, mock_tools_by_name)

    # Verify it's compiled (has get_graph method)
    assert hasattr(graph, "get_graph")

    # Verify expected nodes exist
    graph_dict = graph.get_graph()
    nodes = list(graph_dict.nodes)

    expected_nodes = ["parse_query", "agent", "tools", "prefetch", "enrich", "prefetch_compare"]
    for node in expected_nodes:
        assert node in nodes, f"Node {node} not found in advisor graph"


def test_make_agent_node_uses_custom_system_prompt():
    """make_agent_node with explicit system_prompt kwarg uses that prompt, not SYSTEM_PROMPT."""
    from unittest.mock import MagicMock

    from src.graph.nodes import make_agent_node
    from src.prompts import SYSTEM_PROMPT

    custom_prompt = "This is a custom advisor prompt for testing"

    # Create agent node with custom prompt
    mock_model = MagicMock()
    mock_tools = []
    agent_node = make_agent_node(mock_model, mock_tools, system_prompt=custom_prompt)

    # Create a minimal state
    from langchain_core.messages import HumanMessage

    state = {"messages": [HumanMessage(content="test")], "prefetch_done": False}

    # Call the node
    agent_node(state)

    # Verify the model was called with the custom prompt, not SYSTEM_PROMPT
    call_args = mock_model.bind_tools.return_value.invoke.call_args[0][0]
    system_message = call_args[0]

    assert system_message.content == custom_prompt
    assert system_message.content != SYSTEM_PROMPT
