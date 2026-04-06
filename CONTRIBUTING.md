# Contributing to MCPFolio

MCPFolio was vibe-coded with [Claude Code](https://claude.ai/code) + [Antigravity](https://antigravity.google/), and **vibe-coded contributions are explicitly welcome**. If you built something by pair-programming with an AI, ran it, and it worked — open a PR. The bar is working code, not a particular development process.

This document covers getting a local environment running, code conventions, and how to submit changes. There is no CLA. By contributing, you agree that your contributions are licensed under the [BSD 3-Clause License](LICENSE).

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | 3.12 also tested in CI |
| Ollama | Latest | [ollama.com](https://ollama.com) |
| Node.js | 18 | Only needed for frontend changes |
| conda | Any | Recommended; venv also works |

---

## Local Setup

```bash
# 1. Fork and clone
git clone https://github.com/adkarp/mcpfolio.git
cd mcpfolio

# 2. Create environment
conda create -n mcpfolio python=3.11 -y
conda activate mcpfolio

# 3. Install all dependencies (runtime + dev)
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. Pull a model
ollama pull llama3.2:3b

# 5. Start the dashboard
bash scripts/start-dashboard.sh
```

The script handles conda environment activation, Ollama startup, and health-checking automatically.

### Frontend dev server (with hot reload)

```bash
cd src/web/frontend
npm install
npm run dev   # Vite dev server on :5173, proxies /api/* to :8000
```

In a separate terminal, start the backend:

```bash
bash scripts/start-dashboard.sh
```

---

## Project Layout

```
src/
├── config.py           # All settings (env vars, .env)
├── server/finance.py   # MCP server — this is where new data tools go
├── web/main.py         # FastAPI app — REST endpoints
└── web/frontend/src/
    ├── main.js         # All frontend logic (no framework)
    └── style.css       # Design system (CSS custom properties)
```

When adding new **market data capabilities**, add a tool to `src/server/finance.py` decorated with `@mcp.tool()`. It will be automatically available to the FastAPI layer and the LLM.

When adding **new API endpoints**, add them to `src/web/main.py` with a Pydantic request/response model.

---

## Code Quality

The CI pipeline enforces three checks. Run them locally before pushing:

```bash
# Auto-format code
black src/ tests/

# Lint (errors block CI; warnings are advisory)
ruff check src/ tests/

# Type checking (advisory)
mypy src/
```

All three tools are configured in `pyproject.toml` (or `setup.cfg` if present). Black's line length is 100; Ruff uses sensible defaults with a few project-specific ignores.

For frontend changes, make sure the production build passes:

```bash
cd src/web/frontend && npm run build
```

---

## Testing

```bash
# Run all tests
pytest

# Run a single file
pytest tests/test_finance_server.py -v

# With coverage report
pytest --cov=src --cov-report=term-missing
```

Tests live in `tests/`. The CI matrix runs on:
- **OS**: ubuntu-latest, macos-latest
- **Python**: 3.11, 3.12

Add tests for any new MCP tool or API endpoint. Tests that require a live Ollama instance should be marked `@pytest.mark.integration` so they can be skipped in environments where Ollama isn't available.

---

## Environment Variables

Copy `.env.example` to `.env` and adjust for your setup. The most relevant dev settings:

```bash
MCPFOLIO_OLLAMA_MODEL=llama3.2:3b
MCPFOLIO_LOG_LEVEL=DEBUG
MCPFOLIO_LOG_JSON_FORMAT=false   # Human-readable logs in dev
MCPFOLIO_YFINANCE_CACHE_TTL=60   # Shorter cache for faster dev iteration
```

All settings have the `MCPFOLIO_` prefix and are documented in `src/config.py`.

---

## Submitting Changes

1. **Create a new branch**:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make your changes**, following the conventions above.

3. **Run quality checks** locally (Black, Ruff, tests).

4. **Commit** using [Conventional Commits](https://www.conventionalcommits.org/):
   ```
   feat: add intraday price endpoint
   fix: handle yfinance rate limit on sentiment fetch
   docs: add MCP tool reference to API docs
   refactor: extract portfolio math helpers
   test: cover get_fund_info error paths
   ```

5. **Open a pull request** against `main`. The CI pipeline runs automatically. Address any failures before requesting review.

---

## Adding a New MCP Tool

1. Add the function to `src/server/finance.py` with the `@mcp.tool()` decorator:
   ```python
   @mcp.tool()
   @with_retry()
   @circuit_breaker()
   def get_my_data(ticker: str) -> dict:
       """Fetches ... for a given ticker."""
       ...
   ```

2. The tool is automatically exposed to the FastAPI layer via `src/tools/lazy_loader.py`. To call it directly from an endpoint, resolve it from the tool map:
   ```python
   tools = await get_mcp_tools()
   tool_map = {tool.name: tool for tool in tools}
   result = await tool_map["get_my_data"].ainvoke({"ticker": ticker})
   ```

3. Add a test in `tests/test_finance_server.py`.

4. Update `docs/API.md` if exposing the tool through a new REST endpoint.

---

## Reporting Bugs

Open a [GitHub Issue](../../issues) with:
- What you did
- What you expected
- What happened (include the relevant log lines from `logs/mcpfolio.log`)
- Your OS, Python version, and Ollama model

---

## Questions

Open a Discussion or an Issue — both are fine.
