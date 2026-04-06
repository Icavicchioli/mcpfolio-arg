# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Adam Karp
"""Prompts for the MCPFolio Financial Analyst."""

import re

SYSTEM_PROMPT = """You are a long-term investment analyst evaluating stocks on a 3-5+ year horizon.

REASONING ORDER — always evaluate in this sequence:
1. **Fundamentals first**: Market cap context, P/E relative to growth expectations, earnings trajectory, revenue consistency, dividend history.
2. **Analyst sentiment**: Buy/Hold/Sell consensus and price targets carry significant weight. If most analysts rate BUY, do NOT override with SELL based on volatility alone.
3. **Technicals as context**: Price range and volatility provide entry-point context, NOT sell signals for fundamentally strong companies.

KEY PRINCIPLES:
- Short-term volatility is NOT a sell signal for blue-chip or mega-cap companies with strong fundamentals.
- A P/E of 25-35 for a mega-cap with consistent double-digit earnings growth is reasonable — compare P/E against growth rate, not in isolation.
- Evaluate competitive moat: market dominance, brand strength, ecosystem lock-in, recurring revenue.
- CAUTION should replace SELL unless fundamentals are genuinely deteriorating (declining revenue, negative earnings trend, analyst downgrades).
- Stick strictly to provided data. If data is missing, state what you don't know.

OUTPUT FORMAT — ~250 words max:

CRITICAL FORMATTING RULES:
1. Each of the four header fields MUST appear on its own line. Never combine them.
   BAD:  RECOMMENDATION: BUY CONFIDENCE: 0.85 KEY_RISK: ...
   GOOD:
     RECOMMENDATION: BUY
     CONFIDENCE: 0.85
     KEY_RISK: High valuation premium relative to peers
     FAIR_VALUE: $250

2. FAIR_VALUE is mandatory — never omit it. Write FAIR_VALUE: N/A if you cannot estimate.

3. Section headers MUST use ## prefix. Write "## Thesis", not "Thesis:" or "Thesis".

Output EXACTLY in this order:

RECOMMENDATION: [BUY/HOLD/SELL/CAUTION]
CONFIDENCE: [0.00-1.00]
KEY_RISK: [single sentence — the biggest risk]
FAIR_VALUE: [$price or N/A]

## Thesis
Write 2-3 flowing sentences explaining the core investment case. Avoid bullet points here.

## Fundamentals
- Market cap and scale context
- P/E vs growth rate assessment
- Dividend and earnings trajectory

## Analyst Consensus
One fluent sentence summarizing the buy/hold/sell split and average price target.

## Risk Factors
- Risk 1: brief explanation
- Risk 2: brief explanation
- Risk 3: brief explanation

## Verdict
Write 2-3 polished sentences with a clear directional conclusion for a long-term investor. End with the recommendation restated naturally.
"""

PREFETCH_NOTICE = (
    "IMPORTANT: Live market data has already been retrieved and is shown above. "
    "You HAVE the current data needed to answer. "
    "DO NOT say you cannot access or provide market data — you already have it. "
    "Answer directly using the market data shown above. "
    "Only call additional tools if the user asks for data not already provided."
)

COMPARISON_SYSTEM_PROMPT = """You are a long-term investment analyst comparing two stocks on a 3-5+ year horizon.

REASONING ORDER — always evaluate in this sequence:
1. **Fundamentals first**: Compare market caps, P/E ratios relative to growth, earnings trajectories, revenue consistency, dividend histories.
2. **Analyst sentiment**: Buy/Hold/Sell consensus and price targets for each ticker. Weight analyst consensus heavily.
3. **Technicals as context**: 52-week ranges and volatility provide relative entry-point context.
4. **Competitive moat**: Which company has the stronger durable advantage?

KEY PRINCIPLES:
- Short-term volatility is NOT a sell signal for fundamentally strong companies.
- A higher P/E is acceptable if justified by superior growth rate (compare PEG ratios mentally).
- If data is missing for one ticker, note it explicitly and weight the comparison accordingly.
- EQUAL verdict is valid if both companies are genuinely comparable in quality.
- Stick strictly to provided data. State what you don't know.

OUTPUT FORMAT — be concise (~350 words max), use these exact headers:

COMPARISON: [TICKER_A / TICKER_B / EQUAL]
## Side-by-Side
| Metric | TICKER_A | TICKER_B |
|--------|----------|----------|
(fill in: Price, Market Cap, P/E, EPS, Revenue, Dividend Yield, 52-Week Volatility)
## Valuation Delta
2-3 sentences comparing relative valuation and growth expectations.
## Analyst Consensus
One-liner per ticker summarizing buy/hold/sell counts.
## Risk Factors
- 2-3 bullet points covering the key risks for each.
## Verdict
2-3 sentence final recommendation for a long-term investor choosing between the two.
"""

ANALYSIS_TEMPLATE = """# Analysis for {ticker}

{ai_analysis}

---
*Note: This is an AI-generated sanity check and does not constitute financial advice.*
"""


def parse_llm_output(text: str) -> dict:
    """Extract the structured block from LLM output.

    Handles fields on separate lines OR all on one line, and accepts both
    FAIR_VALUE and FAIR VALUE (with space) as written by the LLM.

    Returns a dict with keys: recommendation, confidence, key_risk, fair_value.
    Any field that cannot be parsed is returned as None.
    """
    # Lookahead stops each field's value at the next known keyword or end-of-string.
    # This works whether the fields are newline-separated or all on one line.
    _BOUNDARY = r"(?=\s*(?:RECOMMENDATION|CONFIDENCE|KEY[_ ]RISK|FAIR[_ ]VALUE)\s*:|$)"

    def _find(label: str) -> str | None:
        # Accept both underscore and space variants (KEY_RISK / KEY RISK, etc.)
        pat = re.escape(label).replace(r"\ ", r"[_ ]")
        m = re.search(rf"{pat}\s*:\s*(.+?){_BOUNDARY}", text, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    recommendation = _find("RECOMMENDATION")
    if recommendation:
        recommendation = re.sub(r"[\[\]*_]", "", recommendation).strip().upper()

    confidence_str = _find("CONFIDENCE")
    confidence = None
    if confidence_str:
        m = re.search(r"(\d+\.?\d*)", confidence_str)
        if m:
            val = float(m.group(1))
            confidence = val if val <= 1.0 else val / 100.0
            confidence = round(max(0.0, min(1.0, confidence)), 2)

    key_risk = _find("KEY_RISK") or _find("KEY RISK")
    if key_risk:
        key_risk = re.sub(r"[\[\]*_]", "", key_risk).strip()

    fair_value = None
    fv_str = _find("FAIR_VALUE") or _find("FAIR VALUE")
    if fv_str and fv_str.strip().upper() != "N/A":
        m = re.search(r"(\d+\.?\d*)", fv_str.replace(",", ""))
        if m:
            fair_value = float(m.group(1))

    return {
        "recommendation": recommendation,
        "confidence": confidence,
        "key_risk": key_risk,
        "fair_value": fair_value,
    }


def _fmt_mktcap(mkt_cap) -> str:
    if mkt_cap and mkt_cap > 1e9:
        return f"${mkt_cap / 1e9:.1f}B"
    if mkt_cap and mkt_cap > 1e6:
        return f"${mkt_cap / 1e6:.0f}M"
    return "N/A"


def format_single_context(
    ticker: str,
    snapshot: dict,
    sentiment: list[dict] | None,
    news: list[dict] | None,
) -> str:
    """
    Build the LLM context string from parsed market data.

    Used by both the CLI prefetch node and the web run_analysis_task.
    All inputs should be already-parsed dicts/lists (not raw MCP results).
    """
    price = snapshot.get("current_price", "N/A")
    mkt_cap_str = _fmt_mktcap(snapshot.get("market_cap"))
    pe_ratio = snapshot.get("pe_ratio") or snapshot.get("trailing_pe")
    pe_display = pe_ratio if pe_ratio is not None else "N/A"
    div_yield = snapshot.get("dividend_yield")
    div_str = f"{div_yield * 100:.2f}%" if div_yield else "0% (no dividend)"
    vol_pct = snapshot.get("volatility_52_week_pct", 0)
    week_high = snapshot.get("fifty_two_week_high", "N/A")
    week_low = snapshot.get("fifty_two_week_low", "N/A")
    change_pct = snapshot.get("change_percent", 0)
    eps = snapshot.get("eps") or snapshot.get("trailing_eps") or "N/A"
    rev = snapshot.get("revenue")
    rev_str = f"${rev / 1e9:.1f}B" if rev and rev > 1e9 else f"${rev / 1e6:.0f}M" if rev else "N/A"
    volume = snapshot.get("volume")
    vol_str = f"{volume:,}" if volume else "N/A"

    context = f"""MARKET DATA for {ticker}:
- Price: ${price} ({change_pct:+.2f}% today)
- Volume: {vol_str}
- Market Cap: {mkt_cap_str}
- P/E Ratio: {pe_display}
- EPS: {eps}
- Revenue: {rev_str}
- Dividend Yield: {div_str}
- 52-Week Range: ${week_low} – ${week_high} (volatility: {vol_pct:.1f}%)
"""

    if sentiment:
        # Detect format: period-aggregate (strongBuy/buy/hold/sell/strongSell)
        # vs individual firm ratings (firm/grade/action)
        first = sentiment[0]
        if any(k in first for k in ("strongBuy", "buy", "hold", "sell", "strongSell")):
            # Period-aggregate format from get_sentiment_data — sum across returned periods
            totals = {"strongBuy": 0, "buy": 0, "hold": 0, "sell": 0, "strongSell": 0}
            for r in sentiment:
                for k in totals:
                    totals[k] += int(r.get(k) or 0)
            total_analysts = sum(totals.values())
            context += (
                f"\nANALYST CONSENSUS ({len(sentiment)} periods, {total_analysts} total ratings):\n"
                f"  Strong Buy: {totals['strongBuy']}, Buy: {totals['buy']}, "
                f"Hold: {totals['hold']}, Sell: {totals['sell']}, "
                f"Strong Sell: {totals['strongSell']}\n"
            )
        else:
            # Individual firm ratings format (firm/grade/action)
            ratings_summary = []
            for r in sentiment:
                firm = r.get("firm", "Unknown")
                grade = r.get("grade") or r.get("action") or "N/A"
                ratings_summary.append(f"  - {firm}: {grade}")
            context += (
                f"\nANALYST RATINGS ({len(sentiment)} recent):\n"
                + "\n".join(ratings_summary)
                + "\n"
            )
    else:
        context += "\nANALYST RATINGS: No data available.\n"

    if news:
        news_lines = []
        for n in news[:5]:
            title = n.get("title", "")
            source = n.get("publisher") or n.get("source") or ""
            news_lines.append(f"  - {title}" + (f" ({source})" if source else ""))
        context += "\nRECENT NEWS:\n" + "\n".join(news_lines) + "\n"
    else:
        context += "\nRECENT NEWS: No data available.\n"

    return context


def format_comparison_context(
    ticker_a: str,
    snapshot_a: dict,
    sentiment_a: list[dict] | None,
    news_a: list[dict] | None,
    ticker_b: str,
    snapshot_b: dict,
    sentiment_b: list[dict] | None,
    news_b: list[dict] | None,
) -> str:
    """
    Build a side-by-side comparison context string for the LLM.

    Used by both the CLI prefetch_compare node and the web /api/compare endpoint.
    """
    block_a = format_single_context(ticker_a, snapshot_a, sentiment_a, news_a)
    block_b = format_single_context(ticker_b, snapshot_b, sentiment_b, news_b)
    return f"{block_a}\n{'=' * 40}\n\n{block_b}"
