"""
FastAPI web application for Quant-Ollama.

Provides REST API and WebSocket endpoints for financial analysis.
"""

import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.config import get_settings
from src.logging_config import get_logger, start_request
from src.prompts import SYSTEM_PROMPT
from src.startup import quick_startup, shutdown

logger = get_logger(__name__)
settings = get_settings()


# Pydantic Models
class AnalysisRequest(BaseModel):
    """Request for stock analysis"""

    ticker: str = Field(..., description="Stock ticker symbol", min_length=1, max_length=10)
    include_news: bool = Field(True, description="Include news analysis")
    include_sentiment: bool = Field(True, description="Include sentiment data")
    include_fundamentals: bool = Field(True, description="Include fundamental data")
    max_news: int = Field(5, description="Max news articles to fetch")


class WatchlistItem(BaseModel):
    """Watchlist item"""

    ticker: str
    added_at: datetime
    last_price: float | None = None
    last_updated: datetime | None = None


class MarketSnapshotData(BaseModel):
    """Market snapshot data"""

    price: float
    volume: int
    volatility_52week: float
    change_percent: float = 0.0


class SentimentRating(BaseModel):
    """Analyst sentiment rating"""

    firm: str
    action: str
    grade: str | None = None


class AnalysisResponse(BaseModel):
    """Complete analysis response"""

    ticker: str
    timestamp: datetime
    market_snapshot: dict
    sentiment: list[dict] | None = None
    news: list[dict] | None = None
    ai_analysis: str
    risk_score: float = Field(..., ge=0, le=100, description="Risk score 0-100")


class PortfolioItem(BaseModel):
    """Portfolio holding item"""

    ticker: str
    quantity: float = Field(..., gt=0)
    cost_basis: float = Field(..., gt=0)
    added_at: datetime


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    ollama: dict
    model: dict
    timestamp: str


class SecurePortfolioManager:
    """Manages encrypted portfolio data using AES-256 (Fernet)"""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.portfolio_path = self.data_dir / "portfolio.enc"
        self.salt_path = self.data_dir / "portfolio.salt"
        self.key: bytes | None = None
        self.fernet: Fernet | None = None

    def _get_or_create_salt(self) -> bytes:
        if self.salt_path.exists():
            return self.salt_path.read_bytes()
        salt = os.urandom(16)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.salt_path.write_bytes(salt)
        return salt

    def unlock(self, password: str) -> bool:
        """Derive key from password and pre-flight check if data exists"""
        try:
            salt = self._get_or_create_salt()
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=390000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
            fernet = Fernet(key)

            # Check if file exists, try to decrypt a dummy or first block if possible
            # For simplicity, we just set it and let subsequent reads fail if wrong
            self.key = key
            self.fernet = fernet

            if self.portfolio_path.exists():
                # Verify key by trying to load
                self.load()
            return True
        except Exception as e:
            logger.error("portfolio_unlock_error", error=str(e))
            self.key = None
            self.fernet = None
            return False

    def lock(self):
        """Clear key from memory"""
        self.key = None
        self.fernet = None

    def is_unlocked(self) -> bool:
        return self.fernet is not None

    def wipe(self):
        """Purge all portfolio data"""
        if self.portfolio_path.exists():
            self.portfolio_path.unlink()
        if self.salt_path.exists():
            self.salt_path.unlink()
        self.lock()
        logger.warning("portfolio_wiped")

    def save(self, data: list[PortfolioItem]):
        if not self.fernet:
            raise HTTPException(status_code=401, detail="Portfolio locked")
        raw_data = json.dumps([item.model_dump(mode="json") for item in data]).encode()
        encrypted_data = self.fernet.encrypt(raw_data)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.portfolio_path.write_bytes(encrypted_data)

    def load(self) -> list[PortfolioItem]:
        if not self.fernet:
            raise HTTPException(status_code=401, detail="Portfolio locked")
        if not self.portfolio_path.exists():
            return []
        encrypted_data = self.portfolio_path.read_bytes()
        try:
            decrypted_data = self.fernet.decrypt(encrypted_data)
            data = json.loads(decrypted_data)
            return [PortfolioItem(**item) for item in data]
        except Exception:
            self.lock()  # Bad key?
            raise HTTPException(status_code=401, detail="Invalid password or corrupted data")


# Session Manager (single user, in-memory)
class SessionManager:
    """Manage user session data (single user)"""

    def __init__(self):
        self.data_dir = Path("data")
        self.watchlist_path = self.data_dir / "watchlist.json"
        self.watchlist: list[WatchlistItem] = []
        self.portfolio_manager = SecurePortfolioManager(self.data_dir)
        self.analysis_history: list[AnalysisResponse] = []
        self.max_history = 50

        # Load from disk
        self._load_watchlist()

        logger.info("session_manager_initialized", max_history=self.max_history)

    def _load_watchlist(self):
        """Load watchlist from disk"""
        try:
            if self.watchlist_path.exists():
                with open(self.watchlist_path) as f:
                    data = json.load(f)
                    self.watchlist = [WatchlistItem(**item) for item in data]
                logger.info("watchlist_loaded_from_disk", count=len(self.watchlist))
        except Exception as e:
            logger.error("watchlist_load_error", error=str(e))

    def _save_watchlist(self):
        """Save watchlist to disk"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.watchlist_path, "w") as f:
                json.dump([w.model_dump(mode="json") for w in self.watchlist], f)
            logger.debug("watchlist_saved_to_disk")
        except Exception as e:
            logger.error("watchlist_save_error", error=str(e))

    def add_to_watchlist(self, ticker: str, price: float | None = None):
        """Add ticker to watchlist"""
        ticker = ticker.upper()
        # Check if already exists
        if any(w.ticker == ticker for w in self.watchlist):
            logger.debug("ticker_already_in_watchlist", ticker=ticker)
            return

        item = WatchlistItem(
            ticker=ticker,
            added_at=datetime.now(),
            last_price=price,
            last_updated=datetime.now() if price else None,
        )
        self.watchlist.append(item)
        self._save_watchlist()
        logger.info("ticker_added_to_watchlist", ticker=ticker)

    def remove_from_watchlist(self, ticker: str):
        """Remove ticker from watchlist"""
        ticker = ticker.upper()
        self.watchlist = [w for w in self.watchlist if w.ticker != ticker]
        self._save_watchlist()
        logger.info("ticker_removed_from_watchlist", ticker=ticker)

    def update_watchlist_price(self, ticker: str, price: float):
        """Update price for watchlist item"""
        ticker = ticker.upper()
        for item in self.watchlist:
            if item.ticker == ticker:
                item.last_price = price
                item.last_updated = datetime.now()
                logger.debug("watchlist_price_updated", ticker=ticker, price=price)
                break

    def add_analysis(self, analysis: AnalysisResponse):
        """Add analysis to history"""
        self.analysis_history.insert(0, analysis)
        if len(self.analysis_history) > self.max_history:
            removed = self.analysis_history.pop()
            logger.debug("analysis_removed_from_history", ticker=removed.ticker)
        logger.info("analysis_added_to_history", ticker=analysis.ticker)

    def get_analysis(self, ticker: str) -> AnalysisResponse | None:
        """Get most recent analysis for ticker"""
        ticker = ticker.upper()
        for analysis in self.analysis_history:
            if analysis.ticker == ticker:
                return analysis
        return None


# WebSocket Connection Manager
class ConnectionManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        logger.info("connection_manager_initialized")

    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("websocket_connected", total_connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("websocket_disconnected", total_connections=len(self.active_connections))

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific connection"""
        await websocket.send_json(message)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error("broadcast_error", error=str(e))


# Initialize managers
session = SessionManager()
ws_manager = ConnectionManager()


# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """Lifespan context manager for startup/shutdown"""
    # Startup
    logger.info("application_starting")
    startup_result = await quick_startup(skip_health_checks=False)
    logger.info(
        "application_started",
        startup_time_ms=startup_result.startup_time_ms,
        ready=startup_result.ready,
        version="0.2.1-debug-fixes",
    )

    yield

    # Shutdown
    logger.info("application_shutting_down")
    await shutdown()
    logger.info("application_shutdown_complete")


# Create FastAPI app
app = FastAPI(
    title="Quant-Ollama API",
    version="0.2.1",
    description="Local-first financial analyst API",
    lifespan=lifespan,
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (serve built frontend)
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")


def parse_tool_result(result: Any) -> dict:
    """Extract and parse JSON from MCP tool result list"""
    try:
        if isinstance(result, list) and len(result) > 0:
            content = result[0]
            if isinstance(content, dict) and content.get("type") == "text":
                return cast(dict[Any, Any], json.loads(content.get("text", "{}")))
        elif isinstance(result, dict):
            return result
        return {"error": "Unexpected tool result format", "raw": str(result)}
    except Exception as e:
        return {"error": f"Failed to parse tool result: {str(e)}", "raw": str(result)}


# Helper function to run analysis
async def run_analysis_task(request: AnalysisRequest) -> AnalysisResponse:
    """
    Run analysis on a ticker.

    This orchestrates the full analysis workflow:
    1. Get market snapshot
    2. Get sentiment data (if requested)
    3. Get news (if requested)
    4. Run LLM analysis
    5. Calculate risk score
    """
    from src.tools.lazy_loader import get_mcp_tools

    # Get MCP tools (lazy loaded)
    tools = await get_mcp_tools()
    logger.info("analysis_started", ticker=request.ticker)

    # Find the tools we need
    tool_map = {tool.name: tool for tool in tools}

    # Get market snapshot
    market_snapshot_tool = tool_map.get("get_market_snapshot")
    if not market_snapshot_tool:
        raise HTTPException(status_code=500, detail="Market snapshot tool not available")

    raw_market_data = await market_snapshot_tool.ainvoke({"ticker": request.ticker})
    market_data = parse_tool_result(raw_market_data)

    if market_data.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to get market data: {market_data.get('message', market_data.get('error', 'Unknown error'))}",
        )

    # Get sentiment data
    sentiment_data = None
    if request.include_sentiment:
        sentiment_tool = tool_map.get("get_sentiment_data")
        if sentiment_tool:
            raw_sentiment = await sentiment_tool.ainvoke({"ticker": request.ticker})
            sentiment_result = parse_tool_result(raw_sentiment)
            if not sentiment_result.get("error"):
                sentiment_data = sentiment_result.get("ratings", [])

    # Get news
    news_data = None
    if request.include_news:
        news_tool = tool_map.get("get_news")
        if news_tool:
            raw_news = await news_tool.ainvoke(
                {"ticker": request.ticker, "count": request.max_news}
            )
            news_result = parse_tool_result(raw_news)
            if not news_result.get("error"):
                news_data = news_result.get("news", [])

    # Multi-factor risk score: volatility (40%), analyst sentiment (30%), P/E (30%)
    volatility = market_data.get("volatility_52_week_pct", 0) / 100
    vol_score = min(volatility * 100, 100)  # 0-100: 50% vol -> 50 score

    # Analyst sentiment component: more buy ratings = lower risk
    sentiment_score = 50.0  # neutral default when no data
    if sentiment_data:
        buy_count = sum(
            1
            for r in sentiment_data
            if any(
                g in (r.get("grade") or r.get("action") or "").upper()
                for g in ("BUY", "OVERWEIGHT", "OUTPERFORM")
            )
        )
        sell_count = sum(
            1
            for r in sentiment_data
            if any(
                g in (r.get("grade") or r.get("action") or "").upper()
                for g in ("SELL", "UNDERWEIGHT", "UNDERPERFORM")
            )
        )
        total = len(sentiment_data)
        if total > 0:
            # Ranges from 0 (all buy) to 100 (all sell)
            sentiment_score = max(0, min(100, 50 - (buy_count - sell_count) / total * 50))

    # P/E ratio component: extreme values raise risk, moderate is neutral
    pe_ratio = market_data.get("pe_ratio") or market_data.get("trailing_pe")
    pe_score = 50.0  # neutral default
    if pe_ratio is not None and pe_ratio > 0:
        if pe_ratio < 10:
            pe_score = 60  # very low P/E can signal value trap
        elif pe_ratio < 25:
            pe_score = 20  # healthy range
        elif pe_ratio < 40:
            pe_score = 40  # growth premium, moderate risk
        elif pe_ratio < 60:
            pe_score = 65  # elevated
        else:
            pe_score = 85  # extreme valuation
    elif pe_ratio is not None and pe_ratio < 0:
        pe_score = 80  # negative earnings

    risk_score = max(0.0, min(100.0, vol_score * 0.4 + sentiment_score * 0.3 + pe_score * 0.3))

    # --- Refactored AI Analysis ---
    from langchain_ollama import ChatOllama

    ollama_config = settings.get_ollama_config()
    # Ensure low temperature as requested
    ollama_config["temperature"] = 0.1
    llm = ChatOllama(**ollama_config)

    # Construct a structured summary for the LLM (avoids dumping raw JSON)
    price = market_data.get("current_price", "N/A")
    mkt_cap = market_data.get("market_cap")
    mkt_cap_str = (
        f"${mkt_cap / 1e9:.1f}B"
        if mkt_cap and mkt_cap > 1e9
        else f"${mkt_cap / 1e6:.0f}M" if mkt_cap else "N/A"
    )
    pe_display = pe_ratio if pe_ratio is not None else "N/A"
    div_yield = market_data.get("dividend_yield")
    div_str = f"{div_yield * 100:.2f}%" if div_yield else "None"
    vol_pct = market_data.get("volatility_52_week_pct", 0)
    week_high = market_data.get("fifty_two_week_high", "N/A")
    week_low = market_data.get("fifty_two_week_low", "N/A")
    change_pct = market_data.get("change_percent", 0)
    eps = market_data.get("eps") or market_data.get("trailing_eps") or "N/A"
    rev = market_data.get("revenue")
    rev_str = f"${rev / 1e9:.1f}B" if rev and rev > 1e9 else f"${rev / 1e6:.0f}M" if rev else "N/A"

    context = f"""MARKET DATA:
- Price: ${price} ({change_pct:+.2f}% today)
- Market Cap: {mkt_cap_str}
- P/E Ratio: {pe_display}
- EPS: {eps}
- Revenue: {rev_str}
- Dividend Yield: {div_str}
- 52-Week Range: ${week_low} – ${week_high} (volatility: {vol_pct:.1f}%)
"""

    if sentiment_data:
        ratings_summary = []
        for r in sentiment_data:
            firm = r.get("firm", "Unknown")
            grade = r.get("grade") or r.get("action") or "N/A"
            ratings_summary.append(f"  - {firm}: {grade}")
        context += (
            f"\nANALYST RATINGS ({len(sentiment_data)} recent):\n"
            + "\n".join(ratings_summary)
            + "\n"
        )
    else:
        context += "\nANALYST RATINGS: No data available.\n"

    if news_data:
        news_lines = []
        for n in news_data[:5]:
            title = n.get("title", "")
            source = n.get("publisher") or n.get("source") or ""
            news_lines.append(f"  - {title}" + (f" ({source})" if source else ""))
        context += "\nRECENT NEWS:\n" + "\n".join(news_lines) + "\n"
    else:
        context += "\nRECENT NEWS: No data available.\n"

    # Portfolio context if unlocked
    if session.portfolio_manager.is_unlocked():
        holdings = session.portfolio_manager.load()
        ticker_holding = next((h for h in holdings if h.ticker == request.ticker.upper()), None)
        if ticker_holding:
            context += f"\nUser Portfolio Holding: {ticker_holding.quantity} shares @ ${ticker_holding.cost_basis} cost basis."

    logger.info("ai_synthesis_started", ticker=request.ticker)
    try:
        llm_response = await llm.ainvoke(
            [
                ("system", SYSTEM_PROMPT),
                ("user", f"Retrieved context for {request.ticker}:\n{context}"),
            ]
        )
        ai_analysis = llm_response.content
        logger.info("ai_synthesis_complete", ticker=request.ticker)
    except Exception as e:
        logger.error("ai_synthesis_failed", error=str(e))
        ai_analysis = f"Error generating robust AI analysis: {str(e)}\n\nFallback: {ai_analysis}"

    response = AnalysisResponse(
        ticker=request.ticker.upper(),
        timestamp=datetime.now(),
        market_snapshot=market_data,
        sentiment=sentiment_data,
        news=news_data,
        ai_analysis=ai_analysis,
        risk_score=risk_score,
    )

    # Add to session history
    session.add_analysis(response)

    # Update watchlist if ticker is in it
    if any(w.ticker == request.ticker.upper() for w in session.watchlist):
        session.update_watchlist_price(request.ticker, market_data.get("current_price", 0))

    logger.info(
        "analysis_complete",
        ticker=request.ticker,
        risk_score=risk_score,
        has_sentiment=sentiment_data is not None,
        has_news=news_data is not None,
    )

    return response


# REST Endpoints
@app.get("/api/config/models")
async def get_available_models():
    """Get available Ollama models"""
    from src.ollama_pool import get_ollama_client, return_ollama_client

    client = get_ollama_client()
    try:
        response = client.list()
        # Ensure each model has a 'name' field for frontend compatibility
        model_list = []
        for m in response.get("models", []):
            m_dict = dict(m) if not isinstance(m, dict) else m
            name = m_dict.get("model") or m_dict.get("name")
            model_list.append({"name": name, **m_dict})

        return {"models": model_list, "active": settings.ollama_model}
    finally:
        return_ollama_client(client)


@app.post("/api/config/model")
async def set_active_model(model_request: dict):
    """Set the active Ollama model"""
    model_name = model_request.get("model")
    if not model_name:
        raise HTTPException(status_code=400, detail="Model name required")

    settings.ollama_model = model_name
    logger.info("active_model_changed", model=model_name)
    return {"status": "updated", "active": settings.ollama_model}


@app.post("/api/portfolio/prices")
async def get_portfolio_prices(request: dict):
    """
    Batch fetch current prices for a list of tickers.
    Request body: {"tickers": ["AAPL", "MSFT", ...]}
    """
    tickers = request.get("tickers", [])
    if not tickers:
        return {"prices": {}}

    from src.tools.lazy_loader import get_mcp_tools

    tools = await get_mcp_tools()
    tool_map = {tool.name: tool for tool in tools}
    market_tool = tool_map.get("get_market_snapshot")

    if not market_tool:
        raise HTTPException(status_code=500, detail="Market tool unavailable")

    results = {}
    # Process in parallel
    tasks = [market_tool.ainvoke({"ticker": t}) for t in tickers]
    tool_outputs = await asyncio.gather(*tasks, return_exceptions=True)

    for ticker, output in zip(tickers, tool_outputs, strict=False):
        if isinstance(output, Exception):
            logger.error(f"Failed to fetch price for {ticker}: {output}")
            continue

        data = parse_tool_result(output)
        if data and data.get("current_price"):
            results[ticker.upper()] = data.get("current_price")

    return {"prices": results}


@app.post("/api/admin/shutdown")
async def shutdown_all():
    """Shutdown backend and Ollama"""
    logger.info("remote_shutdown_triggered")

    async def perform_shutdown():
        await asyncio.sleep(1)
        # Attempt to kill ollama process if we started it
        import subprocess  # nosec
        from contextlib import suppress

        with suppress(Exception):
            subprocess.run(["pkill", "-f", "ollama serve"], check=False)  # nosec

        import os

        os._exit(0)

    asyncio.create_task(perform_shutdown())
    return {
        "status": "shutting_down",
        "message": "Backend and Ollama services will stop in 1 second.",
    }


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the dashboard UI"""
    frontend_index = Path(__file__).parent / "frontend" / "dist" / "index.html"
    if frontend_index.exists():
        return FileResponse(
            str(frontend_index),
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    # Fallback to API lander if frontend not built
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Quant-Ollama API</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 800px;
                margin: 50px auto;
                padding: 20px;
            }
            h1 { color: #2563eb; }
            .endpoint { background: #f3f4f6; padding: 10px; margin: 10px 0; border-radius: 5px; }
            code { background: #e5e7eb; padding: 2px 6px; border-radius: 3px; }
        </style>
    </head>
    <body>
        <h1>🤖 Quant-Ollama API</h1>
        <p>Local-first financial analyst API v0.2.0</p>

        <h2>Available Endpoints:</h2>
        <div class="endpoint">
            <strong>GET /api/health</strong> - Health check
        </div>
        <div class="endpoint">
            <strong>POST /api/analyze</strong> - Analyze a ticker
        </div>
        <div class="endpoint">
            <strong>GET /api/watchlist</strong> - Get watchlist
        </div>
        <div class="endpoint">
            <strong>POST /api/watchlist/{ticker}</strong> - Add to watchlist
        </div>
        <div class="endpoint">
            <strong>GET /api/history</strong> - Get analysis history
        </div>
        <div class="endpoint">
            <strong>GET /docs</strong> - Interactive API documentation
        </div>

        <p>WebSocket: <code>ws://localhost:8000/ws/analysis</code></p>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Quick health check"""
    from src.health import HealthCheck

    start_request()
    logger.info("health_check_requested")

    ollama_ok, ollama_msg = HealthCheck.check_ollama_running()
    model_ok, model_msg = HealthCheck.check_model_downloaded(settings.ollama_model)

    status = "healthy" if (ollama_ok and model_ok) else "degraded"

    return HealthResponse(
        status=status,
        ollama={"ok": ollama_ok, "message": ollama_msg},
        model={"ok": model_ok, "message": model_msg},
        timestamp=datetime.now().isoformat(),
    )


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_ticker(request: AnalysisRequest):
    """
    Run full analysis on a ticker.

    This is the main endpoint that orchestrates all MCP tool calls
    and LLM reasoning to produce a comprehensive analysis.
    """
    start_request()
    logger.info("analyze_endpoint_called", ticker=request.ticker)

    try:
        result = await run_analysis_task(request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "analysis_failed",
            ticker=request.ticker,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/watchlist")
async def get_watchlist():
    """Get user's watchlist"""
    start_request()
    logger.info("watchlist_requested", count=len(session.watchlist))

    return {"watchlist": session.watchlist}


@app.post("/api/watchlist/{ticker}")
async def add_to_watchlist(ticker: str):
    """Add ticker to watchlist"""
    session.add_to_watchlist(ticker)
    return {"status": "added", "ticker": ticker.upper()}


@app.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str):
    """Remove ticker from watchlist"""
    session.remove_from_watchlist(ticker)
    return {"status": "removed", "ticker": ticker.upper()}


# --- Portfolio Endpoints ---


@app.post("/api/portfolio/unlock")
async def unlock_portfolio(password: str = Body(..., embed=True)):
    """Unlock the portfolio session"""
    success = session.portfolio_manager.unlock(password)
    if success:
        return {"status": "unlocked"}
    raise HTTPException(status_code=401, detail="Invalid password")


@app.post("/api/portfolio/lock")
async def lock_portfolio():
    """Lock the portfolio session"""
    session.portfolio_manager.lock()
    return {"status": "locked"}


@app.post("/api/portfolio/wipe")
async def wipe_portfolio():
    """Wipe all portfolio data"""
    session.portfolio_manager.wipe()
    return {"status": "wiped"}


@app.get("/api/portfolio")
async def get_portfolio():
    """Get portfolio holdings"""
    if not session.portfolio_manager.is_unlocked():
        raise HTTPException(status_code=401, detail="Portfolio locked")
    holdings = session.portfolio_manager.load()
    return {"holdings": holdings}


@app.post("/api/portfolio")
async def add_portfolio_item(item: PortfolioItem):
    """Add or update portfolio holding"""
    if not session.portfolio_manager.is_unlocked():
        raise HTTPException(status_code=401, detail="Portfolio locked")

    holdings = session.portfolio_manager.load()
    # Replace if exists, else append
    holdings = [h for h in holdings if h.ticker != item.ticker.upper()]
    holdings.append(item)
    session.portfolio_manager.save(holdings)
    return {"status": "saved", "ticker": item.ticker}


@app.delete("/api/portfolio/{ticker}")
async def remove_portfolio_item(ticker: str):
    """Remove portfolio holding"""
    if not session.portfolio_manager.is_unlocked():
        raise HTTPException(status_code=401, detail="Portfolio locked")

    holdings = session.portfolio_manager.load()
    holdings = [h for h in holdings if h.ticker != ticker.upper()]
    session.portfolio_manager.save(holdings)
    return {"status": "removed", "ticker": ticker.upper()}


@app.get("/api/history")
async def get_analysis_history():
    """Get recent analysis history"""
    start_request()
    logger.info("history_requested", count=len(session.analysis_history))

    return {
        "history": [
            {
                "ticker": analysis.ticker,
                "timestamp": analysis.timestamp.isoformat(),
                "risk_score": analysis.risk_score,
                "price": analysis.market_snapshot.get("current_price"),
            }
            for analysis in session.analysis_history
        ]
    }


@app.get("/api/export/{ticker}")
async def export_analysis(ticker: str, format: str = "json"):
    """
    Export analysis to file.

    Formats: json, markdown
    """
    start_request()
    ticker = ticker.upper()
    analysis = session.get_analysis(ticker)

    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found for ticker")

    logger.info("export_requested", ticker=ticker, format=format)

    if format == "json":
        return JSONResponse(content=analysis.dict())

    elif format == "markdown":
        md = f"""# Analysis Report: {analysis.ticker}

**Generated:** {analysis.timestamp.strftime('%Y-%m-%d %H:%M:%S')}

## Market Snapshot

- **Price:** ${analysis.market_snapshot.get('price', 0):.2f}
- **Volume:** {analysis.market_snapshot.get('volume', 0):,}
- **Volatility:** {analysis.market_snapshot.get('volatility_52week', 0) * 100:.1f}%

## Risk Score

**{analysis.risk_score:.0f}/100** - {'High Risk' if analysis.risk_score > 70 else 'Medium Risk' if analysis.risk_score > 30 else 'Low Risk'}

## AI Analysis

{analysis.ai_analysis}

---
*Generated by Quant-Ollama v0.2.0*
"""
        return PlainTextResponse(content=md, media_type="text/markdown")

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")


# WebSocket endpoint
@app.websocket("/ws/analysis")
async def websocket_analysis(websocket: WebSocket):
    """
    WebSocket endpoint for streaming analysis updates.

    Sends progress updates as the agent works.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            ticker = data.get("ticker")

            if not ticker:
                await ws_manager.send_personal_message(
                    {"type": "error", "message": "No ticker provided"}, websocket
                )
                continue

            start_request()
            logger.info("websocket_analysis_requested", ticker=ticker)

            # Send status updates
            await ws_manager.send_personal_message(
                {"type": "status", "message": f"Starting analysis for {ticker}..."},
                websocket,
            )

            try:
                # Run analysis
                request = AnalysisRequest(
                    ticker=ticker,
                    include_news=True,
                    include_sentiment=True,
                    include_fundamentals=True,
                    max_news=5,
                )
                result = await run_analysis_task(request)

                # Send complete result
                await ws_manager.send_personal_message(
                    {"type": "complete", "result": result.dict()}, websocket
                )

            except Exception as e:
                logger.error("websocket_analysis_error", error=str(e))
                await ws_manager.send_personal_message(
                    {"type": "error", "message": str(e)}, websocket
                )

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error("websocket_error", error=str(e), exc_info=True)
        ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
