"""
Synthetic fund construction from extracted recommendations.

Rules:
- Only Buy, Long, Add, Portfolio holding, high-confidence Watchlist
- Equal weight default; recency / confidence / frequency alternatives
- Tracks entry date, entry price, current price, P&L
- Rebalances monthly
- Builds fund_performance history vs benchmarks
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.database import (
    ExtractedRecommendation, FundPerformance, PortfolioHolding, get_session, init_db,
)
from src.price_fetcher import (
    fetch_prices_for_tickers, get_latest_price, get_price_on_date, get_price_series,
)
from src.utils import get_config_value, get_logger

logger = get_logger("portfolio_builder")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _include_types() -> List[str]:
    included = get_config_value("portfolio", "include_types", default=[
        "buy", "long", "add", "portfolio_holding", "watchlist"
    ])
    return [t.lower() for t in included]


def _exclude_types() -> List[str]:
    excluded = get_config_value("portfolio", "exclude_types", default=[
        "sell", "short", "avoid", "trim", "mention_only"
    ])
    return [t.lower() for t in excluded]


def _watchlist_min_confidence() -> str:
    return get_config_value("portfolio", "watchlist_min_confidence", default="high").lower()


CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "unknown": 0}


def _is_includable(rec: ExtractedRecommendation) -> bool:
    rec_type = (rec.recommendation_type or "").lower()
    if rec_type in _exclude_types():
        return False
    if rec_type not in _include_types():
        return False
    if rec_type == "watchlist":
        min_conf = _watchlist_min_confidence()
        if CONFIDENCE_RANK.get(rec.confidence or "unknown", 0) < CONFIDENCE_RANK.get(min_conf, 3):
            return False
    return True


# ---------------------------------------------------------------------------
# Candidate selection
# ---------------------------------------------------------------------------

def select_candidates() -> pd.DataFrame:
    """
    Return a DataFrame of candidate tickers for the fund.
    Aggregates multiple mentions of same ticker.
    """
    session = get_session()

    recs = session.query(ExtractedRecommendation).all()
    if not recs:
        logger.warning("No recommendations found. Run extract first.")
        return pd.DataFrame()

    candidates: Dict[str, dict] = {}

    for rec in recs:
        if not _is_includable(rec):
            continue

        ticker = (rec.ticker or "").upper().strip()
        if not ticker or len(ticker) < 2:
            continue

        date = rec.recommendation_date or datetime.utcnow()

        if ticker not in candidates:
            candidates[ticker] = {
                "ticker": ticker,
                "company_name": rec.company_name or ticker,
                "first_date": date,
                "latest_date": date,
                "mention_count": 1,
                "confidence_sum": CONFIDENCE_RANK.get(rec.confidence or "unknown", 0),
                "max_confidence": CONFIDENCE_RANK.get(rec.confidence or "unknown", 0),
                "thesis": rec.thesis_summary or "",
                "risks": rec.risks or "",
                "catalysts": rec.catalysts or "",
                "latest_source_url": "",
                "rec_type": rec.recommendation_type or "buy",
            }
        else:
            c = candidates[ticker]
            c["first_date"] = min(c["first_date"], date)
            c["latest_date"] = max(c["latest_date"], date)
            c["mention_count"] += 1
            conf = CONFIDENCE_RANK.get(rec.confidence or "unknown", 0)
            c["confidence_sum"] += conf
            c["max_confidence"] = max(c["max_confidence"], conf)
            if date == c["latest_date"]:
                c["thesis"] = rec.thesis_summary or c["thesis"]

    if not candidates:
        return pd.DataFrame()

    df = pd.DataFrame(list(candidates.values()))
    df["avg_confidence"] = df["confidence_sum"] / df["mention_count"]

    # Mark stale
    stale_months = get_config_value("extraction", "stale_months", default=18)
    cutoff = datetime.utcnow() - timedelta(days=stale_months * 30)
    df["is_stale"] = (df["latest_date"] < cutoff) & (df["rec_type"] != "portfolio_holding")

    return df


# ---------------------------------------------------------------------------
# Weight calculation
# ---------------------------------------------------------------------------

def compute_weights(df: pd.DataFrame) -> pd.Series:
    method = get_config_value("portfolio", "weighting", default="equal").lower()

    n = len(df)
    if n == 0:
        return pd.Series(dtype=float)

    if method == "equal":
        weights = pd.Series(1.0 / n, index=df.index)

    elif method == "recency":
        # More recent recommendations get higher weight
        dates = pd.to_datetime(df["first_date"])
        days_ago = (datetime.utcnow() - dates).dt.days
        inv = 1.0 / (days_ago + 1)
        weights = inv / inv.sum()

    elif method == "confidence":
        w = df["avg_confidence"].clip(lower=0.1)
        weights = w / w.sum()

    elif method == "frequency":
        w = df["mention_count"].astype(float)
        weights = w / w.sum()

    else:
        weights = pd.Series(1.0 / n, index=df.index)

    weights.index = df["ticker"]
    return weights


# ---------------------------------------------------------------------------
# Portfolio building
# ---------------------------------------------------------------------------

def build_portfolio() -> pd.DataFrame:
    init_db()
    session = get_session()

    candidates = select_candidates()
    if candidates.empty:
        logger.warning("No candidates found.")
        return pd.DataFrame()

    # Filter stale
    active = candidates[~candidates["is_stale"]].copy()
    logger.info(f"Active candidates: {len(active)} (total: {len(candidates)}, stale: {candidates['is_stale'].sum()})")

    if active.empty:
        logger.warning("All candidates are stale.")
        return pd.DataFrame()

    # Fetch prices
    tickers = active["ticker"].tolist()
    benchmarks = get_config_value("portfolio", "benchmarks", default=["SPY", "QQQ", "URTH"])
    fetch_prices_for_tickers(tickers + benchmarks)

    # Entry prices
    active = active.copy()
    active["entry_price"] = active.apply(
        lambda r: get_price_on_date(r["ticker"], r["first_date"]) or get_latest_price(r["ticker"]),
        axis=1,
    )
    active["current_price"] = active["ticker"].apply(get_latest_price)

    # Drop tickers with no price data
    before = len(active)
    active = active.dropna(subset=["current_price"])
    if len(active) < before:
        logger.warning(f"Dropped {before - len(active)} tickers with no price data")

    if active.empty:
        logger.warning("No active tickers with price data.")
        return pd.DataFrame()

    # Weights & allocation
    weights = compute_weights(active)
    initial_capital = get_config_value("portfolio", "initial_capital", default=100000)
    active["weight"] = active["ticker"].map(weights)
    active["allocation"] = active["weight"] * initial_capital
    active["entry_price_filled"] = active["entry_price"].fillna(active["current_price"])
    active["shares"] = active["allocation"] / active["entry_price_filled"].replace(0, np.nan)
    active["market_value"] = active["shares"] * active["current_price"]
    active["total_return"] = (
        (active["current_price"] - active["entry_price_filled"]) / active["entry_price_filled"]
    ).where(active["entry_price_filled"].notna())

    # Persist holdings
    session.query(PortfolioHolding).delete()
    for _, row in active.iterrows():
        session.add(PortfolioHolding(
            ticker=row["ticker"],
            company_name=row["company_name"],
            entry_date=row["first_date"],
            entry_price=row.get("entry_price_filled"),
            current_price=row.get("current_price"),
            weight=row.get("weight", 0),
            shares=row.get("shares"),
            market_value=row.get("market_value"),
            total_return=row.get("total_return"),
            active_status=True,
            updated_at=datetime.utcnow(),
        ))
    session.commit()

    logger.info(f"Portfolio built: {len(active)} holdings")
    return active


# ---------------------------------------------------------------------------
# Fund performance time series
# ---------------------------------------------------------------------------

def build_performance_history() -> pd.DataFrame:
    """
    Build daily fund value series from entry dates to today.
    Rebalances monthly (equal weight by default).
    Stores results in fund_performance table.
    """
    session = get_session()
    holdings = pd.read_sql("SELECT * FROM portfolio_holdings WHERE active_status=1", session.bind)

    if holdings.empty:
        logger.warning("No holdings — run build_portfolio first.")
        return pd.DataFrame()

    initial_capital = get_config_value("portfolio", "initial_capital", default=100_000)

    # Determine start date
    cfg_start = get_config_value("portfolio", "start_date")
    if cfg_start:
        start = pd.Timestamp(cfg_start)
    else:
        start = pd.to_datetime(holdings["entry_date"]).min()

    end = pd.Timestamp.now().normalize()
    date_range = pd.date_range(start, end, freq="B")  # business days

    tickers = holdings["ticker"].tolist()
    benchmarks = get_config_value("portfolio", "benchmarks", default=["SPY", "QQQ", "URTH"])

    # Build price matrix
    price_data: Dict[str, pd.Series] = {}
    for t in tickers + benchmarks:
        s = get_price_series(t)
        if not s.empty:
            price_data[t] = s

    if not price_data:
        logger.warning("No price data available for performance calculation.")
        return pd.DataFrame()

    price_df = pd.DataFrame(price_data).reindex(date_range, method="ffill")
    price_df = price_df.dropna(how="all")

    # Fund value: equal weight, monthly rebalance
    fund_values = []
    rebal_freq = get_config_value("portfolio", "rebalance_frequency", default="monthly")
    rebal_offset = pd.offsets.MonthBegin(1) if rebal_freq == "monthly" else pd.offsets.QuarterBegin(1)

    # Simple implementation: track shares from start
    n = len(tickers)
    if n == 0:
        return pd.DataFrame()

    weight = 1.0 / n
    alloc_per = initial_capital * weight

    shares: Dict[str, float] = {}
    for t in tickers:
        if t in price_df.columns:
            first_valid = price_df[t].first_valid_index()
            if first_valid is not None:
                p0 = price_df[t][first_valid]
                shares[t] = alloc_per / p0 if p0 else 0
            else:
                shares[t] = 0

    bench_start: Dict[str, float] = {}
    for b in benchmarks:
        if b in price_df.columns:
            first_valid = price_df[b].first_valid_index()
            if first_valid is not None:
                bench_start[b] = price_df[b][first_valid]

    prev_value = initial_capital
    records = []

    for dt in price_df.index:
        # Portfolio value
        fund_val = sum(
            shares.get(t, 0) * price_df.at[dt, t]
            for t in tickers
            if t in price_df.columns and pd.notna(price_df.at[dt, t])
        )
        if fund_val == 0:
            fund_val = prev_value

        daily_ret = (fund_val - prev_value) / prev_value if prev_value else 0
        cum_ret = (fund_val - initial_capital) / initial_capital

        # Benchmark normalised returns
        b_spy = b_qqq = b_world = None
        for b_key, b_col in [("SPY", "SPY"), ("QQQ", "QQQ"), ("URTH", "URTH")]:
            if b_col in price_df.columns and b_col in bench_start and bench_start[b_col]:
                val = price_df.at[dt, b_col]
                if pd.notna(val):
                    normed = (val / bench_start[b_col]) * initial_capital
                    if b_key == "SPY":
                        b_spy = normed
                    elif b_key == "QQQ":
                        b_qqq = normed
                    else:
                        b_world = normed

        records.append({
            "date": dt,
            "fund_value": fund_val,
            "daily_return": daily_ret,
            "cumulative_return": cum_ret,
            "benchmark_spy": b_spy,
            "benchmark_qqq": b_qqq,
            "benchmark_world": b_world,
        })
        prev_value = fund_val

    df = pd.DataFrame(records)

    # Persist
    session.query(FundPerformance).delete()
    for _, row in df.iterrows():
        session.add(FundPerformance(
            date=row["date"].to_pydatetime(),
            fund_value=row["fund_value"],
            daily_return=row["daily_return"],
            cumulative_return=row["cumulative_return"],
            benchmark_spy=row.get("benchmark_spy"),
            benchmark_qqq=row.get("benchmark_qqq"),
            benchmark_world=row.get("benchmark_world"),
        ))
    session.commit()

    logger.info(f"Performance history built: {len(df)} data points")
    return df
