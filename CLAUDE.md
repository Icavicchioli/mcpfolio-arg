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
- `get_market_snapshot(ticker)`: Current price, volume, 52-week volatility, fundamentals
- `get_sentiment_data(ticker)`: Institutional analyst ratings
- `get_news(ticker, count)`: Recent news articles
- `get_trend_data(ticker, period)`: Historical price data for charts
- `get_fund_info(ticker)`: ETF/Mutual Fund holdings and sectors

### LangGraph State Machine (`src/graph/`)
ReAct pattern with persistent state containing:
- `messages`, `retrieved_financials`, `analyst_signals`
- Uses `InMemorySaver` checkpointer (SQLite optional for cross-session)

### Entry Point
`src/main.py` - CLI interface

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start the web dashboard (handles env activation, Ollama, and browser open)
bash scripts/start-dashboard.sh

# Run the CLI (single-ticker analysis, no dashboard)
conda activate mcpfolio
python src/main.py --ticker AAPL

# Run MCP server standalone (for testing)
python src/server/finance.py
```

## Key Constraints

- Cold start under 5 seconds
- Summarize tool outputs to avoid exceeding 128k context window
- Handle yfinance `RateLimitError` with structured retry messages (no crashes)
