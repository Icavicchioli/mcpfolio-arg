This expanded specification transforms the "stock analyzer" into a production-ready repository concept: **Quant-Ollama V1**.

By leveraging the **Model Context Protocol (MCP)**, we solve the biggest weakness of local LLMs: their lack of access to real-time, high-fidelity data. In 2026, this modular approach is the gold standard for building agents that are both private and powerful.

---

# Project Overview: Quant-Ollama V1

**Quant-Ollama** is a local-first, autonomous financial analyst. Unlike standard chatbots that rely on training data (which is always out of date for markets), this agent uses a dedicated **MCP Financial Server** to pull live ticker data, analyst ratings, and historical trends.

It is designed to act as a "Sanity Check" layer for investors. Instead of just asking for a price, you ask for a **comprehensive risk assessment**. The agent uses **LangGraph** to perform a multi-step "thinking" loop: fetching the data, analyzing the sentiment, and then synthesizing a recommendation—all on your own hardware.

### Why This is Useful

* **Impulse Prevention:** The agent is programmed to look for bearish analyst ratings even when you ask it why a stock is "going to the moon."
* **Privacy:** Your portfolio interests and watchlists are never uploaded to a cloud provider; all reasoning stays in your local RAM.
* **Extensibility:** Because it uses MCP, you can later plug in tools for your own local CSV spreadsheets or private SQL databases without changing the agent's core code.

---

# Technical Requirements Specification

## 1. Environment & Infrastructure

To ensure the agent remains responsive during complex tool-calling loops, the following environment is required:

* **Host Environment:** Python 3.11+ (Required for advanced `asyncio` support).
* **Model Provider:** [Ollama](https://ollama.com/) running **Llama 3.2 (3B)**.
* *Note:* The 3B model is specifically optimized for tool-use and follows JSON instructions better than the 1B variant.


* **Memory Management:** Minimum **16GB RAM** (Unified memory for Mac or VRAM for PC).

## 2. Dependency Stack

Your `pyproject.toml` or `requirements.txt` must include these core tiers:

| Tier | Package | Role |
| --- | --- | --- |
| **Orchestration** | `langgraph` | Manages the state machine and decision-making logic. |
| **Protocol** | `mcp`, `fastmcp` | Standardizes the "bridge" between the LLM and Python tools. |
| **Adapter** | `langchain-mcp-adapters` | Converts MCP tool definitions into LangChain-compatible objects. |
| **Data** | `yfinance`, `pandas` | Fetches and processes raw financial market data. |

## 3. Architecture Requirements

### 3.1 The MCP Data Server (`finance_bridge.py`)

The server must implement a **Standard Input/Output (stdio)** transport layer. It should expose the following tool schemas:

* `get_market_snapshot(ticker)`: Returns current price, volume, and 52-week volatility.
* `get_sentiment_data(ticker)`: Pulls the last 5 institutional analyst ratings (e.g., Goldman Sachs, Morgan Stanley).

### 3.2 The LangGraph State Machine

The agent must follow a **ReAct** (Reasoning + Action) pattern with a persistent state:

* **State Schema:** Must store `messages`, `retrieved_financials`, and `analyst_signals`.
* **Checkpointer:** Use `langgraph.checkpoint.memory.InMemorySaver` for this session, with an option to migrate to SQLite for cross-session memory.

## 4. Operational Constraints

* **Cold Start:** The system should initialize and be ready for queries in under 5 seconds.
* **Token Efficiency:** The agent should be prompted to summarize tool outputs immediately to avoid overflowing the 128k context window of Llama 3.2 during long research sessions.
* **Error Handling:** If `yfinance` returns a `RateLimitError`, the MCP server must return a structured "Retry" message rather than crashing the graph.

---

### Recommended Repository Structure

```text
quant-ollama/
├── config.toml            # Model & Port settings
├── requirements.txt       # Versioned dependencies
├── src/
│   ├── server/            # MCP Tool Server logic
│   │   └── finance.py
│   ├── graph/             # LangGraph state & node definitions
│   │   ├── nodes.py
│   │   └── edges.py
│   └── main.py            # Entry point for the CLI
└── data/                  # Local SQLite storage for persistence

```
