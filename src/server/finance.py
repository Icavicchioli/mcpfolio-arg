"""MCP Financial Server - Provides market data tools via stdio transport."""

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf
from fastmcp import FastMCP

# Add parent directory to path to import logging_config
sys.path.insert(0, str(Path(__file__).parent.parent))
import contextlib

from logging_config import get_logger

logger = get_logger(__name__)
mcp = FastMCP("finance-server")


@mcp.tool()
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
        except Exception:
            calendar_data = None

        # Analyst price targets
        analyst_targets = None
        try:
            targets = stock.analyst_price_targets
            if targets is not None and isinstance(targets, dict):
                analyst_targets = {
                    k: float(v) if isinstance(v, int | float) else v for k, v in targets.items()
                }
        except Exception:
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
        except Exception:
            quarterly_income_data = None

        result = {
            "ticker": ticker,
            "current_price": float(price) if price else None,
            "volume": int(volume) if volume else None,
            "high_52_week": round(high_52w, 2),
            "low_52_week": round(low_52w, 2),
            "volatility_52_week_pct": round(volatility, 2),
            "calendar": calendar_data,
            "analyst_targets": analyst_targets,
            "quarterly_income": quarterly_income_data,
        }

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
        except Exception:
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
        except Exception:
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
        except Exception:
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


if __name__ == "__main__":
    logger.info("mcp_server_starting", transport="stdio")
    mcp.run(transport="stdio", show_banner=False)
    logger.info("mcp_server_shutdown")
