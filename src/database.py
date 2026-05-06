"""
SQLAlchemy models and database helpers for Rebound Capital Tracker.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, String, Text,
    create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.utils import load_config

# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_type = Column(String(50))          # substack | website
    url = Column(String(2048), unique=True, nullable=False)
    title = Column(String(512))
    author = Column(String(256))
    published_date = Column(DateTime)
    fetched_at = Column(DateTime)
    content_hash = Column(String(64))
    raw_html_path = Column(String(512))
    parsed_text_path = Column(String(512))
    status = Column(String(50), default="pending")  # pending | fetched | parsed | error | skipped


class ExtractedRecommendation(Base):
    __tablename__ = "extracted_recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, nullable=False)
    company_name = Column(String(256))
    ticker = Column(String(32))
    exchange = Column(String(32))
    recommendation_type = Column(String(64))  # buy | long | add | hold | watchlist | trim | sell | short | avoid | portfolio_holding | mention_only
    confidence = Column(String(32), default="unknown")  # high | medium | low | unknown
    recommendation_date = Column(DateTime)
    excerpt = Column(Text)
    thesis_summary = Column(Text)
    catalysts = Column(Text)
    risks = Column(Text)
    target_price = Column(Float)
    time_horizon = Column(String(128))
    valuation_metrics = Column(Text)
    extraction_method = Column(String(64))  # regex | nlp | llm
    extraction_confidence = Column(Float)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TickerMap(Base):
    __tablename__ = "ticker_map"

    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String(256), unique=True, nullable=False)
    ticker = Column(String(32))
    exchange = Column(String(32))
    confidence = Column(Float, default=0.0)
    source = Column(String(64))             # manual | yfinance | regex
    manual_override = Column(Boolean, default=False)


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(32), nullable=False)
    date = Column(DateTime, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    adjusted_close = Column(Float)
    volume = Column(Float)
    fetched_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # composite unique to avoid duplicate rows
        {"sqlite_autoincrement": False},
    )


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(32), nullable=False, unique=True)
    company_name = Column(String(256))
    entry_date = Column(DateTime)
    entry_price = Column(Float)
    current_price = Column(Float)
    weight = Column(Float)
    shares = Column(Float)
    market_value = Column(Float)
    total_return = Column(Float)
    active_status = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class FundPerformance(Base):
    __tablename__ = "fund_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(DateTime, nullable=False, unique=True)
    fund_value = Column(Float)
    daily_return = Column(Float)
    cumulative_return = Column(Float)
    benchmark_spy = Column(Float)
    benchmark_qqq = Column(Float)
    benchmark_world = Column(Float)


# ---------------------------------------------------------------------------
# Engine / session factory
# ---------------------------------------------------------------------------

_engine = None
_session: Optional[Session] = None


def get_engine():
    global _engine
    if _engine is None:
        cfg = load_config()
        db_path = Path(cfg.get("output", {}).get("database_path", "data/rebound_tracker.sqlite"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # StaticPool keeps a single connection — correct for SQLite in a single-process CLI/dashboard.
        # check_same_thread=False allows the session to be shared across Streamlit rerenders.
        from sqlalchemy.pool import StaticPool
        _engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return _engine


def get_session() -> Session:
    """Return a module-level singleton session (safe for SQLite single-process use)."""
    global _session
    if _session is None:
        _session = sessionmaker(bind=get_engine())()
    return _session


def init_db() -> None:
    """Create all tables (safe to call multiple times)."""
    Base.metadata.create_all(get_engine(), checkfirst=True)

    # Add unique index on prices(ticker, date) if not present
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uix_price_ticker_date "
            "ON prices(ticker, date)"
        ))
        conn.commit()
