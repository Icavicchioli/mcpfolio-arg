# REST API Reference

Base URL: `http://localhost:8000` (default)

Interactive docs (Swagger UI): `http://localhost:8000/docs`
OpenAPI schema: `http://localhost:8000/openapi.json`

All request/response bodies are JSON. Errors follow the shape `{"detail": "<message>"}`.

---

## Health

### `GET /api/health`

Returns the current status of the backend and Ollama.

**Response `200`**
```json
{
  "status": "healthy",
  "ollama": {
    "ok": true,
    "message": "Ollama is running"
  },
  "model": {
    "ok": true,
    "message": "Model llama3.2:3b is available"
  },
  "timestamp": "2026-02-14T10:30:00.000000"
}
```

`status` is `"healthy"` when both `ollama.ok` and `model.ok` are true; otherwise `"degraded"`.

---

## Analysis

### `POST /api/analyze`

Runs the full analysis pipeline for a ticker: market snapshot → sentiment → news → LLM reasoning → risk score.

This is the slowest endpoint (~10–60 s depending on model and hardware). The LLM call is the dominant cost.

**Request body**
```json
{
  "ticker": "AAPL",
  "include_sentiment": true,
  "include_news": true,
  "include_fundamentals": true,
  "max_news": 20
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `ticker` | string | required | Stock symbol (1–10 chars, case-insensitive) |
| `include_sentiment` | bool | `true` | Fetch institutional analyst ratings |
| `include_news` | bool | `true` | Fetch recent news articles |
| `include_fundamentals` | bool | `true` | Include fundamentals in market snapshot |
| `max_news` | int | `5` | Max articles to fetch (backend clamps to 1–50) |
| `asset_type` | string | `equity` | `equity` or `cedear`; existing callers remain equities |
| `underlying_ticker` | string | `null` | Underlying Yahoo Finance ticker for a CEDEAR, e.g. `AAPL` |
| `quantity`, `cost_basis`, `cost_currency` | number, number, string | omitted, omitted, `USD` | Optional position context; cost basis is per held unit |
| `cedears_per_underlying` | number | `null` | User-declared CEDEAR units representing one underlying share |
| `ratio_source`, `ratio_as_of` | string, date | `null` | User-declared provenance; the app does not independently verify ratios |

**Response `200`**
```json
{
  "ticker": "AAPL",
  "timestamp": "2026-02-14T10:30:00.000000",
  "market_snapshot": {
    "ticker": "AAPL",
    "current_price": 227.50,
    "volume": 52345678,
    "high_52_week": 260.10,
    "low_52_week": 164.08,
    "volatility_52_week_pct": 58.55,
    "market_cap": 3450000000000,
    "pe_ratio": 31.2,
    "dividend_yield": 0.0044,
    "calendar": { ... },
    "analyst_targets": {
      "low": 180.0,
      "mean": 245.0,
      "high": 310.0,
      "current": 227.5
    },
    "quarterly_income": [ ... ]
  },
  "sentiment": [
    {
      "period": "2026-01",
      "strongBuy": 22,
      "buy": 8,
      "hold": 5,
      "sell": 1,
      "strongSell": 0
    }
  ],
  "news": [
    {
      "title": "Apple Reports Record Q1 Revenue",
      "publisher": "Reuters",
      "link": "https://...",
      "published_date": "2026-02-14 08:30:00"
    }
  ],
  "ai_analysis": "## Investment Assessment\n\nApple Inc. presents...",
  "risk_score": 35.2,
  "recommendation": "BUY",
  "confidence": 0.82,
  "key_risk": "High dependence on AI-driven growth and increasing debt load.",
  "fair_value": 305.72
}
```

`risk_score` is 0–100: 0–30 = Low, 31–70 = Medium, 71–100 = High.

`recommendation` is one of `BUY`, `HOLD`, `SELL`, or `CAUTION` (parsed from LLM output; `null` if the LLM did not emit the structured block).

`confidence` is 0.0–1.0; `key_risk` is a single-sentence summary; `fair_value` is the LLM's estimated intrinsic price (null if N/A or not emitted).

**Errors**
- `422` — invalid ticker length or missing field
- `500` — yfinance timeout, Ollama unavailable, or other internal error

For a CEDEAR, the response keeps its local quote metadata separate from an optional `underlying_snapshot`. If the underlying snapshot is unavailable, its fundamentals are reported unavailable instead of substituting CEDEAR-local data. A supplied ratio is always marked unverified.

---

### `GET /api/export/{ticker}`

Exports the most recent cached analysis for a ticker.

**Path parameters**
- `ticker` — stock symbol (case-insensitive)

**Query parameters**
- `format` — `json` (default) or `markdown`

**Response `200` (json)**

Same structure as `POST /api/analyze` response.

**Response `200` (markdown)**

`Content-Type: text/markdown` — a formatted Markdown report.

**Errors**
- `404` — no analysis cached for ticker in the current session
- `400` — unsupported format

---

## Watchlist

### `GET /api/watchlist`

Returns all saved watchlist items.

**Response `200`**
```json
{
  "watchlist": [
    {
      "ticker": "AAPL",
      "added_at": "2026-02-14T09:15:00",
      "last_price": 227.5,
      "last_updated": "2026-02-14T10:30:00"
    }
  ]
}
```

`last_price` and `last_updated` are populated after the ticker is analyzed at least once.

---

### `POST /api/watchlist/{ticker}`

Adds a ticker to the watchlist. Idempotent — adding a ticker that already exists is a no-op.

**Path parameters**
- `ticker` — stock symbol

**Response `200`**
```json
{ "status": "added", "ticker": "AAPL" }
```

---

### `DELETE /api/watchlist/{ticker}`

Removes a ticker from the watchlist.

**Response `200`**
```json
{ "status": "removed", "ticker": "AAPL" }
```

---

### `POST /api/watchlist/refresh`

Batch-fetches the current price for every ticker in the watchlist in parallel and updates their `last_price` / `last_updated` fields. Called automatically by the frontend on startup.

**Response `200`**
```json
{
  "watchlist": [
    {
      "ticker": "AAPL",
      "added_at": "2026-02-14T09:15:00",
      "last_price": 227.5,
      "last_updated": "2026-02-16T08:00:00"
    }
  ]
}
```

Tickers that fail to resolve (rate limit, invalid symbol) retain their previous `last_price` without erroring the whole request.

---

## Comparison

### `POST /api/compare`

Fetches market data for two tickers in parallel (6 concurrent MCP calls) and returns a side-by-side LLM analysis with a winner verdict.

**Request body**
```json
{
  "ticker_a": "AAPL",
  "ticker_b": "MSFT"
}
```

**Response `200`**
```json
{
  "ticker_a": "AAPL",
  "ticker_b": "MSFT",
  "analysis": "## AAPL vs MSFT\n\n...",
  "verdict": "MSFT"
}
```

`verdict` is whichever ticker the LLM recommended; parsed from a `COMPARISON: <TICKER>` line in the LLM output.

**Errors**
- `422` — missing or invalid ticker symbols
- `500` — data fetch failure or Ollama timeout

---

## Analysis History

### `GET /api/history`

Returns a summary of all tickers analyzed in the current server session.

**Response `200`**
```json
{
  "history": [
    {
      "ticker": "AAPL",
      "timestamp": "2026-02-14T10:30:00.000000",
      "risk_score": 35.2,
      "price": 227.5
    }
  ]
}
```

History is in-memory only. It resets when the server restarts.

---

## Thesis History

Thesis history persists across restarts, encrypted in `data/thesis.enc`. These endpoints require the portfolio to be unlocked first; they return `401` when locked.

---

### `GET /api/thesis`

Returns the 200 most recent thesis records across all tickers, newest-first.

**Response `200`**
```json
{
  "thesis": [
    {
      "ticker": "AAPL",
      "timestamp": "2026-02-16T10:30:00.000000",
      "recommendation": "BUY",
      "confidence": 0.82,
      "key_risk": "High valuation premium relative to peers.",
      "fair_value": 250.0,
      "risk_score": 35.2,
      "price": 227.5,
      "ai_analysis": "## Thesis\n\n..."
    }
  ]
}
```

**Errors**
- `401` — portfolio locked

---

### `GET /api/thesis/{ticker}`

Returns the 50 most recent thesis records for a single ticker, newest-first.

**Path parameters**
- `ticker` — stock symbol (case-insensitive)

**Response `200`**

Same structure as `GET /api/thesis` but filtered to the requested ticker.

**Errors**
- `401` — portfolio locked

---

## Portfolio

All portfolio endpoints require the portfolio to be unlocked first. Endpoints return `401` if the portfolio is locked.

---

### `POST /api/portfolio/unlock`

Unlocks the portfolio **and** thesis history for the current session. Derives the Fernet encryption key from the password and verifies it against the stored ciphertext. Both `data/portfolio.enc` and `data/thesis.enc` use the same salt and key.

**Request body**
```json
{ "password": "my-secret-password" }
```

**Response `200`**
```json
{ "status": "unlocked" }
```

**Errors**
- `401` — wrong password (the ciphertext fails to decrypt)

---

### `POST /api/portfolio/lock`

Locks the portfolio **and** thesis history, clearing the session key from memory.

**Response `200`**
```json
{ "status": "locked" }
```

---

### `GET /api/portfolio`

Returns all holdings. Requires unlock.

**Response `200`**
```json
{
  "holdings": [
    {
      "ticker": "AAPL",
      "quantity": 10.0,
      "cost_basis": 150.00,
      "added_at": "2026-01-15T14:00:00"
    }
  ]
}
```

`cost_basis` is the **per-share** purchase price.

**Errors**
- `401` — portfolio locked

---

### `POST /api/portfolio`

Adds or replaces a holding. If the ticker already exists, it is replaced.

**Request body**
```json
{
  "ticker": "AAPL",
  "quantity": 10.0,
  "cost_basis": 150.00,
  "added_at": "2026-01-15T14:00:00"
}
```

| Field | Type | Constraints | Description |
|---|---|---|---|
| `ticker` | string | required | Stock symbol |
| `quantity` | float | `> 0` | Number of held units (shares or CEDEARs) |
| `cost_basis` | float | `> 0` | Average cost per held unit |
| `added_at` | datetime | required | ISO 8601 timestamp |
| `asset_type` | string | `equity` | `equity` or `cedear` |
| `cost_currency` | string | `USD` | Three-letter currency code for `cost_basis` |
| `underlying_ticker` | string | `null` | Underlying symbol for a CEDEAR |
| `cedears_per_underlying` | number | `null` | CEDEAR units per one underlying share; user-verified only |
| `ratio_source`, `ratio_as_of` | string, date | `null` | User-declared ratio source and check date |

**Response `200`**
```json
{ "status": "saved", "ticker": "AAPL" }
```

**Errors**
- `401` — portfolio locked
- `422` — validation error (e.g., quantity ≤ 0)

---

### `DELETE /api/portfolio/{ticker}`

Removes a holding by ticker.

**Response `200`**
```json
{ "status": "removed", "ticker": "AAPL" }
```

**Errors**
- `401` — portfolio locked

---

### `POST /api/portfolio/prices`

Batch-fetches market prices for holdings. Calls `get_market_snapshot` in parallel for each ticker; the legacy `tickers` body remains supported.

**Request body**
```json
{ "tickers": ["AAPL", "MSFT", "GOOGL"] }
```

For quote metadata and per-position valuation, send full positions:

```json
{
  "positions": [
    {
      "ticker": "AAPL.BA",
      "quantity": 10,
      "cost_basis": 27000,
      "cost_currency": "ARS",
      "asset_type": "cedear",
      "underlying_ticker": "AAPL",
      "cedears_per_underlying": 10,
      "ratio_source": "User-provided source",
      "ratio_as_of": "2026-10-01"
    }
  ]
}
```

**Response `200`**
```json
{
  "prices": {
    "AAPL": 227.50,
    "MSFT": 415.30,
    "GOOGL": 192.10
  }
}
```

Tickers that fail to fetch (rate limit, invalid symbol) are omitted from the response without erroring the whole request. Detailed quotes include currency, exchange, source, timestamp and freshness; enriched positions include market value, cost/P&L comparability and underlying-equivalent quantity.

Totals are grouped by currency. P/L is `null` if the cost currency differs from the quote currency or the quote is missing; no FX rate is inferred. Equivalent underlying quantity is `quantity / cedears_per_underlying`, and is unavailable if the ratio or underlying is missing. Ratio statuses are `missing`, `invalid`, `user_provided_unverified`, or `stale_unverified`; no status claims independent verification. Quote statuses are `fresh`, `stale`, or `unknown` (older than seven days is stale).

**Errors**
- `500` — market data tool unavailable

---

### `POST /api/portfolio/wipe`

Permanently deletes the encrypted portfolio file from disk. Irreversible.

**Response `200`**
```json
{ "status": "wiped" }
```

---

## Configuration

### `GET /api/config/models`

Lists all Ollama models installed locally.

**Response `200`**
```json
{
  "models": [
    { "name": "llama3.2:3b", "model": "llama3.2:3b" },
    { "name": "mistral:7b",  "model": "mistral:7b" }
  ],
  "active": "llama3.2:3b"
}
```

---

### `POST /api/config/model`

Switches the active model at runtime. Takes effect on the next analysis request.

**Request body**
```json
{ "model": "mistral:7b" }
```

**Response `200`**
```json
{ "status": "updated", "active": "mistral:7b" }
```

**Errors**
- `400` — missing model name

---

## Admin

### `POST /api/admin/shutdown`

Initiates a graceful shutdown of the FastAPI server and Ollama (via `pkill`). The process exits ~1 second after the response is returned.

**Response `200`**
```json
{
  "status": "shutting_down",
  "message": "Backend and Ollama services will stop in 1 second."
}
```

---

## Market Data (MCP passthrough)

### `GET /api/mcp/finance-server/get_trend_data`

Fetches historical daily price data for charting. Proxied directly to the MCP `get_trend_data` tool.

**Query parameters**
- `ticker` — stock symbol (required)
- `period` — yfinance period string: `1d`, `5d`, `1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `10y`, `ytd`, `max` (default: `1mo`)

**Response `200`**
```json
{
  "ticker": "AAPL",
  "period": "1mo",
  "count": 22,
  "points": [
    { "date": "2026-01-14", "price": 220.10, "volume": 48234567 },
    { "date": "2026-01-15", "price": 222.45, "volume": 51023456 }
  ]
}
```

**Errors**
- `200` with `{"error": "...", "error_type": "..."}` — yfinance errors are returned as a successful HTTP response with an `error` key (MCP convention)

---

## WebSocket

### `ws://localhost:8000/ws/analysis`

Streams analysis progress updates. Useful for building custom frontends or integrations that want real-time feedback during the LLM reasoning step.

**Send**
```json
{ "ticker": "AAPL" }
```

**Receive (sequence)**
```json
{ "type": "status",   "message": "Starting analysis for AAPL..." }
{ "type": "complete", "result": { ... } }
```

Or on error:
```json
{ "type": "error", "message": "Analysis failed: ..." }
{ "type": "error", "message": "No ticker provided" }
```

The `result` object in `complete` messages has the same shape as the `POST /api/analyze` response.

---

### `ws://localhost:8000/ws/advisor`

Real-time streaming endpoint for the Advisor chat interface. Streams LLM tokens, tool calls, and status events using LangGraph's `astream_events` API.

**Send (user message)**
```json
{ "message": "How's NVDA doing?" }
```

**Send (clear conversation)**
```json
{ "action": "clear" }
```

**Receive (event stream)**

Token event (during LLM response):
```json
{ "type": "token", "content": "Based on" }
```

Tool start event (when MCP tool begins):
```json
{
  "type": "tool_start",
  "tool": "get_market_snapshot",
  "input": { "ticker": "NVDA" }
}
```

Tool end event (when MCP tool completes):
```json
{ "type": "tool_end", "tool": "get_market_snapshot" }
```

Response complete event:
```json
{ "type": "done" }
```

Conversation cleared event:
```json
{ "type": "cleared" }
```

Error event:
```json
{ "type": "error", "message": "Tool execution failed: ..." }
```

**Event Flow**

A typical exchange looks like:
1. User sends `{ "message": "Tell me about AAPL" }`
2. Server emits `tool_start` for `get_market_snapshot`
3. Server emits `tool_end` for `get_market_snapshot`
4. Server emits a stream of `token` events (LLM response, word by word)
5. Server emits `done`

The client buffers tokens during tool execution (while `active_tools` is non-empty) and only displays them after all tools complete, preventing the LLM from responding before data is fetched.

**Conversation Memory**

The endpoint uses LangGraph's `MemorySaver` checkpointer with a persistent `thread_id`. Follow-up questions like "what about its competitors?" work because the full conversation history is preserved. Sending `{ "action": "clear" }` resets the thread to a new UUID and clears the graph state.

**Portfolio Context**

When the portfolio is unlocked, the user's current holdings are injected as a fresh `SystemMessage` at the start of each turn. This context is NOT stored in the conversation history — it's added dynamically so the LLM always sees up-to-date holdings without polluting the thread state.

---

## Error Format

All HTTP errors follow FastAPI's default shape:

```json
{ "detail": "Human-readable error message" }
```

Common status codes:

| Code | Meaning |
|---|---|
| `400` | Bad request (missing or invalid parameter) |
| `401` | Portfolio locked or wrong password |
| `404` | Resource not found (e.g., no cached analysis for ticker) |
| `422` | Request validation failed (Pydantic schema mismatch) |
| `500` | Internal error (yfinance failure, Ollama timeout, etc.) |
