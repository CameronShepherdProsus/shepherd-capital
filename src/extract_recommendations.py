"""
Investment idea extraction from scraped content.

Modes:
  1. Regex + NLP rules (always available)
  2. LLM-assisted extraction (if API key present and config.use_llm=true)
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.database import ExtractedRecommendation, Source, get_session, init_db
from src.utils import clean_text, get_config_value, get_logger, parse_date, truncate

logger = get_logger("extract")

# ---------------------------------------------------------------------------
# Ticker patterns
# ---------------------------------------------------------------------------

# Matches: AAPL, NASDAQ:AAPL, NYSE:BRK.B, LON:VOD, ASX:CBA, JSE:NPN, TSX:SU
TICKER_RE = re.compile(
    r"\b(?:(NASDAQ|NYSE|AMEX|LON|ASX|JSE|TSX|HKEX|SGX|TSE|XETRA|EURONEXT):)?"
    r"([A-Z]{1,5}(?:\.[A-Z]{1,2})?)\b"
)

EXCHANGE_MAP = {
    "LON": "LSE", "ASX": "ASX", "JSE": "JSE", "TSX": "TSX",
    "NASDAQ": "NASDAQ", "NYSE": "NYSE", "AMEX": "AMEX",
    "HKEX": "HKEX", "SGX": "SGX", "TSE": "TSE", "XETRA": "XETRA",
}

# Words that look like tickers but aren't
FALSE_POSITIVE_TICKERS = {
    "A", "I", "IT", "IS", "AT", "BY", "OR", "TO", "IN", "ON", "OF", "AS",
    "AN", "BE", "DO", "GO", "UP", "US", "UK", "EU", "AI", "OK", "NO", "SO",
    "IF", "IP", "ID", "HQ", "HR", "PR", "PE", "VC", "CEO", "CFO", "COO",
    "CTO", "IPO", "ETF", "GDP", "CPI", "EPS", "FCF", "ROE", "ROI", "CAGR",
    "YOY", "QOQ", "SG", "HK", "CA", "NZ", "AU", "JP", "DE", "FR", "CH",
    "LBO", "DCF", "NAV", "NTA", "AUM", "IRR", "NPV", "BPS", "DPS", "PEG",
    "EV", "EBIT", "TAM", "SAM", "SOM", "MOU", "LOI", "NDA", "SEC", "SPAC",
    "AND", "THE", "FOR", "BUT", "NOT", "ARE", "WAS", "HAS", "HAD", "HAVE",
    "THIS", "THAT", "THEY", "FROM", "WITH", "WILL", "BEEN", "WERE", "SAID",
    "WHO", "WHAT", "WHEN", "WHERE", "HOW", "WHY", "ALL", "ITS", "MORE",
    "THAN", "INTO", "OVER", "ALSO", "EACH", "BOTH", "MANY", "MOST", "SUCH",
    "SOME", "ANY", "CAN", "MAY", "MUST", "LTD", "INC", "PLC", "LLC", "LP",
    "AG", "SA", "NV", "BV", "SE", "RE",
}

# ---------------------------------------------------------------------------
# Recommendation type detection
# ---------------------------------------------------------------------------

REC_PATTERNS: List[tuple] = [
    # More-specific patterns must come before general ones (e.g. portfolio_holding before hold)
    ("portfolio_holding", re.compile(r"\b(port(folio)?\s+hold(ing)?|current\s+hold(ing)?|portfolio company|in the portfolio|in my portfolio)\b", re.I)),
    ("watchlist",         re.compile(r"\b(watch\s*list|on watch|watching closely|on my radar|on radar|keeping an eye)\b", re.I)),
    ("buy",               re.compile(r"\b(buy|buying|bought|go long|initiating|initiate|opening a position)\b", re.I)),
    ("long",              re.compile(r"\b(long|long position|long idea|going long)\b", re.I)),
    ("add",               re.compile(r"\b(add(ing)?|accumulate|top up|increase(d)? position)\b", re.I)),
    ("trim",              re.compile(r"\b(trim(ming)?|reduce(d)?|partial(ly)? sold|take(ing)? profit)\b", re.I)),
    ("sell",              re.compile(r"\b(sell(ing)?|sold|exit(ed)?|close(d)? position|closing)\b", re.I)),
    ("short",             re.compile(r"\b(short(ing)?|short position|short idea|bear(ish)? on)\b", re.I)),
    ("avoid",             re.compile(r"\b(avoid(ing)?|pass(ing)? on|not interested|no interest|steer clear)\b", re.I)),
    ("hold",              re.compile(r"\b(hold(ing)?|maintain(ing)?|keep(ing)?)\b", re.I)),
]

MENTION_RE = re.compile(r"\b(mention(ed)?|interesting|worth watching|noted|noted|discussed)\b", re.I)


def classify_recommendation(text: str) -> tuple[str, str]:
    """Return (rec_type, confidence)."""
    for rec_type, pattern in REC_PATTERNS:
        if pattern.search(text):
            confidence = "high" if rec_type in ("buy", "long", "sell", "short", "portfolio_holding") else "medium"
            return rec_type, confidence
    if MENTION_RE.search(text):
        return "mention_only", "low"
    return "mention_only", "unknown"


# ---------------------------------------------------------------------------
# Thesis / catalyst / risk extraction
# ---------------------------------------------------------------------------

CATALYST_RE = re.compile(
    r"(?:catalyst|driver|trigger|upside|growth|opportunity|tailwind)[s]?\s*[:\-]?\s*([^.!?\n]{10,200})",
    re.I,
)
RISK_RE = re.compile(
    r"(?:risk|concern|downside|challenge|bear case|headwind)[s]?\s*[:\-]?\s*([^.!?\n]{10,200})",
    re.I,
)
TARGET_PRICE_RE = re.compile(
    r"(?:target price|price target|fair value|intrinsic value|target)\s*(?:is|of|:)?\s*[\$\£\€]?\s*(\d[\d,\.]+)",
    re.I,
)
TIME_HORIZON_RE = re.compile(
    r"(?:horizon|timeframe|over|within|by)\s+(\d+[\-–]\d+\s*(?:year|month|yr|mo)s?|"
    r"\d+\s*(?:year|month|yr|mo)s?|(?:short|medium|long)[- ]term)",
    re.I,
)
VALUATION_RE = re.compile(
    r"\b(?:P/E|EV/EBITDA|P/S|P/B|P/FCF|EV/Sales|NTM\s*P/E|LTM\s*P/E|"
    r"price[\s-]to[\s-]earnings|price[\s-]to[\s-]book)\b[^.!?]{0,100}",
    re.I,
)


def extract_metadata(text: str) -> dict:
    catalysts = [m.group(1).strip() for m in CATALYST_RE.finditer(text)][:3]
    risks = [m.group(1).strip() for m in RISK_RE.finditer(text)][:3]
    target_price = None
    tm = TARGET_PRICE_RE.search(text)
    if tm:
        try:
            target_price = float(tm.group(1).replace(",", ""))
        except ValueError:
            pass
    time_horizon = None
    thm = TIME_HORIZON_RE.search(text)
    if thm:
        time_horizon = thm.group(1).strip()
    valuation = [m.group(0).strip() for m in VALUATION_RE.finditer(text)][:3]
    return {
        "catalysts": "; ".join(catalysts),
        "risks": "; ".join(risks),
        "target_price": target_price,
        "time_horizon": time_horizon,
        "valuation_metrics": "; ".join(valuation),
    }


# ---------------------------------------------------------------------------
# Sentence context
# ---------------------------------------------------------------------------

def get_context_window(text: str, pos: int, window: int = 200) -> str:
    """Return a tight window (default ±200 chars) around a match position."""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return text[start:end]


def get_sentence_context(text: str, pos: int, extra_sentences: int = 0) -> str:
    """
    Return the sentence containing `pos` plus `extra_sentences` on each side.
    Uses character-position boundaries to avoid off-by-one errors.
    """
    # Find sentence break positions using character offsets
    breaks = [0] + [m.end() for m in re.finditer(r"[.!?\n]+\s*", text)] + [len(text)]
    # Deduplicate and sort
    breaks = sorted(set(breaks))

    # Identify which segment contains pos
    sent_idx = max(0, len(breaks) - 2)  # default: last segment
    for i in range(len(breaks) - 1):
        if breaks[i] <= pos < breaks[i + 1]:
            sent_idx = i
            break

    seg_start = breaks[max(0, sent_idx - extra_sentences)]
    seg_end = breaks[min(len(breaks) - 1, sent_idx + extra_sentences + 1)]
    return text[seg_start:seg_end].strip()


def summarise_thesis(text: str, company: str, max_chars: int = 400) -> str:
    """Return the most relevant sentence(s) around the company mention."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    hits = [s for s in sentences if company.lower() in s.lower()][:3]
    if hits:
        return truncate(" ".join(hits), max_chars)
    return truncate(text, max_chars)


# ---------------------------------------------------------------------------
# Source-level context inference
# ---------------------------------------------------------------------------

# Maps URL slug / title patterns → (rec_type, confidence, extraction_confidence)
_SOURCE_PATTERNS: List[tuple] = [
    (re.compile(r"deep.?dive|deep_dive",          re.I), "long",              "high",   0.80),
    (re.compile(r"portfolio.?hold|portfolio.?updat|rebound.?portfolio|building.?a.?rebound", re.I), "portfolio_holding", "high", 0.80),
    (re.compile(r"watchlist",                     re.I), "watchlist",         "high",   0.75),
    (re.compile(r"\d+.?stocks.?in.?a?.?deep.?drawdown|overlooked.?stocks|bruised.?blue|built.?to.?last", re.I), "buy", "high", 0.80),
    (re.compile(r"earnings.?review|earnings.?preview|earnings.?update", re.I), "hold",  "medium", 0.55),
    (re.compile(r"notes.?on|turnaround",          re.I), "long",              "medium", 0.65),
    (re.compile(r"glp.?1|healthcare",             re.I), "watchlist",         "medium", 0.60),
]


def infer_source_type(source_url: str, source_title: str) -> Optional[tuple]:
    """
    Return (rec_type, confidence, extraction_confidence) inferred from the
    article URL slug and title, or None if no pattern matches.
    """
    combined = f"{source_url} {source_title}".lower()
    for pattern, rec_type, conf, extr_conf in _SOURCE_PATTERNS:
        if pattern.search(combined):
            return rec_type, conf, extr_conf
    return None


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------

def extract_from_text(
    text: str,
    source_id: int,
    pub_date: Optional[datetime] = None,
    source_url: str = "",
    source_title: str = "",
) -> List[dict]:
    """Extract all investment ideas from a block of text."""
    results = []
    seen_tickers = set()

    # Infer a default classification from the article URL/title
    source_inference = infer_source_type(source_url, source_title)

    for m in TICKER_RE.finditer(text):
        exchange_prefix = m.group(1) or ""
        ticker_raw = m.group(2)

        if ticker_raw in FALSE_POSITIVE_TICKERS:
            continue
        if len(ticker_raw) < 2:
            continue

        key = f"{exchange_prefix}:{ticker_raw}" if exchange_prefix else ticker_raw
        if key in seen_tickers:
            continue
        seen_tickers.add(key)

        sentence_ctx = get_sentence_context(text, m.start(), extra_sentences=0)
        wide_ctx = get_context_window(text, m.start(), 300)

        # Try text-level classification first
        rec_type, confidence = classify_recommendation(sentence_ctx)

        # If text gave only "mention_only" or "hold", upgrade using source-level inference
        if source_inference and rec_type in ("mention_only", "hold"):
            inferred_type, inferred_conf, inferred_extr = source_inference
            rec_type = inferred_type
            confidence = inferred_conf
            extraction_confidence = inferred_extr
        else:
            extraction_confidence = 0.6 if confidence != "unknown" else 0.3

        meta = extract_metadata(wide_ctx)
        thesis = summarise_thesis(wide_ctx, ticker_raw)
        excerpt = truncate(sentence_ctx, 250)
        exchange = EXCHANGE_MAP.get(exchange_prefix, exchange_prefix or None)

        results.append({
            "source_id": source_id,
            "company_name": ticker_raw,
            "ticker": ticker_raw,
            "exchange": exchange,
            "recommendation_type": rec_type,
            "confidence": confidence,
            "recommendation_date": pub_date,
            "excerpt": excerpt,
            "thesis_summary": thesis,
            "extraction_method": "regex",
            "extraction_confidence": extraction_confidence,
            **meta,
        })

    return results


# ---------------------------------------------------------------------------
# LLM-assisted extraction
# ---------------------------------------------------------------------------

LLM_PROMPT = """You are an investment research analyst extracting structured data from financial writing.

Given the following article excerpt, identify all stock/equity investment ideas mentioned.

For each:
- company_name: full company name
- ticker: stock ticker (e.g. AAPL, LON:VOD)
- exchange: exchange if mentioned
- recommendation_type: one of: buy, long, add, hold, watchlist, trim, sell, short, avoid, portfolio_holding, mention_only
- confidence: high, medium, or low
- thesis_summary: 1-2 sentence summary of why the author likes/dislikes this stock
- catalysts: key growth drivers mentioned
- risks: key risks mentioned
- target_price: numerical target price if mentioned (null if not)
- time_horizon: e.g. "2 years", "long-term" (null if not)

Return a JSON array. Only include companies that are clearly stock/equity investments.
Do not invent information not present in the text.

Article:
{text}

JSON array:"""


def llm_extract(text: str, source_id: int, pub_date: Optional[datetime] = None) -> List[dict]:
    provider = get_config_value("extraction", "llm_provider", default="anthropic")
    results = []

    try:
        if provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": LLM_PROMPT.format(text=text[:4000])}],
            )
            raw = resp.content[0].text
        elif provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": LLM_PROMPT.format(text=text[:4000])}],
                max_tokens=2048,
            )
            raw = resp.choices[0].message.content
        else:
            return []

        # Parse JSON from response
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []
        items = json.loads(json_match.group(0))

        for item in items:
            if not isinstance(item, dict):
                continue
            results.append({
                "source_id": source_id,
                "company_name": item.get("company_name", ""),
                "ticker": item.get("ticker", ""),
                "exchange": item.get("exchange"),
                "recommendation_type": item.get("recommendation_type", "mention_only"),
                "confidence": item.get("confidence", "unknown"),
                "recommendation_date": pub_date,
                "excerpt": truncate(text, 250),
                "thesis_summary": item.get("thesis_summary", ""),
                "catalysts": item.get("catalysts", ""),
                "risks": item.get("risks", ""),
                "target_price": item.get("target_price"),
                "time_horizon": item.get("time_horizon"),
                "valuation_metrics": None,
                "extraction_method": "llm",
                "extraction_confidence": 0.85,
            })
    except Exception as exc:
        logger.warning(f"LLM extraction failed: {exc}")

    return results


# ---------------------------------------------------------------------------
# Main extraction pipeline
# ---------------------------------------------------------------------------

def extract_all(force_reextract: bool = False) -> int:
    init_db()
    session = get_session()
    use_llm = get_config_value("extraction", "use_llm", default=False)

    # Check for API key
    if use_llm:
        provider = get_config_value("extraction", "llm_provider", default="anthropic")
        if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            logger.warning("use_llm=true but ANTHROPIC_API_KEY not set — falling back to regex.")
            use_llm = False
        elif provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
            logger.warning("use_llm=true but OPENAI_API_KEY not set — falling back to regex.")
            use_llm = False

    from sqlalchemy import text as sqla_text

    # Get sources to process
    if force_reextract:
        # Clear existing extractions and re-process all fetched/parsed sources
        session.execute(sqla_text("DELETE FROM extracted_recommendations"))
        session.execute(sqla_text("UPDATE sources SET status='fetched' WHERE status='parsed'"))
        session.commit()
        sources = session.query(Source).filter(Source.status == "fetched").all()
    else:
        extracted_ids = {row[0] for row in session.execute(
            sqla_text("SELECT DISTINCT source_id FROM extracted_recommendations")
        )}
        sources = session.query(Source).filter(
            Source.status == "fetched",
            Source.id.not_in(extracted_ids) if extracted_ids else Source.status == "fetched"
        ).all()

    logger.info(f"Sources to extract from: {len(sources)}")
    total_extracted = 0

    for src in sources:
        # Load body text from raw HTML
        body_text = ""
        if src.raw_html_path and Path(src.raw_html_path).exists():
            import trafilatura
            raw = Path(src.raw_html_path).read_text(encoding="utf-8", errors="replace")
            body_text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""

        if not body_text.strip():
            src.status = "parsed"
            session.commit()
            continue

        src_url = src.url or ""
        src_title = src.title or ""

        if use_llm:
            ideas = llm_extract(body_text, src.id, src.published_date)
            if not ideas:
                ideas = extract_from_text(body_text, src.id, src.published_date, src_url, src_title)
        else:
            ideas = extract_from_text(body_text, src.id, src.published_date, src_url, src_title)

        for idea in ideas:
            rec = ExtractedRecommendation(
                source_id=idea["source_id"],
                company_name=idea["company_name"],
                ticker=idea["ticker"],
                exchange=idea.get("exchange"),
                recommendation_type=idea["recommendation_type"],
                confidence=idea["confidence"],
                recommendation_date=idea.get("recommendation_date"),
                excerpt=idea.get("excerpt"),
                thesis_summary=idea.get("thesis_summary"),
                catalysts=idea.get("catalysts"),
                risks=idea.get("risks"),
                target_price=idea.get("target_price"),
                time_horizon=idea.get("time_horizon"),
                valuation_metrics=idea.get("valuation_metrics"),
                extraction_method=idea["extraction_method"],
                extraction_confidence=idea.get("extraction_confidence", 0.5),
            )
            session.add(rec)

        src.status = "parsed"
        session.commit()
        total_extracted += len(ideas)

    logger.info(f"Extraction complete. Ideas extracted: {total_extracted}")
    return total_extracted
