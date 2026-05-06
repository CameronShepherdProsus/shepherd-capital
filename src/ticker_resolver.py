"""
Ticker resolution: maps company names/partial tickers to canonical tickers.

Resolution order:
  1. Manual overrides CSV
  2. Already-resolved ticker_map in DB
  3. Exchange-prefixed ticker (already canonical)
  4. yfinance search
  5. Mark as ambiguous for manual review
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yfinance as yf
from rapidfuzz import fuzz, process as rf_process

from src.database import ExtractedRecommendation, TickerMap, get_session, init_db
from src.utils import get_config_value, get_logger

logger = get_logger("ticker_resolver")


# ---------------------------------------------------------------------------
# Load manual overrides
# ---------------------------------------------------------------------------

def load_manual_overrides() -> Dict[str, dict]:
    path = Path(get_config_value("ticker_overrides_file", default="data/processed/manual_ticker_overrides.csv"))
    overrides: Dict[str, dict] = {}
    if not path.exists():
        return overrides
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("company_name", "").strip().lower()
            if name:
                overrides[name] = {
                    "ticker": row.get("ticker", "").strip().upper(),
                    "exchange": row.get("exchange", "").strip(),
                    "notes": row.get("notes", "").strip(),
                }
    logger.info(f"Loaded {len(overrides)} manual ticker overrides")
    return overrides


# ---------------------------------------------------------------------------
# yfinance lookup
# ---------------------------------------------------------------------------

def yf_search(query: str) -> Optional[Tuple[str, str, float]]:
    """
    Search yfinance for a ticker. Returns (ticker, exchange, confidence) or None.
    yfinance doesn't have a search API; we validate by checking if the ticker info loads.
    """
    # Clean the query to a plausible ticker
    candidate = re.sub(r"[^A-Z0-9.\-]", "", query.upper())[:10]
    if not candidate:
        return None
    try:
        info = yf.Ticker(candidate).info
        if info and info.get("symbol"):
            return info["symbol"], info.get("exchange", ""), 0.85
    except Exception:
        pass
    return None


def fuzzy_match_ticker(name: str, known_map: Dict[str, dict]) -> Optional[Tuple[str, float]]:
    """Fuzzy match company name against known_map keys. Returns (ticker, score)."""
    if not known_map:
        return None
    result = rf_process.extractOne(name.lower(), known_map.keys(), scorer=fuzz.token_sort_ratio)
    if result and result[1] >= 80:
        entry = known_map[result[0]]
        return entry.get("ticker"), result[1] / 100.0
    return None


# ---------------------------------------------------------------------------
# Main resolution
# ---------------------------------------------------------------------------

def resolve_tickers() -> dict:
    init_db()
    session = get_session()
    manual = load_manual_overrides()

    # Load existing resolved map from DB
    db_map: Dict[str, dict] = {}
    for tm in session.query(TickerMap).all():
        db_map[tm.company_name.lower()] = {
            "ticker": tm.ticker,
            "exchange": tm.exchange,
            "confidence": tm.confidence,
            "manual_override": tm.manual_override,
        }

    # Get all unique (company_name, ticker, exchange) combos from recommendations
    from sqlalchemy import text as sqla_text
    rows = session.execute(sqla_text(
        "SELECT DISTINCT company_name, ticker, exchange FROM extracted_recommendations "
        "WHERE ticker IS NOT NULL AND ticker != ''"
    )).fetchall()

    stats = {"resolved": 0, "manual": 0, "yfinance": 0, "ambiguous": 0, "skipped": 0}

    for company_name, ticker, exchange in rows:
        name_lower = (company_name or "").lower()
        ticker_upper = (ticker or "").upper()

        # 1. Manual override
        if name_lower in manual:
            ov = manual[name_lower]
            _upsert_ticker_map(session, company_name, ov["ticker"], ov["exchange"], 1.0, "manual", True)
            stats["manual"] += 1
            continue

        # 2. Already in DB with high confidence
        if name_lower in db_map and db_map[name_lower]["confidence"] >= 0.8:
            stats["skipped"] += 1
            continue

        # 3. Already has exchange prefix → canonical
        if re.match(r"^[A-Z]+:[A-Z]{1,5}$", ticker_upper):
            parts = ticker_upper.split(":")
            _upsert_ticker_map(session, company_name, parts[1], parts[0], 0.95, "regex", False)
            stats["resolved"] += 1
            continue

        # 4. Try exact uppercase ticker via yfinance
        result = yf_search(ticker_upper)
        if result:
            _upsert_ticker_map(session, company_name, result[0], result[1], result[2], "yfinance", False)
            stats["yfinance"] += 1
            continue

        # 5. Fuzzy match against manual overrides
        fm = fuzzy_match_ticker(name_lower, manual)
        if fm:
            _upsert_ticker_map(session, company_name, fm[0], None, fm[1], "fuzzy", False)
            stats["resolved"] += 1
            continue

        # 6. Store as ambiguous
        _upsert_ticker_map(session, company_name, ticker_upper, exchange, 0.3, "regex", False)
        stats["ambiguous"] += 1

    session.commit()
    logger.info(f"Ticker resolution: {stats}")
    return stats


def _upsert_ticker_map(
    session,
    company_name: str,
    ticker: str,
    exchange: Optional[str],
    confidence: float,
    source: str,
    manual_override: bool,
) -> None:
    existing = session.query(TickerMap).filter_by(company_name=company_name).first()
    if existing:
        if manual_override or confidence > existing.confidence:
            existing.ticker = ticker
            existing.exchange = exchange
            existing.confidence = confidence
            existing.source = source
            existing.manual_override = manual_override
    else:
        session.add(TickerMap(
            company_name=company_name,
            ticker=ticker,
            exchange=exchange,
            confidence=confidence,
            source=source,
            manual_override=manual_override,
        ))
    session.commit()


def enrich_recommendations_with_tickers() -> None:
    """
    Back-fill resolved tickers into extracted_recommendations.
    - Fills nulls/blanks for all entries.
    - For manual overrides, also corrects already-set tickers so the portfolio
      uses the canonical symbol (e.g. LVMH → LVMUY, TSMC → TSM).
    """
    session = get_session()
    from sqlalchemy import text as sqla_text
    for tm in session.query(TickerMap).all():
        if not tm.ticker:
            # Blank ticker = false positive; clear any existing value so portfolio ignores it
            session.execute(sqla_text(
                "UPDATE extracted_recommendations SET ticker='', exchange=NULL "
                "WHERE company_name=:c"
            ), {"c": tm.company_name})
        elif tm.manual_override:
            # Manual override: update even if a ticker was already set
            session.execute(sqla_text(
                "UPDATE extracted_recommendations SET ticker=:t, exchange=:e "
                "WHERE company_name=:c"
            ), {"t": tm.ticker, "e": tm.exchange, "c": tm.company_name})
        else:
            # Automated resolution: only fill nulls/blanks
            session.execute(sqla_text(
                "UPDATE extracted_recommendations SET ticker=:t, exchange=:e "
                "WHERE company_name=:c AND (ticker IS NULL OR ticker='')"
            ), {"t": tm.ticker, "e": tm.exchange, "c": tm.company_name})
    session.commit()
