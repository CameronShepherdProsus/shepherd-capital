"""
Stock price fetcher using yfinance.

Stores adjusted close history in SQLite prices table.
Caches to avoid unnecessary API calls.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from src.database import Price, get_session, init_db
from src.utils import get_config_value, get_logger

logger = get_logger("price_fetcher")
warnings.filterwarnings("ignore", category=FutureWarning)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _last_price_date(session, ticker: str) -> Optional[datetime]:
    from sqlalchemy import text as sqla_text
    row = session.execute(sqla_text(
        "SELECT MAX(date) FROM prices WHERE ticker=:t"
    ), {"t": ticker}).fetchone()
    if row and row[0]:
        return pd.Timestamp(row[0]).to_pydatetime()
    return None


def _is_stale(session, ticker: str) -> bool:
    cache_hours = get_config_value("prices", "cache_hours", default=4)
    from sqlalchemy import text as sqla_text
    row = session.execute(sqla_text(
        "SELECT MAX(fetched_at) FROM prices WHERE ticker=:t"
    ), {"t": ticker}).fetchone()
    if not row or not row[0]:
        return True
    last = pd.Timestamp(row[0]).to_pydatetime()
    return (datetime.utcnow() - last).total_seconds() > cache_hours * 3600


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_history(ticker: str, start: str, end: str) -> Optional[pd.DataFrame]:
    try:
        tkr = yf.Ticker(ticker)
        df = tkr.history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return None
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as exc:
        logger.warning(f"yfinance error for {ticker}: {exc}")
        return None


def _upsert_prices(session, ticker: str, df: pd.DataFrame) -> int:
    from sqlalchemy import text as sqla_text
    count = 0
    for ts, row in df.iterrows():
        date_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        session.execute(sqla_text("""
            INSERT INTO prices (ticker, date, open, high, low, close, adjusted_close, volume, fetched_at)
            VALUES (:ticker, :date, :open, :high, :low, :close, :adj, :vol, :fetched)
            ON CONFLICT(ticker, date) DO UPDATE SET
                close=excluded.close,
                adjusted_close=excluded.adjusted_close,
                volume=excluded.volume,
                fetched_at=excluded.fetched_at
        """), {
            "ticker": ticker,
            "date": date_str,
            "open": float(row.get("Open", 0) or 0),
            "high": float(row.get("High", 0) or 0),
            "low": float(row.get("Low", 0) or 0),
            "close": float(row.get("Close", 0) or 0),
            "adj": float(row.get("Close", 0) or 0),  # history() returns adjusted
            "vol": float(row.get("Volume", 0) or 0),
            "fetched": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        })
        count += 1
    session.commit()
    return count


def fetch_prices_for_tickers(tickers: List[str], force_refresh: bool = False) -> Dict[str, bool]:
    init_db()
    session = get_session()
    history_years = get_config_value("prices", "history_years", default=5)
    start_date = (datetime.now() - timedelta(days=history_years * 365)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    results: Dict[str, bool] = {}

    for ticker in tickers:
        if not ticker or ticker.strip() == "":
            continue
        ticker = ticker.upper().strip()

        if not force_refresh and not _is_stale(session, ticker):
            logger.debug(f"{ticker}: cache fresh, skipping")
            results[ticker] = True
            continue

        last = _last_price_date(session, ticker)
        fetch_start = last.strftime("%Y-%m-%d") if last else start_date

        logger.info(f"Fetching prices: {ticker} from {fetch_start}")
        df = _fetch_history(ticker, fetch_start, end_date)
        if df is None or df.empty:
            logger.warning(f"No price data for {ticker}")
            results[ticker] = False
            continue

        count = _upsert_prices(session, ticker, df)
        logger.info(f"  → {count} rows stored for {ticker}")
        results[ticker] = True

    return results


def get_latest_price(ticker: str) -> Optional[float]:
    session = get_session()
    from sqlalchemy import text as sqla_text
    row = session.execute(sqla_text(
        "SELECT adjusted_close FROM prices WHERE ticker=:t ORDER BY date DESC LIMIT 1"
    ), {"t": ticker}).fetchone()
    return float(row[0]) if row and row[0] else None


def get_price_on_date(ticker: str, target_date: datetime) -> Optional[float]:
    """Return adjusted_close closest to (and not after) target_date."""
    session = get_session()
    from sqlalchemy import text as sqla_text
    date_str = target_date.strftime("%Y-%m-%d %H:%M:%S")
    row = session.execute(sqla_text(
        "SELECT adjusted_close FROM prices WHERE ticker=:t AND date <= :d "
        "ORDER BY date DESC LIMIT 1"
    ), {"t": ticker, "d": date_str}).fetchone()
    return float(row[0]) if row and row[0] else None


def get_price_series(ticker: str) -> pd.Series:
    """Return full adjusted_close time series as pandas Series."""
    session = get_session()
    from sqlalchemy import text as sqla_text
    rows = session.execute(sqla_text(
        "SELECT date, adjusted_close FROM prices WHERE ticker=:t ORDER BY date ASC"
    ), {"t": ticker}).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    idx = pd.to_datetime([r[0] for r in rows])
    vals = [float(r[1]) if r[1] else None for r in rows]
    return pd.Series(vals, index=idx, name=ticker)


def refresh_all_tracked_prices(force: bool = False) -> None:
    """Refresh prices for all tickers in portfolio_holdings + benchmarks."""
    session = get_session()
    from sqlalchemy import text as sqla_text
    holdings = [row[0] for row in session.execute(
        sqla_text("SELECT DISTINCT ticker FROM portfolio_holdings WHERE active_status=1")
    )]
    benchmarks = get_config_value("portfolio", "benchmarks", default=["SPY", "QQQ", "URTH"])
    all_tickers = list(set(holdings + benchmarks))
    if not all_tickers:
        logger.info("No tickers to refresh")
        return
    logger.info(f"Refreshing prices for {len(all_tickers)} tickers")
    fetch_prices_for_tickers(all_tickers, force_refresh=force)
