# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MCPFolio is a local-first, autonomous financial analyst that uses MCP (Model Context Protocol) to provide real-time market data to a local LLM. It acts as a "sanity check" layer for investors by performing comprehensive risk assessments through a multi-step reasoning loop.

## Tech Stack

- **Python 3.11+** (required for advanced asyncio support)
- **Ollama** running Llama 3.2 (3B) - optimized for tool-use
- **LangGraph** for state machine orchestration (ReAct pattern)
- **MCP/FastMCP** for LLM-to-tool protocol
- **langchain-mcp-adapters** for LangChain integration
- **yfinance/pandas** for financial data

## Architecture

### MCP Data Server (`src/server/finance.py`)
Uses stdio transport layer. Exposes:
- `get_market_snapshot(ticker)`: Current price, volume, 52-week volatility, fundamentals, `quote_type`
- `get_sentiment_data(ticker)`: Institutional analyst ratings
- `get_news(ticker, count)`: Recent news articles
- `get_trend_data(ticker, period)`: Historical price data for charts
- `get_fund_info(ticker)`: ETF/Mutual Fund holdings and sectors
- `get_earnings_calendar(ticker)`: Next earnings date, EPS estimate, `earnings_imminent` flag (≤7 days)
- `get_macro_context()`: S&P 500 YTD, VIX level + market regime, 10-year Treasury yield; 30-min TTL cache
- `get_sector_peers(ticker)`: Top 5 peer companies in the same sector via `yf.Sector`

### LangGraph State Machine (`src/graph/`)

`AgentState` is defined in `src/graph/state.py` and contains:
- `messages` — conversation history (annotated with `add_messages` reducer)
- `tickers` — ticker symbols extracted from the user query
- `mode` — `"single"` | `"compare"` | `"chat"`
- `retrieved_financials` — keyed by ticker → full snapshot dict
- `analyst_signals` — keyed by ticker → `{buy, hold, sell, ratings}`
- `data_quality` — keyed by ticker → `{tool_name: bool}`
- `prefetch_done` — True after parallel prefetch completes

#### Graph Structure (CLI path)

```
START
  └─► parse_query
        └─► [route_after_parse]
              ├─► "single"  → prefetch → enrich  → agent → [should_continue] → tools ↺ → END
              ├─► "compare" → prefetch_compare    → agent → END
              └─► "chat"    → agent → [should_continue] → tools ↺ → END
```

#### Graph Nodes (`src/graph/nodes.py`)

All nodes are created via factory functions so they capture `model` and `tools_by_name` as closures.

| Node factory | Description |
|---|---|
| `make_parse_query_node()` | Regex-extracts uppercase ticker tokens from the last user message; sets `tickers` and `mode` |
| `make_prefetch_node(tools_by_name)` | Fires 3 parallel MCP calls (snapshot, sentiment, news) for a single ticker; populates state and adds a context `HumanMessage` |
| `make_prefetch_compare_node(tools_by_name)` | Fires 6 parallel MCP calls (3 per ticker) for a two-ticker comparison; adds a side-by-side context `HumanMessage` |
| `make_enrich_node(tools_by_name)` | Data-aware enrichment for single-ticker path. Always fetches macro context. Branches: ETF → fund holdings; stock → earnings calendar + sector peers; ≥2 failed tools → data-caveat warning; earnings ≤7 days → catalyst alert |
| `make_agent_node(model, tools, system_prompt=None)` | LLM reasoning node; injects `system_prompt` (defaults to `SYSTEM_PROMPT`) + `PREFETCH_NOTICE` when prefetch is done at invocation time |

#### Graph Edges (`src/graph/edges.py`)

- `should_continue(state)` — returns `"tools"` if last message has tool calls, else `"end"`
- `route_after_parse(state)` — returns `state["mode"]` (`"single"` | `"compare"` | `"chat"`)

### Persistence Layer (`src/persistence.py`)

`ThesisStore` — encrypted thesis history using Fernet, same salt/password as `SecurePortfolioManager`.

- `data/thesis.enc` — encrypted JSON list of `ThesisRecord` dicts
- `data/portfolio.salt` — shared salt (used by both portfolio and thesis)
- `ThesisRecord` fields: `ticker`, `timestamp` (ISO 8601), `recommendation`, `confidence`, `key_risk`, `fair_value`, `risk_score`, `price`, `ai_analysis`
- One password unlocks both stores; `POST /api/portfolio/unlock` and `POST /api/portfolio/lock` delegate to both
- `thesis.enc` is created on first `save()`; read returns `[]` gracefully when absent
- `GET /api/thesis` — last 200 records across tickers, newest-first (401 if locked)
- `GET /api/thesis/{ticker}` — last 50 records for one ticker (401 if locked)

### Dashboard / Web Path (`src/web/main.py`)

FastAPI app. Key flows:
- **`POST /api/analyze`** — calls `run_analysis_task`, which fetches market snapshot, sentiment, and news **in parallel** via `asyncio.gather`, then calls the LLM directly (no LangGraph); result is appended to in-memory history and persisted to `ThesisStore` when unlocked.
- **`POST /api/compare`** — fetches 6 MCP tools in parallel (3 per ticker), formats a side-by-side context with `format_comparison_context`, calls LLM with `COMPARISON_SYSTEM_PROMPT`, returns `ComparisonResponse` with `verdict`.
- **`/ws/advisor`** — WebSocket endpoint for the Advisor chat tab; uses LangGraph's `astream_events(version="v2")` to stream LLM tokens and tool events in real-time; manages multi-turn memory via `MemorySaver` with persistent `thread_id`; buffers tokens while tools are active to prevent hallucination before data arrives; injects portfolio context when unlocked.

### Shared Prompts & Formatters (`src/prompts.py`)

- `SYSTEM_PROMPT` — long-term investment analyst instruction set
- `COMPARISON_SYSTEM_PROMPT` — side-by-side comparison instruction set with `COMPARISON:` output directive
- `PREFETCH_NOTICE` — appended to `SYSTEM_PROMPT` when pre-fetched data is already in context
- `format_single_context(ticker, snapshot, sentiment, news)` — builds structured LLM context string; used by both the CLI prefetch node and `run_analysis_task`
- `format_comparison_context(...)` — builds side-by-side context string; used by both CLI `prefetch_compare` node and `POST /api/compare`

### Advisor Graph (`src/graph/advisor.py`)

The Advisor tab uses the same LangGraph topology as the CLI but with a different system prompt and temperature:

- **`ADVISOR_SYSTEM_PROMPT`** — conversational financial advisor instruction set with pattern-based tool calling rules:
  - NEVER call tools for capability questions ("Do you know...", "Can you...", educational questions)
  - ALWAYS call tools for specific tickers, market conditions, comparisons
  - No structured output requirements (unlike `SYSTEM_PROMPT` which requires `RECOMMENDATION:`, `CONFIDENCE:`, etc.)
  - Temperature 0.6 with strict "CRITICAL RULES - NEVER VIOLATE" accuracy constraints
- **`build_advisor_graph(model, tools, tools_by_name)`** — factory function that returns a compiled LangGraph with `MemorySaver` checkpointer; reuses the same nodes as the CLI graph but passes `ADVISOR_SYSTEM_PROMPT` to `make_agent_node`

The Advisor graph is lazy-initialized in `SessionManager` on first WebSocket connection and persists for the session. The `thread_id` is reset when the user clicks "Clear conversation".

### Entry Point
`src/main.py` - CLI interface

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start the web dashboard (handles env activation, Ollama, and browser open)
bash scripts/start-dashboard.sh

# Run the CLI (interactive — supports single, compare, and chat modes)
conda activate mcpfolio
python src/main.py

# Run MCP server standalone (for testing)
python src/server/finance.py
```

## Key Constraints

- Cold start under 5 seconds
- Summarize tool outputs to avoid exceeding 128k context window
- Handle yfinance `RateLimitError` with structured retry messages (no crashes)
