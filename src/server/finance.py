# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""MCP Financial Server - Provides market data tools via stdio transport."""

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from cachetools import TTLCache  # type: ignore[import-untyped]
from fastmcp import FastMCP

# Add parent directory to path to import logging_config
sys.path.insert(0, str(Path(__file__).parent.parent))
import contextlib

from logging_config import get_logger
from tools.wrappers import circuit_breaker, with_retry

logger = get_logger(__name__)
mcp = FastMCP("finance-server")

# 15-minute TTL caches for the two most-called tools.
# Prevents redundant yfinance round-trips during multi-ticker comparisons and
# watchlist refreshes without storing stale data for longer than one trading session.
_SNAPSHOT_CACHE: TTLCache = TTLCache(maxsize=200, ttl=900)
_SENTIMENT_CACHE: TTLCache = TTLCache(maxsize=200, ttl=900)


def _get_trend_data_logic(ticker: str, period: str = "1mo") -> dict:
    """Internal logic for fetching trend data."""
    start_time = time.time()
    ticker = ticker.strip().upper()
    logger.info("get_trend_data_called", ticker=ticker, period=period)

    try:
        stock = yf.Ticker(ticker)
        # Use 1d interval for trends
        hist = stock.history(period=period, interval="1d")

        if hist.empty:
            return {"error": "No trend data available", "ticker": ticker, "error_type": "no_data"}

        # Format for Chart.js: list of {date, price}
        points = []
        for dt, row in hist.iterrows():
            points.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "price": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
            )

        # Pre-compute summary stats so the LLM can read them directly
        # without processing the full points array
        prices = [p["price"] for p in points]
        pct_change = round((prices[-1] - prices[0]) / prices[0] * 100, 2) if prices[0] else 0
        summary = {
            "start_date": points[0]["date"],
            "start_price": prices[0],
            "end_date": points[-1]["date"],
            "end_price": prices[-1],
            "pct_change": pct_change,
            "trend": "upward" if pct_change > 2 else "downward" if pct_change < -2 else "flat",
            "period_high": max(prices),
            "period_low": min(prices),
        }

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_trend_data_success",
            ticker=ticker,
            points=len(points),
            duration_ms=round(duration_ms, 2),
        )

        return {
            "ticker": ticker,
            "period": period,
            "summary": summary,
            "points": points,
            "count": len(points),
        }
    except Exception as e:
        logger.error("get_trend_data_failed", ticker=ticker, error=str(e), exc_info=True)
        return {"error": str(e), "ticker": ticker, "error_type": "unknown"}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_trend_data(ticker: str, period: str = "1mo") -> dict:
    """Fetches historical price trend data for analyzing growth, declines, and volatility patterns.

    Valid periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max

    Use this to:
    - Identify long-term growth trends (1y, 5y, max)
    - Analyze recent volatility (1mo, 3mo)
    - Compare year-to-date performance (ytd)
    - Assess recovery from drawdowns (max for full history)

    Returns daily close prices and volume for the period.
    """
    # Handle None being passed explicitly
    if period is None:
        period = "1mo"
    return _get_trend_data_logic(ticker, period)


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_market_snapshot(ticker: str) -> dict:
    """Fetches a market snapshot for a given stock ticker.

    This function retrieves current price, volume, 52-week high/low, volatility,
    upcoming calendar events, analyst price targets, and quarterly income
    statements using the yfinance library.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'AAPL').

    Returns:
        dict: A dictionary containing market data with consistent error structure.
            On success:
            {
                "ticker": str,
                "current_price": float | None,
                "volume": int | None,
                "high_52_week": float,
                "low_52_week": float,
                "volatility_52_week_pct": float,
                "market_cap": int | None,
                "pe_ratio": float | None,
                "dividend_yield": float | None,
                "calendar": dict | None,
                "analyst_targets": dict | None,
                "quarterly_income": list[dict] | None
            }
            On error:
            {
                "error": str,
                "ticker": str,
                "error_type": "invalid_ticker" | "no_data" | "rate_limit" | "unknown"
            }
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    logger.info("get_market_snapshot_called", ticker=ticker)

    if ticker in _SNAPSHOT_CACHE:
        logger.debug("get_market_snapshot_cache_hit", ticker=ticker)
        return dict(_SNAPSHOT_CACHE[ticker])

    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        # Validate ticker exists and has basic data
        if not info or len(info) <= 1 or "symbol" not in info:
            logger.warning(
                "invalid_ticker_detected", ticker=ticker, info_length=len(info) if info else 0
            )
            return {
                "error": f"Invalid or delisted ticker: {ticker}",
                "ticker": ticker,
                "error_type": "invalid_ticker",
            }

        # Fetch 52-week historical data (1 year + buffer)
        hist = stock.history(period="1y")

        if hist.empty:
            logger.warning("no_historical_data", ticker=ticker)
            return {
                "error": f"No historical data available for {ticker}",
                "ticker": ticker,
                "error_type": "no_data",
            }

        # Calculate 52-week metrics
        high_52w = float(hist["High"].max())
        low_52w = float(hist["Low"].min())
        volatility = ((high_52w - low_52w) / low_52w) * 100 if low_52w > 0 else 0.0

        # Fetch additional data with safe extraction
        price = (
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("navPrice")
            or info.get("previousClose")
        )

        volume = info.get("volume") or info.get("regularMarketVolume")

        # Calendar events - simplify to dict only
        calendar_data = None
        try:
            cal = stock.calendar
            if cal is not None:
                if isinstance(cal, pd.DataFrame):
                    calendar_data = cal.to_dict(orient="index")
                elif isinstance(cal, dict):
                    calendar_data = {
                        k: str(v) if not isinstance(v, int | float | bool | type(None)) else v
                        for k, v in cal.items()
                    }
        except Exception:  # nosec
            calendar_data = None

        # Analyst price targets
        analyst_targets = None
        try:
            targets = stock.analyst_price_targets
            if targets is not None and isinstance(targets, dict):
                analyst_targets = {
                    k: float(v) if isinstance(v, int | float) else v for k, v in targets.items()
                }
        except Exception:  # nosec
            analyst_targets = None

        # Quarterly income statement
        quarterly_income_data = None
        try:
            quarterly_income = stock.quarterly_income_stmt
            if quarterly_income is not None and not quarterly_income.empty:
                # Convert to records and ensure JSON serializable
                quarterly_income_data = [
                    {
                        k: float(v) if isinstance(v, int | float) and pd.notna(v) else None
                        for k, v in row.items()
                    }
                    for row in quarterly_income.head(4).to_dict(orient="records")
                ]
        except Exception:  # nosec
            quarterly_income_data = None

        result = {
            "ticker": ticker,
            "quote_type": info.get("quoteType"),
            "current_price": float(price) if price else None,
            "volume": int(volume) if volume else None,
            "high_52_week": round(high_52w, 2),
            "low_52_week": round(low_52w, 2),
            "volatility_52_week_pct": round(volatility, 2),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield") or info.get("trailingAnnualDividendYield"),
            "calendar": calendar_data,
            "analyst_targets": analyst_targets,
            "quarterly_income": quarterly_income_data,
        }

        _SNAPSHOT_CACHE[ticker] = result
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_market_snapshot_success",
            ticker=ticker,
            price=result["current_price"],
            volatility=result["volatility_52_week_pct"],
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        error_type = "unknown"

        # Detect rate limiting
        if any(term in error_str.lower() for term in ["rate", "429", "too many requests"]):
            error_type = "rate_limit"
            error_str = "Rate limit exceeded. Please wait a few seconds and retry."

        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "get_market_snapshot_failed",
            ticker=ticker,
            error=error_str,
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            exc_info=True,
        )

        return {"error": error_str, "ticker": ticker, "error_type": error_type}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_sentiment_data(ticker: str, count: int = 5) -> dict:
    """Retrieves recent institutional analyst ratings for a ticker.

    Fetches the most recent analyst recommendations from yfinance.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'MSFT').
        count (int): Number of recent ratings to return (default: 5, max: 20).

    Returns:
        dict: A dictionary containing sentiment data with consistent error structure.
            On success:
            {
                "ticker": str,
                "ratings": list[dict],
                "count": int
            }
            Each rating has: 'period', 'strongBuy', 'buy', 'hold', 'sell', 'strongSell'

            On error:
            {
                "error": str,
                "ticker": str,
                "error_type": "no_data" | "rate_limit" | "unknown"
            }
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    count = max(1, min(count, 20))  # Clamp between 1 and 20
    logger.info("get_sentiment_data_called", ticker=ticker, count=count)

    cache_key = f"{ticker}:{count}"
    if cache_key in _SENTIMENT_CACHE:
        logger.debug("get_sentiment_data_cache_hit", ticker=ticker)
        return dict(_SENTIMENT_CACHE[cache_key])

    try:
        stock = yf.Ticker(ticker)
        recommendations = stock.recommendations

        if recommendations is None or recommendations.empty:
            logger.warning("no_analyst_ratings", ticker=ticker)
            return {
                "ticker": ticker,
                "ratings": [],
                "count": 0,
                "message": "No analyst ratings available for this ticker",
            }

        # Get the most recent ratings
        recent = recommendations.tail(count)

        # Convert to JSON-serializable format
        ratings_list = []
        for _, row in recent.iterrows():
            rating = {
                k: (str(v) if pd.notna(v) and not isinstance(v, int | float | bool) else v)
                for k, v in row.to_dict().items()
            }
            ratings_list.append(rating)

        result = {"ticker": ticker, "ratings": ratings_list, "count": len(ratings_list)}
        _SENTIMENT_CACHE[cache_key] = result

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_sentiment_data_success",
            ticker=ticker,
            ratings_count=len(ratings_list),
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        error_type = "unknown"

        if any(term in error_str.lower() for term in ["rate", "429", "too many requests"]):
            error_type = "rate_limit"
            error_str = "Rate limit exceeded. Please wait a few seconds and retry."

        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "get_sentiment_data_failed",
            ticker=ticker,
            error=error_str,
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            exc_info=True,
        )

        return {"error": error_str, "ticker": ticker, "error_type": error_type}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_news(ticker: str, count: int = 10, date: str | None = None) -> dict:
    """Fetches recent news articles for a given stock ticker.

    Retrieves news articles from yfinance with optional date filtering.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'GOOGL').
        count (int): Maximum number of articles to return (default: 10, max: 50).
        date (Optional[str]): Filter by date in 'YYYY-MM-DD' format.

    Returns:
        dict: A dictionary containing news articles with consistent error structure.
            On success:
            {
                "ticker": str,
                "news": list[dict],
                "count": int,
                "filtered_by_date": str | None
            }
            Each article contains:
            {
                "title": str,
                "publisher": str,
                "link": str,
                "published_date": str
            }

            On error:
            {
                "error": str,
                "ticker": str,
                "error_type": "no_data" | "rate_limit" | "invalid_date" | "unknown"
            }
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    count = max(1, min(count, 50))  # Clamp between 1 and 50
    logger.info("get_news_called", ticker=ticker, count=count, date_filter=date)

    # Validate date format if provided
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            logger.warning("invalid_date_format", ticker=ticker, date=date)
            return {
                "error": f"Invalid date format: {date}. Expected YYYY-MM-DD.",
                "ticker": ticker,
                "error_type": "invalid_date",
            }

    try:
        stock = yf.Ticker(ticker)

        # Try both methods to fetch news
        news = None
        try:
            news = stock.news
        except AttributeError:
            with contextlib.suppress(Exception):
                news = stock.get_news()

        if not news or len(news) == 0:
            logger.warning("no_news_available", ticker=ticker)
            return {
                "ticker": ticker,
                "news": [],
                "count": 0,
                "filtered_by_date": date,
                "message": "No news articles available for this ticker",
            }

        # Process and format news articles
        formatted_news = []
        for article in news:
            # Handle nested structure: yfinance now returns {id, content}
            content = article.get("content", article)

            # Extract title
            title = content.get("title", "Untitled")

            # Extract publisher (nested under provider)
            publisher = "Unknown"
            if "provider" in content:
                provider = content["provider"]
                if isinstance(provider, dict):
                    publisher = provider.get("displayName", "Unknown")
                elif isinstance(provider, str):
                    publisher = provider

            # Extract link (prefer canonicalUrl, fallback to clickThroughUrl)
            link = ""
            for url_key in ["canonicalUrl", "clickThroughUrl", "link"]:
                if url_key in content:
                    url_data = content[url_key]
                    if isinstance(url_data, dict):
                        link = url_data.get("url", "")
                    elif isinstance(url_data, str):
                        link = url_data
                    if link:
                        break

            # Parse date - try ISO format first (pubDate), then Unix timestamp (providerPublishTime)
            published_dt = None
            published_str = "Unknown"

            # Try ISO format date string (e.g., "2026-01-27T21:39:41Z")
            pub_date_str = content.get("pubDate") or content.get("displayTime")
            if pub_date_str:
                try:
                    # Handle ISO 8601 format with Z suffix
                    if pub_date_str.endswith("Z"):
                        pub_date_str = pub_date_str[:-1] + "+00:00"
                    published_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                    published_str = published_dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    pass

            # Fallback to Unix timestamp if available
            if not published_dt:
                pub_timestamp = content.get("providerPublishTime")
                if pub_timestamp:
                    try:
                        published_dt = datetime.fromtimestamp(pub_timestamp)
                        published_str = published_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except (ValueError, OSError):
                        pass

            # Apply date filter if specified
            if date and published_dt:
                article_date = published_dt.strftime("%Y-%m-%d")
                if article_date != date:
                    continue

            formatted_article = {
                "title": title,
                "publisher": publisher,
                "link": link,
                "published_date": published_str,
            }
            formatted_news.append(formatted_article)

            # Stop if we have enough articles
            if len(formatted_news) >= count:
                break

        result = {
            "ticker": ticker,
            "news": formatted_news,
            "count": len(formatted_news),
            "filtered_by_date": date,
        }

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_news_success",
            ticker=ticker,
            news_count=len(formatted_news),
            date_filter=date,
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        error_type = "unknown"

        if any(term in error_str.lower() for term in ["rate", "429", "too many requests"]):
            error_type = "rate_limit"
            error_str = "Rate limit exceeded. Please wait a few seconds and retry."

        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "get_news_failed",
            ticker=ticker,
            error=error_str,
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            exc_info=True,
        )

        return {"error": error_str, "ticker": ticker, "error_type": error_type}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_fund_info(ticker: str) -> dict:
    """Retrieves information for a given fund ticker.

    Fetches general information and top holdings for a fund (ETF or mutual fund).

    Args:
        ticker (str): The fund ticker symbol (e.g., 'VTI', 'SPY').

    Returns:
        dict: A dictionary containing fund data with consistent error structure.
            On success:
            {
                "ticker": str,
                "fund_overview": dict | None,
                "top_holdings": list[dict] | None,
                "sector_weightings": dict | None
            }

            On error:
            {
                "error": str,
                "ticker": str,
                "error_type": "no_data" | "rate_limit" | "unknown"
            }
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    logger.info("get_fund_info_called", ticker=ticker)

    try:
        fund = yf.Ticker(ticker)

        # Fetch funds_data object
        funds_data = None
        with contextlib.suppress(Exception):
            funds_data = fund.funds_data

        # If funds_data is None, the ticker likely doesn't exist or isn't a fund
        if funds_data is None:
            logger.warning("no_fund_data", ticker=ticker)
            return {
                "error": f"No fund data available for {ticker}. Verify ticker is valid and is a fund/ETF.",
                "ticker": ticker,
                "error_type": "no_data",
            }

        # Extract fund overview
        fund_overview = None
        try:
            overview = funds_data.fund_overview
            if overview is not None:
                if isinstance(overview, pd.DataFrame):
                    fund_overview = overview.to_dict(orient="index")
                elif isinstance(overview, dict):
                    fund_overview = {
                        k: (str(v) if not isinstance(v, int | float | bool | type(None)) else v)
                        for k, v in overview.items()
                    }
        except Exception:  # nosec
            pass

        # Extract top holdings
        top_holdings_data = None
        try:
            top_holdings = funds_data.top_holdings
            if top_holdings is not None and not top_holdings.empty:
                top_holdings_data = [
                    {
                        k: (
                            float(v)
                            if isinstance(v, int | float) and pd.notna(v)
                            else str(v) if pd.notna(v) else None
                        )
                        for k, v in row.items()
                    }
                    for row in top_holdings.to_dict(orient="records")
                ]
        except Exception:  # nosec
            pass

        # Extract sector weightings
        sector_weightings = None
        try:
            sectors = funds_data.sector_weightings
            if sectors is not None:
                if isinstance(sectors, pd.DataFrame):
                    sector_weightings = sectors.to_dict(orient="index")
                elif isinstance(sectors, dict):
                    sector_weightings = {
                        k: (float(v) if isinstance(v, int | float) else v)
                        for k, v in sectors.items()
                    }
        except Exception:  # nosec
            pass

        result = {
            "ticker": ticker,
            "fund_overview": fund_overview,
            "top_holdings": top_holdings_data,
            "sector_weightings": sector_weightings,
        }

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_fund_info_success",
            ticker=ticker,
            has_overview=fund_overview is not None,
            holdings_count=len(top_holdings_data) if top_holdings_data else 0,
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        error_type = "unknown"

        if any(term in error_str.lower() for term in ["rate", "429", "too many requests"]):
            error_type = "rate_limit"
            error_str = "Rate limit exceeded. Please wait a few seconds and retry."

        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "get_fund_info_failed",
            ticker=ticker,
            error=error_str,
            error_type=error_type,
            duration_ms=round(duration_ms, 2),
            exc_info=True,
        )

        return {"error": error_str, "ticker": ticker, "error_type": error_type}


# 30-minute cache for macro context — market conditions don't change by the minute.
_MACRO_CACHE: TTLCache = TTLCache(maxsize=1, ttl=1800)
_MACRO_CACHE_KEY = "global"


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_earnings_calendar(ticker: str) -> dict:
    """Fetches the next earnings date and EPS/revenue estimates for a ticker.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'AAPL').

    Returns:
        dict: {
            "ticker": str,
            "earnings_date": str | None,
            "days_until_earnings": int | None,
            "eps_estimate": float | None,
            "revenue_estimate": float | None,
            "earnings_imminent": bool   # True if earnings within 7 days
        }
        On error: {"error": str, "ticker": str, "error_type": str}
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    logger.info("get_earnings_calendar_called", ticker=ticker)

    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar

        if cal is None:
            return {
                "ticker": ticker,
                "error": "No earnings calendar available",
                "error_type": "no_data",
            }

        # Calendar can be a dict or DataFrame depending on yfinance version
        if isinstance(cal, pd.DataFrame):
            cal = cal.to_dict()

        if not isinstance(cal, dict):
            return {
                "ticker": ticker,
                "error": "Unexpected calendar format",
                "error_type": "no_data",
            }

        # Extract next earnings date
        earnings_dates = cal.get("Earnings Date", [])
        if hasattr(earnings_dates, "values"):
            earnings_dates = list(earnings_dates.values())
        if not isinstance(earnings_dates, list):
            earnings_dates = [earnings_dates]

        next_date_raw = earnings_dates[0] if earnings_dates else None
        earnings_date_str = None
        days_until = None

        if next_date_raw is not None:
            try:
                if hasattr(next_date_raw, "date"):
                    next_dt = next_date_raw.date()
                else:
                    next_dt = datetime.strptime(str(next_date_raw)[:10], "%Y-%m-%d").date()
                earnings_date_str = str(next_dt)
                days_until = (next_dt - datetime.now().date()).days
            except (ValueError, AttributeError):
                pass

        def _safe_float(val) -> float | None:
            if val is None:
                return None
            if hasattr(val, "values"):
                val = list(val.values())[0]
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

        eps_estimate = _safe_float(
            cal.get("Earnings Average") or cal.get("EPS Estimate") or cal.get("EPS Average")
        )
        revenue_estimate = _safe_float(cal.get("Revenue Average") or cal.get("Revenue Estimate"))

        result = {
            "ticker": ticker,
            "earnings_date": earnings_date_str,
            "days_until_earnings": days_until,
            "eps_estimate": eps_estimate,
            "revenue_estimate": revenue_estimate,
            "earnings_imminent": days_until is not None and 0 <= days_until <= 7,
        }

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_earnings_calendar_success",
            ticker=ticker,
            days_until=days_until,
            imminent=result["earnings_imminent"],
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        logger.error("get_earnings_calendar_failed", ticker=ticker, error=error_str, exc_info=True)
        return {"error": error_str, "ticker": ticker, "error_type": "unknown"}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_macro_context(ticker: str = "") -> dict:  # noqa: ARG001
    """Fetches key macro market indicators: S&P 500 YTD return, VIX, and 10-year Treasury yield.

    This tool takes NO required arguments. The optional ticker parameter is accepted
    but ignored — this returns broad market data, not ticker-specific data.

    Results are cached for 30 minutes since macro conditions change slowly.

    Returns:
        dict: {
            "sp500_ytd_pct": float | None,
            "vix_level": float | None,
            "market_regime": str,   # e.g. "Normal", "Elevated (Caution)", "High Volatility (Risk-Off)"
            "treasury_10y_yield": float | None
        }
        On error: {"error": str, "error_type": str}
    """
    if _MACRO_CACHE_KEY in _MACRO_CACHE:
        logger.debug("get_macro_context_cache_hit")
        return dict(_MACRO_CACHE[_MACRO_CACHE_KEY])

    start_time = time.time()
    logger.info("get_macro_context_called")

    try:
        # S&P 500 YTD
        gspc = yf.Ticker("^GSPC")
        gspc_hist = gspc.history(period="ytd")
        sp500_ytd = None
        if not gspc_hist.empty and len(gspc_hist) >= 2:
            start_price = float(gspc_hist["Close"].iloc[0])
            end_price = float(gspc_hist["Close"].iloc[-1])
            sp500_ytd = round((end_price - start_price) / start_price * 100, 2)

        # VIX
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        vix_level = round(float(vix_hist["Close"].iloc[-1]), 2) if not vix_hist.empty else None

        market_regime = "Unknown"
        if vix_level is not None:
            if vix_level < 15:
                market_regime = "Low Volatility (Risk-On)"
            elif vix_level < 20:
                market_regime = "Normal"
            elif vix_level < 30:
                market_regime = "Elevated (Caution)"
            else:
                market_regime = "High Volatility (Risk-Off)"

        # 10-Year Treasury (^TNX is quoted as yield × 10 in some feeds; yfinance returns actual %)
        tnx_hist = yf.Ticker("^TNX").history(period="5d")
        treasury_yield = round(float(tnx_hist["Close"].iloc[-1]), 2) if not tnx_hist.empty else None

        result = {
            "sp500_ytd_pct": sp500_ytd,
            "vix_level": vix_level,
            "market_regime": market_regime,
            "treasury_10y_yield": treasury_yield,
        }

        _MACRO_CACHE[_MACRO_CACHE_KEY] = result
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_macro_context_success",
            sp500_ytd=sp500_ytd,
            vix=vix_level,
            regime=market_regime,
            duration_ms=round(duration_ms, 2),
        )
        return result

    except Exception as e:
        error_str = str(e)
        logger.error("get_macro_context_failed", error=error_str, exc_info=True)
        return {"error": error_str, "error_type": "unknown"}


@mcp.tool()
@with_retry()
@circuit_breaker()
def get_sector_peers(ticker: str) -> dict:
    """Fetches the top peer companies in the same sector for benchmarking context.

    Uses yfinance Sector API. Falls back gracefully if sector data is unavailable.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'AAPL').

    Returns:
        dict: {
            "ticker": str,
            "sector": str | None,
            "peers": list[{"ticker": str, "name": str, "weight": float | None}],
            "count": int
        }
        On error: {"error": str, "ticker": str, "error_type": str}
    """
    start_time = time.time()
    ticker = ticker.strip().upper()
    logger.info("get_sector_peers_called", ticker=ticker)

    try:
        info = yf.Ticker(ticker).info
        sector = info.get("sector") or info.get("sectorKey")

        if not sector:
            return {
                "ticker": ticker,
                "sector": None,
                "peers": [],
                "count": 0,
                "error": "No sector information for this ticker",
                "error_type": "no_data",
            }

        # yfinance Sector uses lowercase hyphenated keys (e.g. "consumer-cyclical")
        sector_key = sector.lower().replace(" ", "-").replace("_", "-").replace("/", "-")

        peers: list[dict] = []
        try:
            sector_obj = yf.Sector(sector_key)
            top_cos = sector_obj.top_companies

            if top_cos is not None and not top_cos.empty:
                for sym, row in top_cos.head(7).iterrows():
                    if str(sym).upper() == ticker:
                        continue
                    peers.append(
                        {
                            "ticker": str(sym).upper(),
                            "name": str(row.get("name", sym)),
                            "weight": (
                                round(float(row["weight"]), 4)
                                if "weight" in row and pd.notna(row["weight"])
                                else None
                            ),
                        }
                    )
                    if len(peers) >= 5:
                        break
        except Exception as e:
            logger.warning("sector_peers_lookup_failed", sector=sector, error=str(e))

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "get_sector_peers_success",
            ticker=ticker,
            sector=sector,
            peer_count=len(peers),
            duration_ms=round(duration_ms, 2),
        )
        return {
            "ticker": ticker,
            "sector": sector,
            "peers": peers,
            "count": len(peers),
        }

    except Exception as e:
        error_str = str(e)
        logger.error("get_sector_peers_failed", ticker=ticker, error=error_str, exc_info=True)
        return {"error": error_str, "ticker": ticker, "error_type": "unknown"}


if __name__ == "__main__":
    logger.info("mcp_server_starting", transport="stdio")
    mcp.run(transport="stdio", show_banner=False)
    logger.info("mcp_server_shutdown")
