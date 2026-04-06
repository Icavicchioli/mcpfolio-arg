# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""AgentState definition for the MCPFolio LangGraph agent."""

from typing import Annotated, NotRequired, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the financial analyst agent."""

    messages: Annotated[list, add_messages]
    tickers: NotRequired[list[str]]  # extracted from user query
    mode: NotRequired[str]  # "single" | "compare" | "chat"
    retrieved_financials: NotRequired[dict]  # keyed by ticker → full snapshot dict
    analyst_signals: NotRequired[dict]  # keyed by ticker → {buy, hold, sell, ratings}
    data_quality: NotRequired[dict]  # keyed by ticker → {tool_name: bool}
    prefetch_done: NotRequired[bool]
