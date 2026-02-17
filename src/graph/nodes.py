"""LangGraph node factory functions for the MCPFolio ReAct agent."""

import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from src.prompts import (
    PREFETCH_NOTICE,
    SYSTEM_PROMPT,
    format_comparison_context,
    format_single_context,
)

# Common English words and financial terms to filter from ticker extraction.
# Single-letter entries: A (article), I (pronoun), and common finance shorthands
# like P (P/E), E (earnings/P/E), Q (quarter), R (return), D (dividend),
# S (sell), N (net), W (with), X (ex-date) that appear frequently in text.
_BLOCKLIST = {
    # Single letters — too ambiguous in natural language
    "A",
    "I",
    "P",
    "E",
    "Q",
    "R",
    "D",
    "S",
    "N",
    "W",
    "X",
    # Two-letter common words
    "AT",
    "VS",
    "OR",
    "AN",
    "WE",
    "DO",
    "GO",
    "UP",
    "SO",
    "IF",
    "NO",
    "ON",
    "BY",
    "MY",
    "AM",
    "IS",
    "BE",
    "AS",
    "OF",
    "IN",
    "TO",
    "ME",
    "IT",
    # Three-letter common words & abbreviations
    "AND",
    "BUY",
    "THE",
    "FOR",
    "NOT",
    "BUT",
    "ALL",
    "CAN",
    "GET",
    "USE",
    "NOW",
    "NEW",
    "OLD",
    "BIG",
    "LOW",
    "WHO",
    "HOW",
    "WHY",
    "ITS",
    "HAS",
    "HAD",
    "WAS",
    "ARE",
    # Longer common words
    "SELL",
    "HOLD",
    "WILL",
    "THIS",
    "THAT",
    "WHAT",
    "WITH",
    "FROM",
    "HAVE",
    "THAN",
    "THEN",
    "WHEN",
    "HIGH",
    "TELL",
    "SHOW",
    "GIVE",
    "LOOK",
    "FIND",
    "MAKE",
    "TAKE",
    "KNOW",
    "WANT",
    "NEED",
    "LIKE",
    "JUST",
    "ALSO",
    "WELL",
    "INTO",
    "OVER",
    "SOME",
    "MORE",
    "MOST",
    "EACH",
    "SUCH",
    "SAME",
    "EVEN",
    "BOTH",
    "ONLY",
    "VERY",
    "MUCH",
    "LONG",
    "RATE",
    "STOCK",
    "ETF",
    "FUND",
    "REIT",
    "NEWS",
    "DATA",
    "INFO",
    "RISK",
    "GAIN",
    "LOSS",
    "PRICE",
    "VALUE",
    "ABOUT",
    "WHICH",
    "THEIR",
    "THERE",
    "THESE",
    "THOSE",
    "WOULD",
    "COULD",
    "SHOULD",
    "MIGHT",
    "SHALL",
    "AFTER",
    "FIRST",
    "LAST",
    "YEAR",
    "YEARS",
    "RECENT",
    "LATEST",
    "TODAY",
    "GIVEN",
    "SINCE",
}


def _parse_mcp_result(result) -> dict:
    """Extract and parse JSON from an MCP tool result."""
    try:
        if isinstance(result, list) and len(result) > 0:
            content = result[0]
            if isinstance(content, dict) and content.get("type") == "text":
                return dict(json.loads(content.get("text", "{}")))
        elif isinstance(result, dict):
            return result
        return {"error": "Unexpected tool result format", "raw": str(result)}
    except Exception as e:
        return {"error": f"Failed to parse tool result: {str(e)}", "raw": str(result)}


def make_parse_query_node():
    """
    Return a node that extracts ticker symbols from the user's message.

    Sets `tickers` (list) and `mode` ("single" | "compare" | "chat") in state.
    """

    def parse_query_node(state):
        # Find the last human message
        last_human = next(
            (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
            None,
        )
        if not last_human:
            return {"tickers": [], "mode": "chat"}

        text = (
            last_human.content if isinstance(last_human.content, str) else str(last_human.content)
        )

        # Extract uppercase 1-5 letter tokens, filter blocklist
        tokens = re.findall(r"\b[A-Z]{1,5}\b", text)
        seen = set()
        tickers = []
        for t in tokens:
            if t not in _BLOCKLIST and t not in seen:
                seen.add(t)
                tickers.append(t)

        if len(tickers) == 0:
            mode = "chat"
        elif len(tickers) == 1:
            mode = "single"
        else:
            mode = "compare"
            tickers = tickers[:2]  # use first two

        return {"tickers": tickers, "mode": mode}

    return parse_query_node


def make_prefetch_node(tools_by_name: dict):
    """
    Return an async node that prefetches data for a single ticker in parallel.

    Fires 3 concurrent MCP calls: market_snapshot, sentiment, news.
    Stores results in state and adds a context HumanMessage for the agent.
    """

    async def prefetch_node(state):
        ticker = state.get("tickers", [""])[0]
        if not ticker:
            return {"prefetch_done": False}

        snapshot_tool = tools_by_name.get("get_market_snapshot")
        sentiment_tool = tools_by_name.get("get_sentiment_data")
        news_tool = tools_by_name.get("get_news")

        coros = [
            snapshot_tool.ainvoke({"ticker": ticker}) if snapshot_tool else asyncio.sleep(0),
            sentiment_tool.ainvoke({"ticker": ticker}) if sentiment_tool else asyncio.sleep(0),
            news_tool.ainvoke({"ticker": ticker, "count": 5}) if news_tool else asyncio.sleep(0),
        ]
        raw_snapshot, raw_sentiment, raw_news = await asyncio.gather(*coros, return_exceptions=True)

        snapshot = (
            _parse_mcp_result(raw_snapshot) if not isinstance(raw_snapshot, Exception) else {}
        )
        sentiment_result = (
            _parse_mcp_result(raw_sentiment) if not isinstance(raw_sentiment, Exception) else {}
        )
        news_result = _parse_mcp_result(raw_news) if not isinstance(raw_news, Exception) else {}

        sentiment = [] if sentiment_result.get("error") else sentiment_result.get("ratings", [])
        news = [] if news_result.get("error") else news_result.get("news", [])

        data_quality = {
            ticker: {
                "get_market_snapshot": not bool(snapshot.get("error")),
                "get_sentiment_data": (
                    not isinstance(raw_sentiment, Exception)
                    and not bool(sentiment_result.get("error"))
                ),
                "get_news": (
                    not isinstance(raw_news, Exception) and not bool(news_result.get("error"))
                ),
            }
        }

        retrieved_financials = {ticker: snapshot}
        analyst_signals = {
            ticker: {
                "ratings": sentiment,
                "buy": sum(
                    1
                    for r in sentiment
                    if "BUY" in (r.get("grade") or r.get("action") or "").upper()
                ),
                "sell": sum(
                    1
                    for r in sentiment
                    if "SELL" in (r.get("grade") or r.get("action") or "").upper()
                ),
            }
        }

        context_str = format_single_context(ticker, snapshot, sentiment or None, news or None)
        prefetch_msg = HumanMessage(content=f"[Pre-fetched Market Data]\n{context_str}")

        return {
            "messages": [prefetch_msg],
            "retrieved_financials": retrieved_financials,
            "analyst_signals": analyst_signals,
            "data_quality": data_quality,
            "prefetch_done": True,
        }

    return prefetch_node


def make_prefetch_compare_node(tools_by_name: dict):
    """
    Return an async node that prefetches data for two tickers in parallel.

    Fires 6 concurrent MCP calls (3 per ticker).
    Stores results in state and adds a side-by-side context HumanMessage.
    """

    async def prefetch_compare_node(state):
        tickers = state.get("tickers", [])
        if len(tickers) < 2:
            return {"prefetch_done": False}

        ticker_a, ticker_b = tickers[0], tickers[1]

        snapshot_tool = tools_by_name.get("get_market_snapshot")
        sentiment_tool = tools_by_name.get("get_sentiment_data")
        news_tool = tools_by_name.get("get_news")

        coros = [
            snapshot_tool.ainvoke({"ticker": ticker_a}) if snapshot_tool else asyncio.sleep(0),
            snapshot_tool.ainvoke({"ticker": ticker_b}) if snapshot_tool else asyncio.sleep(0),
            sentiment_tool.ainvoke({"ticker": ticker_a}) if sentiment_tool else asyncio.sleep(0),
            sentiment_tool.ainvoke({"ticker": ticker_b}) if sentiment_tool else asyncio.sleep(0),
            news_tool.ainvoke({"ticker": ticker_a, "count": 5}) if news_tool else asyncio.sleep(0),
            news_tool.ainvoke({"ticker": ticker_b, "count": 5}) if news_tool else asyncio.sleep(0),
        ]
        results = await asyncio.gather(*coros, return_exceptions=True)
        raw_snap_a, raw_snap_b, raw_sent_a, raw_sent_b, raw_news_a, raw_news_b = results

        def _safe_parse(raw) -> dict:
            return _parse_mcp_result(raw) if not isinstance(raw, Exception) else {}

        def _safe_ratings(raw) -> list:
            r = _safe_parse(raw)
            return [] if r.get("error") else r.get("ratings", [])

        def _safe_news(raw) -> list:
            r = _safe_parse(raw)
            return [] if r.get("error") else r.get("news", [])

        snap_a = _safe_parse(raw_snap_a)
        snap_b = _safe_parse(raw_snap_b)
        sent_a = _safe_ratings(raw_sent_a)
        sent_b = _safe_ratings(raw_sent_b)
        news_a = _safe_news(raw_news_a)
        news_b = _safe_news(raw_news_b)

        data_quality = {
            ticker_a: {
                "get_market_snapshot": not bool(snap_a.get("error")),
                "get_sentiment_data": not isinstance(raw_sent_a, Exception)
                and not bool(_safe_parse(raw_sent_a).get("error")),
                "get_news": not isinstance(raw_news_a, Exception)
                and not bool(_safe_parse(raw_news_a).get("error")),
            },
            ticker_b: {
                "get_market_snapshot": not bool(snap_b.get("error")),
                "get_sentiment_data": not isinstance(raw_sent_b, Exception)
                and not bool(_safe_parse(raw_sent_b).get("error")),
                "get_news": not isinstance(raw_news_b, Exception)
                and not bool(_safe_parse(raw_news_b).get("error")),
            },
        }

        retrieved_financials = {ticker_a: snap_a, ticker_b: snap_b}
        analyst_signals = {
            ticker_a: {
                "ratings": sent_a,
                "buy": sum(
                    1 for r in sent_a if "BUY" in (r.get("grade") or r.get("action") or "").upper()
                ),
                "sell": sum(
                    1 for r in sent_a if "SELL" in (r.get("grade") or r.get("action") or "").upper()
                ),
            },
            ticker_b: {
                "ratings": sent_b,
                "buy": sum(
                    1 for r in sent_b if "BUY" in (r.get("grade") or r.get("action") or "").upper()
                ),
                "sell": sum(
                    1 for r in sent_b if "SELL" in (r.get("grade") or r.get("action") or "").upper()
                ),
            },
        }

        context_str = format_comparison_context(
            ticker_a,
            snap_a,
            sent_a or None,
            news_a or None,
            ticker_b,
            snap_b,
            sent_b or None,
            news_b or None,
        )
        prefetch_msg = HumanMessage(
            content=f"[Pre-fetched Comparison Data: {ticker_a} vs {ticker_b}]\n{context_str}"
        )

        return {
            "messages": [prefetch_msg],
            "retrieved_financials": retrieved_financials,
            "analyst_signals": analyst_signals,
            "data_quality": data_quality,
            "prefetch_done": True,
        }

    return prefetch_compare_node


def make_enrich_node(tools_by_name: dict):
    """
    Return an async node that enriches single-ticker context after prefetch.

    Always fetches macro context (S&P 500 YTD, VIX, 10-yr yield).
    Branches on asset type and data quality:
      - ETF/MutualFund  → fetches fund holdings via get_fund_info
      - Stock           → fetches earnings calendar + sector peers
      - Degraded (≥2 failed tools) → injects an explicit data-caveat warning
      - Earnings imminent (≤7 days) → prepends a catalyst alert
    """

    async def enrich_node(state):
        ticker = state.get("tickers", [""])[0]
        if not ticker:
            return {}

        financials = state.get("retrieved_financials", {}).get(ticker, {})
        data_quality = state.get("data_quality", {}).get(ticker, {})
        is_etf = str(financials.get("quote_type") or "").upper() in ("ETF", "MUTUALFUND")

        macro_tool = tools_by_name.get("get_macro_context")
        earnings_tool = tools_by_name.get("get_earnings_calendar")
        sector_tool = tools_by_name.get("get_sector_peers")
        fund_tool = tools_by_name.get("get_fund_info")

        coros = [
            macro_tool.ainvoke({}) if macro_tool else asyncio.sleep(0),
            (fund_tool.ainvoke({"ticker": ticker}) if (fund_tool and is_etf) else asyncio.sleep(0)),
            (
                earnings_tool.ainvoke({"ticker": ticker})
                if (earnings_tool and not is_etf)
                else asyncio.sleep(0)
            ),
            (
                sector_tool.ainvoke({"ticker": ticker})
                if (sector_tool and not is_etf)
                else asyncio.sleep(0)
            ),
        ]
        raw_macro, raw_fund, raw_earnings, raw_peers = await asyncio.gather(
            *coros, return_exceptions=True
        )

        messages_to_add = []

        # Degraded data caveat — surface before any enrichment context
        failed_tools = [k for k, v in data_quality.items() if not v]
        if len(failed_tools) >= 2:
            messages_to_add.append(
                HumanMessage(
                    content=(
                        f"DATA CAVEAT: {len(failed_tools)} data sources failed "
                        f"({', '.join(failed_tools)}) for {ticker}. "
                        "Flag any data gaps explicitly in your analysis."
                    )
                )
            )

        # Macro context (always)
        macro = _parse_mcp_result(raw_macro) if not isinstance(raw_macro, Exception) else {}
        if macro and not macro.get("error"):
            lines = [
                "MACRO CONTEXT:",
                f"  S&P 500 YTD: {macro.get('sp500_ytd_pct', 'N/A')}%",
                f"  VIX: {macro.get('vix_level', 'N/A')} — {macro.get('market_regime', 'N/A')}",
                f"  10-Year Treasury: {macro.get('treasury_10y_yield', 'N/A')}%",
            ]
            messages_to_add.append(HumanMessage(content="\n".join(lines)))

        if is_etf:
            # ETF: inject fund holdings instead of earnings/peers
            fund = _parse_mcp_result(raw_fund) if not isinstance(raw_fund, Exception) else {}
            if fund and not fund.get("error"):
                holdings = (fund.get("top_holdings") or [])[:5]
                sectors = fund.get("sector_weightings") or {}
                lines = [f"FUND HOLDINGS ({ticker}):"]
                for h in holdings:
                    sym = h.get("symbol") or h.get("holdingName", "?")
                    pct = h.get("holdingPercent")
                    lines.append(f"  {sym}: {pct:.1%}" if isinstance(pct, float) else f"  {sym}")
                if sectors:
                    top_s = sorted(sectors.items(), key=lambda x: x[1], reverse=True)[:3]
                    lines.append("Top sectors: " + ", ".join(f"{s} ({v:.0%})" for s, v in top_s))
                messages_to_add.append(HumanMessage(content="\n".join(lines)))
        else:
            # Earnings calendar
            earnings = (
                _parse_mcp_result(raw_earnings) if not isinstance(raw_earnings, Exception) else {}
            )
            if earnings and not earnings.get("error"):
                days = earnings.get("days_until_earnings")
                eps = earnings.get("eps_estimate")
                date_str = earnings.get("earnings_date", "N/A")
                if days is not None and 0 <= days <= 7:
                    messages_to_add.append(
                        HumanMessage(
                            content=(
                                f"EARNINGS CATALYST ALERT: {ticker} reports in {days} day(s) "
                                f"({date_str}). "
                                + (f"EPS estimate: ${eps:.2f}. " if eps else "")
                                + "Weight short-term risk heavily in your analysis."
                            )
                        )
                    )
                elif date_str != "N/A":
                    messages_to_add.append(
                        HumanMessage(
                            content=f"NEXT EARNINGS: {ticker} — {date_str}"
                            + (f" (EPS est. ${eps:.2f})" if eps else "")
                        )
                    )

            # Sector peers
            peers_result = (
                _parse_mcp_result(raw_peers) if not isinstance(raw_peers, Exception) else {}
            )
            peers = peers_result.get("peers", [])
            sector = peers_result.get("sector")
            if peers and sector:
                lines = [f"SECTOR PEERS ({sector}):"]
                for p in peers[:5]:
                    lines.append(f"  {p['ticker']}: {p.get('name', '')}")
                messages_to_add.append(HumanMessage(content="\n".join(lines)))

        return {"messages": messages_to_add} if messages_to_add else {}

    return enrich_node


def make_agent_node(model, tools: list, system_prompt: str | None = None):
    """
    Return an agent reasoning node that decides whether to call tools or respond.

    Injects SYSTEM_PROMPT (+ PREFETCH_NOTICE when data is pre-loaded) at invocation
    time without persisting it in state.

    Args:
        model: LLM instance
        tools: List of available tools
        system_prompt: Optional custom system prompt (defaults to SYSTEM_PROMPT)
    """
    _prompt = system_prompt or SYSTEM_PROMPT

    def agent_node(state):
        system_content = _prompt
        if state.get("prefetch_done"):
            system_content = _prompt + "\n\n" + PREFETCH_NOTICE

        messages = [SystemMessage(content=system_content)] + list(state["messages"])
        response = model.bind_tools(tools).invoke(messages)
        return {"messages": [response]}

    return agent_node
