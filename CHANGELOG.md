# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.1] — Repository consistency and security fixes
### Added
- Added `# nosec` markers to intentional subprocess calls to satisfy Bandit
- Standardized project version to `0.2.1` across all metadata files (`main.py`, `pyproject.toml`)
### Changed
- Updated CI pipeline to trigger on `master` branch
- Modernized `safety` command in CI to use `safety scan`
- Increased PBKDF2 iterations to 390,000 for better security alignment
- Added final risk score clamping to ensure 0-100 range
### Fixed
- Fixed broken filename references in `docs/idea.md`
- Synchronized `CLAUDE.md` architecture reference with full MCP toolset
- Removed obsolete `config.toml` leftover from development

## [Unreleased]

### Added (Phase C — thesis tracking + SYSTEM_PROMPT formatting fix)
- `src/persistence.py` — new `ThesisStore` class: encrypts per-analysis thesis records to `data/thesis.enc` using Fernet (same salt + same password as `SecurePortfolioManager`); one password unlocks both stores
- `GET /api/thesis` — returns the 200 most recent thesis records across all tickers (newest-first); requires portfolio unlock, returns `401` when locked
- `GET /api/thesis/{ticker}` — returns the 50 most recent thesis records for a single ticker; same auth requirement
- `SessionManager.add_analysis()` now persists to `ThesisStore` when unlocked, so every analysis after unlock is durably recorded across restarts
- `POST /api/portfolio/unlock` and `POST /api/portfolio/lock` now also unlock/lock the thesis store — one password, one action
- Thesis History card added to the Portfolio page (frontend): shows date · ticker · color-coded REC badge · confidence · price · key-risk preview; click-to-expand renders the full `ai_analysis` inline
- 13 new unit tests for `ThesisStore` (`tests/unit/test_persistence.py`); `ThesisStore` coverage 96.97%

### Changed (Phase C)
- `SYSTEM_PROMPT` OUTPUT FORMAT block replaced with explicit per-line formatting rules and a BAD/GOOD counter-example, requiring the LLM to put each header field on its own line, always emit `FAIR_VALUE`, and always use `##` section headers

### Added (Phase B — new MCP tools and data-aware enrichment)
- `get_earnings_calendar(ticker)` MCP tool — next earnings date, days until, EPS/revenue estimates, and `earnings_imminent` flag (true when ≤7 days away)
- `get_macro_context()` MCP tool — S&P 500 YTD return, VIX level + market regime (Risk-On / Normal / Elevated / Risk-Off), 10-year Treasury yield; 30-min TTL cache
- `get_sector_peers(ticker)` MCP tool — top 5 peers in the same GICS sector via `yf.Sector`; returns empty list (not an exception) when the Sector API is unavailable
- `quote_type` field added to `get_market_snapshot` response (enables ETF vs. stock branching downstream)
- `make_enrich_node` LangGraph node inserted between `prefetch` and `agent` on the single-ticker CLI path: always injects macro context; branches to fund holdings (ETF) or earnings calendar + sector peers (stock); prepends a DATA CAVEAT when ≥2 tools return degraded data; emits an EARNINGS CATALYST ALERT when earnings are ≤7 days away

### Added (Phase A — caching, structured output, watchlist startup)
- TTL caching on `get_market_snapshot` (15-min) and `get_sentiment_data` (15-min) to reduce redundant yfinance calls
- Structured LLM output: `POST /api/analyze` now parses and returns `recommendation`, `confidence`, `key_risk`, and `fair_value` extracted from the LLM response; parser handles single-line output, space vs. underscore variants (`FAIR VALUE` / `FAIR_VALUE`), and 0–100 vs. 0–1 confidence scales
- `POST /api/watchlist/refresh` endpoint — batch-fetches current prices for all watchlist tickers in parallel at startup; frontend calls this automatically so prices are populated before the first user interaction
- Ticker comparison: `POST /api/compare` fetches 6 MCP tools in parallel (3 per ticker) and returns a side-by-side LLM analysis with a `verdict` field naming the recommended ticker

### Changed (Phase A)
- SYSTEM_PROMPT updated to produce flowing prose (Thesis and Verdict as paragraphs, not bullets) with `##` section headers and blank lines between sections
- `fetchInitialData()` no longer auto-analyzes the last search bar ticker on page load — only the watchlist is loaded

### Added
- Full portfolio redesign: holdings table with Shares / Cost Per Share / Current Price / Total Value / G/L columns
- Equity allocation doughnut chart (lazy-initialized to avoid hidden-canvas sizing bug)
- Per-holding breakdown card showing share count and dollar G/L
- News article count is now adjustable live — changing the count input re-renders from a cached article pool without triggering a new API call
- Backend always fetches up to 20 news articles (the input's `max`); the frontend slices to the displayed count
- `state.currentNews` cache in frontend for post-analysis count changes
- Portfolio page hides the watchlist sidebar and expands to full width (`no-sidebar` CSS class toggle)
- Danger Zone relocated to portfolio page bottom as a full-width section

### Changed
- Complete visual redesign ("Meridian Dark" design system):
  - Accent color changed from `#3b82f6` (blue) to `#7c6ff7` (indigo-violet)
  - Gain/loss colors changed to emerald (`#10b981`) and rose (`#f43f5e`)
  - Signature 2px indigo→blue→emerald gradient top-line via `body::before`
  - `QO` square logo mark replaces the pulse dot, with a breathing glow animation
  - All financial numbers now use `font-variant-numeric: tabular-nums`
  - Card section headings styled as uppercase label text (0.68rem, 800 weight, wide letter-spacing)
  - Cards: deeper glass (`blur(24px) saturate(150%)`) with inner top-edge highlight
  - Status dots: online state gains a `box-shadow` glow
- Dashboard "Buy" button removed — dashboard is watchlist-only; portfolio input is via the modal
- Portfolio modal redesigned: Ticker + Number of Shares + Cost Basis Per Share → auto-calculated Total Cost (removed current-price field that triggered expensive full AI analysis)
- `cost_basis` is now stored as cost-per-share; G/L = `(qty × current_price) − (qty × cost_basis)`

### Fixed
- Broken "Buy" button on dashboard (had no event listener)
- Portfolio pie chart 0×0 size bug when canvas was inside a hidden element at page load (fixed by lazy initialization)
- Stale `add-portfolio-btn` DOM reference in `handleRemoveHolding()`
- Duplicate CSS block for `.portfolio-grid`, `.portfolio-header`, `.danger-zone`
- Cost basis double-counting: old code stored total cost but re-multiplied by quantity on render

---

## [0.2.0] — Multi-factor risk and structured LLM context

### Added
- Multi-factor risk score: volatility (40%) + analyst sentiment (30%) + P/E ratio (30%)
- Structured LLM context block passed to the model: price, volatility, analyst ratings, recent news, portfolio context (if unlocked)
- Long-term investment horizon framing in the system prompt
- Market cap, P/E ratio, and dividend yield fields in the market snapshot card
- Batch price fetching for portfolio holdings via `POST /api/portfolio/prices` (parallel yfinance calls)
- Model picker: `GET /api/config/models` lists all installed Ollama models; `POST /api/config/model` switches model at runtime
- News article count control in the dashboard UI
- Loading spinner in the search button during analysis
- Shutdown button in the header (`POST /api/admin/shutdown`) — gracefully stops backend and Ollama
- 30-day sparkline trend chart in the market snapshot card (new `get_trend_data` MCP tool)

### Changed
- Analysis prompt updated to focus on long-term fundamental investing rather than short-term signals
- Dashboard layout improved: card grid, icon updates, Danger Zone relocated

---

## [0.1.0] — Initial working system

### Added
- FastAPI backend with full analysis pipeline orchestrating MCP tool calls and LLM reasoning
- MCP Finance Server (`src/server/finance.py`) with tools: `get_market_snapshot`, `get_sentiment_data`, `get_news`, `get_fund_info`
- LangGraph ReAct state machine for multi-step reasoning (`src/graph/`)
- Vite + vanilla JS SPA dashboard with glassmorphism dark theme
- Watchlist: persistent storage, add/remove, last price display
- Portfolio: AES-256 encrypted holdings, PBKDF2HMAC key derivation, lock/unlock/wipe workflow
- Institutional sentiment bar chart (Buy / Strong Buy / Hold / Sell / Strong Sell)
- Analysis history per session
- Export endpoint (`GET /api/export/{ticker}`) — JSON and Markdown formats
- WebSocket endpoint (`ws://localhost:8000/ws/analysis`) for streaming analysis progress
- Pydantic-settings configuration with `MCPFOLIO_` env var prefix (`.env` support)
- Structured JSON logging with rotating file handler
- `@with_retry()` and `@circuit_breaker()` decorators on all MCP tools for yfinance rate limit resilience
- Ollama connection pool (`src/ollama_pool.py`) for concurrent request handling
- GitHub Actions CI: lint (Black, Ruff, MyPy), test matrix (ubuntu + macOS × Python 3.11 + 3.12), security scan (Safety + Bandit), build artifact
- Dependabot configuration for automated dependency updates

---

[Unreleased]: https://github.com/adkarp/mcpfolio/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/adkarp/mcpfolio/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/adkarp/mcpfolio/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/adkarp/mcpfolio/releases/tag/v0.1.0
