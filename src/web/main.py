# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""
FastAPI web application for MCPFolio.

Provides REST API and WebSocket endpoints for financial analysis.
"""

import asyncio
import base64
import json
import os
import re
import uuid
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
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.config import get_settings
from src.logging_config import get_logger, start_request
from src.persistence import ThesisStore
from src.prompts import (
    COMPARISON_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    format_comparison_context,
    format_single_context,
    parse_llm_output,
)
from src.startup import quick_startup, shutdown

logger = get_logger(__name__)
settings = get_settings()


# Pydantic Models
class AnalysisRequest(BaseModel):
    """Request for stock analysis"""

    ticker: str = Field(..., description="Stock ticker symbol", min_length=1, max_length=20)
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


class AnalysisResponse(BaseModel):
    """Complete analysis response"""

    ticker: str
    timestamp: datetime
    market_snapshot: dict
    sentiment: list[dict] | None = None
    news: list[dict] | None = None
    ai_analysis: str
    risk_score: float = Field(..., ge=0, le=100, description="Formula-based risk score 0-100")
    recommendation: str | None = None
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="LLM confidence 0-1")
    key_risk: str | None = None
    fair_value: float | None = None


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


class ComparisonRequest(BaseModel):
    """Request for side-by-side ticker comparison"""

    ticker_a: str = Field(..., description="First ticker symbol", min_length=1, max_length=10)
    ticker_b: str = Field(..., description="Second ticker symbol", min_length=1, max_length=10)
    include_news: bool = Field(True, description="Include news analysis")
    include_sentiment: bool = Field(True, description="Include sentiment data")


class ComparisonResponse(BaseModel):
    """Side-by-side ticker comparison response"""

    ticker_a: str
    ticker_b: str
    timestamp: datetime
    data_a: dict
    data_b: dict
    sentiment_a: list[dict] | None = None
    sentiment_b: list[dict] | None = None
    news_a: list[dict] | None = None
    news_b: list[dict] | None = None
    ai_analysis: str
    verdict: str  # ticker_a value, ticker_b value, or "EQUAL"


class MarketRegionData(BaseModel):
    name: str
    change_pct: float
    weight: float


class MarketStateResponse(BaseModel):
    regions: list[MarketRegionData]
    vix: float | None = None
    overall_change_pct: float | None = None
    market_regime: str = "Unknown"
    treasury_10y: float | None = None


class FluidTickerData(BaseModel):
    """Per-ticker metrics for the Market Fluid simulation"""

    ticker: str
    price_change_pct: float
    volume_ratio: float
    volatility_52w: float
    market_cap: float
    pl_pct: float | None = None  # portfolio scope only


class FluidDataResponse(BaseModel):
    """Response for /api/fluid/data"""

    scope: str
    tickers: list[FluidTickerData]


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
        self.thesis_store = ThesisStore(self.data_dir)
        self.analysis_history: list[AnalysisResponse] = []
        self.max_history = 50

        # Advisor graph state
        self.advisor_graph = None  # CompiledGraph, lazy-initialized
        self.advisor_thread_id: str = "advisor-web"

        # Load from disk
        self._load_watchlist()

        logger.info("session_manager_initialized", max_history=self.max_history)

    def _load_watchlist(self):
        """Load watchlist from disk"""
        try:
            if self.watchlist_path.exists():
                with self.watchlist_path.open() as f:
                    data = json.load(f)
                    self.watchlist = [WatchlistItem(**item) for item in data]
                logger.info("watchlist_loaded_from_disk", count=len(self.watchlist))
        except Exception as e:
            logger.error("watchlist_load_error", error=str(e))

    def _save_watchlist(self):
        """Save watchlist to disk"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with self.watchlist_path.open("w") as f:
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

        # Persist to encrypted thesis store if unlocked
        if self.thesis_store.is_unlocked():
            try:
                self.thesis_store.save(analysis)
            except Exception as e:
                logger.error("thesis_save_failed", ticker=analysis.ticker, error=str(e))

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
        version="0.2.1",
    )

    yield

    # Shutdown
    logger.info("application_shutting_down")
    await shutdown()
    logger.info("application_shutdown_complete")


# Create FastAPI app
app = FastAPI(
    title="MCPFolio API",
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

    # Locate tools
    market_snapshot_tool = tool_map.get("get_market_snapshot")
    if not market_snapshot_tool:
        raise HTTPException(status_code=500, detail="Market snapshot tool not available")

    sentiment_tool = tool_map.get("get_sentiment_data") if request.include_sentiment else None
    news_tool = tool_map.get("get_news") if request.include_news else None

    async def _noop():
        return None

    # Fetch market data, sentiment, and news in parallel
    _gather_results: tuple[Any, Any, Any] = await asyncio.gather(
        market_snapshot_tool.ainvoke({"ticker": request.ticker}),
        sentiment_tool.ainvoke({"ticker": request.ticker}) if sentiment_tool else _noop(),
        (
            news_tool.ainvoke({"ticker": request.ticker, "count": request.max_news})
            if news_tool
            else _noop()
        ),
        return_exceptions=True,
    )
    raw_market_data: Any
    raw_sentiment: Any
    raw_news: Any
    raw_market_data, raw_sentiment, raw_news = _gather_results

    market_data = (
        parse_tool_result(raw_market_data)
        if not isinstance(raw_market_data, Exception)
        else {"error": str(raw_market_data)}
    )

    if market_data.get("error") or isinstance(raw_market_data, Exception):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to get market data: {market_data.get('message', market_data.get('error', 'Unknown error'))}",
        )

    # Parse sentiment
    sentiment_data = None
    if sentiment_tool and raw_sentiment is not None and not isinstance(raw_sentiment, Exception):
        sentiment_result = parse_tool_result(raw_sentiment)
        if not sentiment_result.get("error"):
            sentiment_data = sentiment_result.get("ratings", [])

    # Parse news
    news_data = None
    if news_tool and raw_news is not None and not isinstance(raw_news, Exception):
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

    # --- AI Analysis ---
    from langchain_ollama import ChatOllama

    ollama_config = settings.get_ollama_config()
    ollama_config["temperature"] = 0.1
    llm = ChatOllama(**ollama_config)

    # Build structured context string using shared formatter
    context = format_single_context(request.ticker.upper(), market_data, sentiment_data, news_data)

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
        ai_analysis = str(llm_response.content)
        logger.info("ai_synthesis_complete", ticker=request.ticker)
    except Exception as e:
        logger.error("ai_synthesis_failed", error=str(e))
        ai_analysis = f"Error generating robust AI analysis: {str(e)}\n\nFallback: {ai_analysis}"

    structured = parse_llm_output(ai_analysis)

    # Strip the structured header block from the display text — keep only the ## narrative
    _parts = re.split(r"(?=^##\s)", ai_analysis, maxsplit=1, flags=re.MULTILINE)
    display_analysis = _parts[-1].strip() if len(_parts) > 1 else ai_analysis

    response = AnalysisResponse(
        ticker=request.ticker.upper(),
        timestamp=datetime.now(),
        market_snapshot=market_data,
        sentiment=sentiment_data,
        news=news_data,
        ai_analysis=display_analysis,
        risk_score=risk_score,
        recommendation=structured["recommendation"],
        confidence=structured["confidence"],
        key_risk=structured["key_risk"],
        fair_value=structured["fair_value"],
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
        recommendation=structured["recommendation"],
        confidence=structured["confidence"],
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
            import platform

            if platform.system() == "Windows":
                subprocess.run(["taskkill", "/F", "/IM", "ollama.exe"], check=False)  # nosec
            else:
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
        <title>MCPFolio API</title>
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
        <h1>🤖 MCPFolio API</h1>
        <p>Local-first financial analyst API v0.2.0</p>

        <h2>Available Endpoints:</h2>
        <div class="endpoint">
            <strong>GET /api/health</strong> - Health check
        </div>
        <div class="endpoint">
            <strong>POST /api/analyze</strong> - Analyze a ticker
        </div>
        <div class="endpoint">
            <strong>POST /api/compare</strong> - Compare two tickers side-by-side
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


@app.post("/api/compare", response_model=ComparisonResponse)
async def compare_tickers(request: ComparisonRequest):
    """
    Run side-by-side comparison of two tickers.

    Fetches data for both tickers in parallel (6 concurrent MCP calls),
    then asks the LLM to produce a structured comparison with a verdict.
    """
    from langchain_ollama import ChatOllama

    from src.tools.lazy_loader import get_mcp_tools

    start_request()
    ticker_a = request.ticker_a.upper()
    ticker_b = request.ticker_b.upper()
    logger.info("compare_endpoint_called", ticker_a=ticker_a, ticker_b=ticker_b)

    tools = await get_mcp_tools()
    tool_map = {tool.name: tool for tool in tools}

    market_tool = tool_map.get("get_market_snapshot")
    if not market_tool:
        raise HTTPException(status_code=500, detail="Market snapshot tool not available")

    sentiment_tool = tool_map.get("get_sentiment_data") if request.include_sentiment else None
    news_tool = tool_map.get("get_news") if request.include_news else None

    async def _noop():
        return None

    # 6 parallel MCP calls (3 per ticker)
    results = await asyncio.gather(
        market_tool.ainvoke({"ticker": ticker_a}),
        market_tool.ainvoke({"ticker": ticker_b}),
        sentiment_tool.ainvoke({"ticker": ticker_a}) if sentiment_tool else _noop(),
        sentiment_tool.ainvoke({"ticker": ticker_b}) if sentiment_tool else _noop(),
        news_tool.ainvoke({"ticker": ticker_a, "count": 5}) if news_tool else _noop(),
        news_tool.ainvoke({"ticker": ticker_b, "count": 5}) if news_tool else _noop(),
        return_exceptions=True,
    )
    raw_market_a, raw_market_b, raw_sent_a, raw_sent_b, raw_news_a, raw_news_b = results

    def _safe_market(raw) -> dict:
        return parse_tool_result(raw) if not isinstance(raw, Exception) else {"error": str(raw)}

    def _safe_ratings(raw: Any) -> list[dict] | None:
        if raw is None or isinstance(raw, Exception):
            return None
        r = parse_tool_result(raw)
        if r.get("error"):
            return None
        return cast(list[dict], r["ratings"]) if "ratings" in r else None

    def _safe_news(raw: Any) -> list[dict] | None:
        if raw is None or isinstance(raw, Exception):
            return None
        r = parse_tool_result(raw)
        if r.get("error"):
            return None
        return cast(list[dict], r["news"]) if "news" in r else None

    data_a = _safe_market(raw_market_a)
    data_b = _safe_market(raw_market_b)

    if data_a.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to get market data for {ticker_a}: {data_a.get('error')}",
        )
    if data_b.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"Failed to get market data for {ticker_b}: {data_b.get('error')}",
        )

    sentiment_a = _safe_ratings(raw_sent_a)
    sentiment_b = _safe_ratings(raw_sent_b)
    news_a = _safe_news(raw_news_a)
    news_b = _safe_news(raw_news_b)

    # Build side-by-side context using shared formatter
    context = format_comparison_context(
        ticker_a,
        data_a,
        sentiment_a,
        news_a,
        ticker_b,
        data_b,
        sentiment_b,
        news_b,
    )

    # LLM comparison
    ollama_config = settings.get_ollama_config()
    ollama_config["temperature"] = 0.1
    llm = ChatOllama(**ollama_config)

    logger.info("comparison_synthesis_started", ticker_a=ticker_a, ticker_b=ticker_b)
    try:
        llm_response = await llm.ainvoke(
            [
                ("system", COMPARISON_SYSTEM_PROMPT),
                ("user", f"Compare {ticker_a} vs {ticker_b}:\n{context}"),
            ]
        )
        ai_analysis = str(llm_response.content)
        logger.info("comparison_synthesis_complete", ticker_a=ticker_a, ticker_b=ticker_b)
    except Exception as e:
        logger.error("comparison_synthesis_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"LLM comparison failed: {str(e)}")

    # Extract verdict from the COMPARISON: line
    verdict = "EQUAL"
    for line in ai_analysis.split("\n"):
        if line.strip().upper().startswith("COMPARISON:"):
            val = line.split(":", 1)[1].strip().upper()
            if ticker_a in val:
                verdict = ticker_a
            elif ticker_b in val:
                verdict = ticker_b
            break

    return ComparisonResponse(
        ticker_a=ticker_a,
        ticker_b=ticker_b,
        timestamp=datetime.now(),
        data_a=data_a,
        data_b=data_b,
        sentiment_a=sentiment_a,
        sentiment_b=sentiment_b,
        news_a=news_a,
        news_b=news_b,
        ai_analysis=ai_analysis,
        verdict=verdict,
    )


@app.get("/api/watchlist")
async def get_watchlist():
    """Get user's watchlist"""
    start_request()
    logger.info("watchlist_requested", count=len(session.watchlist))

    return {"watchlist": session.watchlist}


@app.post("/api/watchlist/refresh")
async def refresh_watchlist_prices():
    """Fetch current prices for all watchlist tickers in parallel.

    Called on dashboard startup so every watchlist item shows a price
    without requiring a full analysis to have been run first.
    """
    import yfinance as yf

    if not session.watchlist:
        return {"watchlist": session.watchlist, "updated": 0}

    async def _fetch_price(ticker: str) -> tuple[str, float | None]:
        def _get_info() -> dict:
            return dict(yf.Ticker(ticker).info)

        try:
            info = await asyncio.to_thread(_get_info)
            price = (
                info.get("currentPrice")
                or info.get("regularMarketPrice")
                or info.get("navPrice")
                or info.get("previousClose")
            )
            return ticker, float(price) if price else None
        except Exception:
            return ticker, None

    results = await asyncio.gather(
        *[_fetch_price(w.ticker) for w in session.watchlist],
        return_exceptions=True,
    )

    updated = 0
    for result in results:
        if isinstance(result, tuple):
            ticker, price = result
            if price is not None:
                session.update_watchlist_price(ticker, price)
                updated += 1

    session._save_watchlist()
    logger.info("watchlist_prices_refreshed", updated=updated, total=len(session.watchlist))
    return {"watchlist": session.watchlist, "updated": updated}


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
    """Unlock the portfolio session (also unlocks thesis history)"""
    success = session.portfolio_manager.unlock(password)
    if success:
        session.thesis_store.unlock(password)
        return {"status": "unlocked"}
    raise HTTPException(status_code=401, detail="Invalid password")


@app.post("/api/portfolio/lock")
async def lock_portfolio():
    """Lock the portfolio session (also locks thesis history)"""
    session.portfolio_manager.lock()
    session.thesis_store.lock()
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


@app.get("/api/thesis")
async def get_thesis_history():
    """Get recent thesis history across all tickers (requires portfolio unlock)"""
    if not session.thesis_store.is_unlocked():
        raise HTTPException(status_code=401, detail="Portfolio locked")
    return {"thesis": session.thesis_store.get_recent(200)}


@app.get("/api/thesis/{ticker}")
async def get_thesis_for_ticker(ticker: str):
    """Get thesis history for a single ticker (requires portfolio unlock)"""
    if not session.thesis_store.is_unlocked():
        raise HTTPException(status_code=401, detail="Portfolio locked")
    return {"thesis": session.thesis_store.get_history(ticker.upper(), 50)}


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
*Generated by MCPFolio v0.2.1*
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


@app.websocket("/ws/advisor")
async def websocket_advisor(websocket: WebSocket):
    """
    WebSocket endpoint for the AI advisor chat.

    Streams LangGraph events in real time: LLM tokens and tool calls.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()

            # ── Clear conversation ──
            if data.get("action") == "clear":
                session.advisor_thread_id = str(uuid.uuid4())
                session.advisor_graph = None  # force graph re-init with fresh thread
                await websocket.send_json({"type": "cleared"})
                continue

            user_text = (data.get("message") or "").strip()
            if not user_text:
                continue

            # ── Lazy-init advisor graph ──
            if session.advisor_graph is None:
                logger.info("advisor_graph_initializing")
                try:
                    from langchain_ollama import ChatOllama

                    from src.graph.advisor import build_advisor_graph
                    from src.tools.lazy_loader import get_mcp_tools

                    tools = await get_mcp_tools()
                    tools_by_name = {t.name: t for t in tools}
                    ollama_config = {
                        **settings.get_ollama_config(),
                        "temperature": 0.5,  # Balanced temp for conversational advisor with accurate tool calling
                        "num_predict": 2048,  # Allow longer responses (default is ~512)
                    }
                    llm = ChatOllama(**ollama_config)
                    session.advisor_graph = build_advisor_graph(llm, tools, tools_by_name)
                    logger.info("advisor_graph_initialized", tools_count=len(tools))
                except Exception as e:
                    logger.error("advisor_graph_init_failed", error=str(e), exc_info=True)
                    await websocket.send_json(
                        {"type": "error", "message": f"Failed to initialize advisor: {str(e)}"}
                    )
                    continue

            # ── Optional portfolio context (fresh each turn) ──
            input_messages = []
            if session.portfolio_manager.is_unlocked():
                holdings = session.portfolio_manager.load()
                if holdings:
                    summary = "User's current portfolio: " + ", ".join(
                        f"{h.ticker} ({h.quantity} shares @ ${h.cost_basis}/share)"
                        for h in holdings
                    )
                    input_messages.append(SystemMessage(content=summary))
            input_messages.append(HumanMessage(content=user_text))

            config = {"configurable": {"thread_id": session.advisor_thread_id}}

            # ── Stream events ──
            try:
                # Track active tools to buffer response until tools complete
                active_tools = set()
                buffered_tokens: list[str] = []

                async for event in session.advisor_graph.astream_events(
                    {"messages": input_messages}, config=config, version="v2"
                ):
                    kind = event["event"]
                    node = event.get("metadata", {}).get("langgraph_node", "")

                    # Track tool lifecycle
                    if kind == "on_tool_start":
                        # Use run_id for unique tracking if available, fallback to name
                        tool_id = event.get("run_id") or event.get("name", "")
                        tool_name = event.get("name", "")
                        active_tools.add(tool_id)
                        # Extract tool input, handling non-serializable objects
                        tool_input = event["data"].get("input", {})
                        # Convert to JSON-safe format
                        try:
                            json.dumps(tool_input)
                        except (TypeError, ValueError):
                            if isinstance(tool_input, dict):
                                tool_input = {k: str(v) for k, v in tool_input.items()}
                            else:
                                tool_input = {"raw": str(tool_input)}

                        await websocket.send_json(
                            {
                                "type": "tool_start",
                                "tool": tool_name,
                                "input": tool_input,
                            }
                        )

                    elif kind == "on_tool_end":
                        tool_id = event.get("run_id") or event.get("name", "")
                        tool_name = event.get("name", "")
                        active_tools.discard(tool_id)
                        await websocket.send_json({"type": "tool_end", "tool": tool_name})

                        # If all tools are done, flush buffered tokens
                        if not active_tools and buffered_tokens:
                            for token in buffered_tokens:
                                await websocket.send_json({"type": "token", "content": token})
                            buffered_tokens = []

                    # Buffer or send tokens based on tool state
                    if kind == "on_chat_model_stream" and node == "agent":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            if active_tools:
                                # Tools still running - buffer the token
                                buffered_tokens.append(chunk.content)
                            else:
                                # No active tools - send immediately
                                await websocket.send_json(
                                    {"type": "token", "content": chunk.content}
                                )

                # Close any remaining thinking blocks that didn't get on_tool_end
                for tool_name in list(active_tools):
                    await websocket.send_json({"type": "tool_end", "tool": tool_name})
                active_tools.clear()

                # Flush any tokens that were buffered while tools were active
                if buffered_tokens:
                    for token in buffered_tokens:
                        await websocket.send_json({"type": "token", "content": token})
                    buffered_tokens.clear()

                await websocket.send_json({"type": "done"})

            except Exception as e:
                logger.error("advisor_stream_error", error=str(e))
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.get("/api/fluid/data", response_model=FluidDataResponse)
async def get_fluid_data(scope: str = "market"):
    """
    Lightweight financial metrics for the Market Fluid simulation.

    scope="market"    → watchlist tickers or defaults (SPY, QQQ, NVDA, AAPL, BTC-USD)
    scope="portfolio" → portfolio holdings (401 if locked); includes P/L %
    """
    import yfinance as yf

    DEFAULTS = ["SPY", "QQQ", "NVDA", "AAPL", "BTC-USD"]

    if scope == "portfolio":
        if not session.portfolio_manager.is_unlocked():
            raise HTTPException(status_code=401, detail="Portfolio locked")
        holdings = session.portfolio_manager.load()
        tickers = [h.ticker for h in holdings]
        cost_basis_map = {h.ticker: h.cost_basis for h in holdings}
    else:
        watchlist_tickers = [w.ticker for w in session.watchlist]
        tickers = watchlist_tickers if watchlist_tickers else DEFAULTS
        cost_basis_map = {}

    async def _fetch_ticker(ticker: str) -> FluidTickerData | None:
        cost_basis = cost_basis_map.get(ticker)

        def _get() -> FluidTickerData:
            t = yf.Ticker(ticker)
            fi = t.fast_info

            last = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None) or 0.0
            prev = getattr(fi, "previous_close", None) or last
            change = ((float(last) - float(prev)) / float(prev) * 100) if prev else 0.0

            avg_vol = float(getattr(fi, "three_month_average_volume", None) or 1)
            curr_vol = float(getattr(fi, "regular_market_volume", None) or avg_vol)
            vol_ratio = curr_vol / avg_vol if avg_vol > 0 else 1.0

            hi = getattr(fi, "year_high", None) or getattr(fi, "fifty_two_week_high", None) or last
            lo = getattr(fi, "year_low", None) or getattr(fi, "fifty_two_week_low", None) or last
            mid = ((float(hi) + float(lo)) / 2) if (hi and lo) else (float(last) or 1.0)
            vol_52w = abs(float(hi) - float(lo)) / mid if mid > 0 else 0.2

            mkt_cap = float(getattr(fi, "market_cap", None) or 1e9)

            pl: float | None = None
            if cost_basis and last:
                pl = (float(last) - float(cost_basis)) / float(cost_basis) * 100

            return FluidTickerData(
                ticker=ticker,
                price_change_pct=round(change, 4),
                volume_ratio=round(vol_ratio, 4),
                volatility_52w=round(vol_52w, 4),
                market_cap=mkt_cap,
                pl_pct=round(pl, 4) if pl is not None else None,
            )

        try:
            return await asyncio.to_thread(_get)
        except Exception as e:
            logger.warning("fluid_data_fetch_error", ticker=ticker, error=str(e))
            return None

    results = await asyncio.gather(
        *[_fetch_ticker(t) for t in tickers],
        return_exceptions=True,
    )
    fluid_tickers = [r for r in results if isinstance(r, FluidTickerData)]
    return FluidDataResponse(scope=scope, tickers=fluid_tickers)


@app.get("/api/market/state", response_model=MarketStateResponse)
async def get_market_state():
    """World market state for the splash screen fluid simulation."""
    import yfinance as yf

    INDICES = [
        ("^GSPC", "Americas", 0.40),
        ("^IXIC", "Americas", 0.20),
        ("^FTSE", "Europe", 0.15),
        ("^GDAXI", "Europe", 0.10),
        ("^N225", "Asia", 0.10),
        ("^HSI", "Asia", 0.05),
        ("GC=F", "Commodities", 0.50),
        ("CL=F", "Commodities", 0.50),
        ("BTC-USD", "Crypto", 1.00),
    ]
    VIX_TICKER = "^VIX"
    TREASURY_TICKER = "^TNX"

    def _fetch_change(ticker: str) -> float | None:
        try:
            fi = yf.Ticker(ticker).fast_info
            last = getattr(fi, "last_price", None) or getattr(fi, "previous_close", None)
            prev = getattr(fi, "previous_close", None)
            if last and prev and prev != 0:
                return (float(last) - float(prev)) / float(prev) * 100
        except Exception:
            pass
        return None

    def _fetch_level(ticker: str) -> float | None:
        try:
            fi = yf.Ticker(ticker).fast_info
            price = getattr(fi, "last_price", None)
            return float(price) if price is not None else None
        except Exception:
            return None

    all_tickers = [t for t, _, _ in INDICES] + [VIX_TICKER, TREASURY_TICKER]
    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                _fetch_change if t not in (VIX_TICKER, TREASURY_TICKER) else _fetch_level, t
            )
            for t in all_tickers
        ],
        return_exceptions=True,
    )

    idx_results: dict[str, float | None] = {}
    for t, v in zip(all_tickers, results, strict=False):
        idx_results[t] = v if isinstance(v, float | int) else None

    vix = idx_results.get(VIX_TICKER)
    treasury = idx_results.get(TREASURY_TICKER)

    region_buckets: dict[str, list[tuple[float, float]]] = {}
    for ticker, region, weight in INDICES:
        chg = idx_results.get(ticker)
        if chg is not None:
            region_buckets.setdefault(region, []).append((chg, weight))

    REGION_WEIGHTS = {
        "Americas": 0.45,
        "Europe": 0.25,
        "Asia": 0.20,
        "Commodities": 0.05,
        "Crypto": 0.05,
    }
    regions = []
    weighted_sum = 0.0
    total_weight = 0.0
    for region_name, pairs in region_buckets.items():
        total_w = sum(w for _, w in pairs)
        region_chg = sum(c * w for c, w in pairs) / total_w if total_w else 0
        regions.append(
            MarketRegionData(
                name=region_name,
                change_pct=round(region_chg, 3),
                weight=REGION_WEIGHTS.get(region_name, 0.1),
            )
        )
        rw = REGION_WEIGHTS.get(region_name, 0.1)
        weighted_sum += region_chg * rw
        total_weight += rw

    overall = round(weighted_sum / total_weight, 3) if total_weight else None

    if vix is not None and vix > 25:
        regime = "High Volatility"
    elif overall is not None and overall > 0.5:
        regime = "Bull"
    elif overall is not None and overall < -0.5:
        regime = "Bear"
    elif overall is not None:
        regime = "Mixed"
    else:
        regime = "Unknown"  # no live data (markets closed / rate-limited)

    return MarketStateResponse(
        regions=regions,
        vix=round(vix, 2) if vix else None,
        overall_change_pct=overall,
        market_regime=regime,
        treasury_10y=round(float(treasury), 3) if treasury else None,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
