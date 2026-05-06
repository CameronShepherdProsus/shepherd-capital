"""
Unit tests for extraction, classification, and portfolio logic.
"""
from __future__ import annotations

import pytest
from datetime import datetime


# ---------------------------------------------------------------------------
# Ticker extraction tests
# ---------------------------------------------------------------------------

class TestTickerExtraction:

    def _extract(self, text: str):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.extract_recommendations import extract_from_text
        return extract_from_text(text, source_id=999, pub_date=datetime(2024, 1, 1))

    def test_basic_ticker(self):
        results = self._extract("We like AAPL as a long-term hold.")
        tickers = [r["ticker"] for r in results]
        assert "AAPL" in tickers

    def test_exchange_prefixed_ticker(self):
        results = self._extract("Our top pick is NASDAQ:MSFT right now.")
        tickers = [r["ticker"] for r in results]
        assert "MSFT" in tickers

    def test_false_positives_excluded(self):
        results = self._extract("The CEO of the US company said AI is the future and ROI is improving.")
        tickers = [r["ticker"] for r in results]
        for fp in ["CEO", "US", "AI", "ROI", "THE"]:
            assert fp not in tickers

    def test_multiple_tickers(self):
        results = self._extract("We hold AAPL, MSFT, and GOOGL in the portfolio.")
        tickers = [r["ticker"] for r in results]
        assert len(tickers) >= 3

    def test_lon_exchange(self):
        results = self._extract("LON:VOD is an interesting UK play.")
        tickers = [r["ticker"] for r in results]
        exchanges = [r["exchange"] for r in results]
        assert "VOD" in tickers
        assert "LSE" in exchanges or "LON" in exchanges

    def test_no_duplicates(self):
        results = self._extract("AAPL is great. We love AAPL. Buy AAPL.")
        tickers = [r["ticker"] for r in results]
        assert tickers.count("AAPL") == 1


# ---------------------------------------------------------------------------
# Recommendation classification tests
# ---------------------------------------------------------------------------

class TestClassification:

    def _classify(self, text: str):
        from src.extract_recommendations import classify_recommendation
        return classify_recommendation(text)

    def test_buy_classification(self):
        rec_type, conf = self._classify("We are initiating a buy on this stock.")
        assert rec_type == "buy"

    def test_long_classification(self):
        rec_type, conf = self._classify("This is a long idea we like a lot.")
        assert rec_type in ("long", "buy")

    def test_sell_classification(self):
        rec_type, conf = self._classify("We are exiting this position and selling our shares.")
        assert rec_type == "sell"

    def test_short_classification(self):
        rec_type, conf = self._classify("We are shorting this name on valuation concerns.")
        assert rec_type == "short"

    def test_watchlist_classification(self):
        rec_type, conf = self._classify("We are keeping an eye on this one for the watchlist.")
        assert rec_type == "watchlist"

    def test_avoid_classification(self):
        rec_type, conf = self._classify("We would avoid this company entirely.")
        assert rec_type == "avoid"

    def test_portfolio_holding_classification(self):
        rec_type, conf = self._classify("This is a current portfolio holding.")
        assert rec_type == "portfolio_holding"

    def test_mention_only_fallback(self):
        rec_type, conf = self._classify("AAPL released earnings last week.")
        assert rec_type == "mention_only"

    def test_high_confidence_buy(self):
        _, conf = self._classify("We are initiating a buy on this stock.")
        assert conf == "high"


# ---------------------------------------------------------------------------
# Duplicate URL handling tests
# ---------------------------------------------------------------------------

class TestDuplicateURLHandling:

    def test_normalise_url_strips_fragment(self):
        from src.utils import normalise_url
        assert normalise_url("https://example.com/p/post#comments") == "https://example.com/p/post"

    def test_normalise_url_strips_trailing_slash(self):
        from src.utils import normalise_url
        assert normalise_url("https://example.com/p/post/") == "https://example.com/p/post"

    def test_content_hash_deterministic(self):
        from src.utils import content_hash
        assert content_hash("hello world") == content_hash("hello world")

    def test_content_hash_differs(self):
        from src.utils import content_hash
        assert content_hash("hello") != content_hash("world")


# ---------------------------------------------------------------------------
# Portfolio weighting tests
# ---------------------------------------------------------------------------

class TestPortfolioWeighting:

    def _build_candidates(self, n: int):
        import pandas as pd
        return pd.DataFrame([
            {
                "ticker": f"TICK{i}",
                "company_name": f"Company {i}",
                "first_date": datetime(2023, 1, i + 1),
                "latest_date": datetime(2024, 1, i + 1),
                "mention_count": i + 1,
                "avg_confidence": (i % 3) + 1,
                "confidence_sum": (i % 3) + 1,
                "is_stale": False,
            }
            for i in range(n)
        ])

    def test_equal_weight_sums_to_one(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import patch
        from src.portfolio_builder import compute_weights

        df = self._build_candidates(5)
        with patch("src.portfolio_builder.get_config_value", return_value="equal"):
            weights = compute_weights(df)
        assert abs(weights.sum() - 1.0) < 1e-6

    def test_equal_weights_are_uniform(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import patch
        from src.portfolio_builder import compute_weights

        df = self._build_candidates(4)
        with patch("src.portfolio_builder.get_config_value", return_value="equal"):
            weights = compute_weights(df)
        assert all(abs(w - 0.25) < 1e-6 for w in weights)

    def test_frequency_weight_sums_to_one(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import patch
        from src.portfolio_builder import compute_weights

        df = self._build_candidates(5)
        with patch("src.portfolio_builder.get_config_value", return_value="frequency"):
            weights = compute_weights(df)
        assert abs(weights.sum() - 1.0) < 1e-6

    def test_recency_weight_sums_to_one(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import patch
        from src.portfolio_builder import compute_weights

        df = self._build_candidates(5)
        with patch("src.portfolio_builder.get_config_value", return_value="recency"):
            weights = compute_weights(df)
        assert abs(weights.sum() - 1.0) < 1e-6

    def test_empty_candidates_returns_empty(self):
        import sys
        import pandas as pd
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.portfolio_builder import compute_weights

        weights = compute_weights(pd.DataFrame())
        assert len(weights) == 0


# ---------------------------------------------------------------------------
# Metadata extraction tests
# ---------------------------------------------------------------------------

class TestMetadataExtraction:

    def test_target_price_extraction(self):
        from src.extract_recommendations import extract_metadata
        meta = extract_metadata("We have a target price of $250 for this stock.")
        assert meta["target_price"] == 250.0

    def test_time_horizon_extraction(self):
        from src.extract_recommendations import extract_metadata
        meta = extract_metadata("We see this playing out over 2-3 years.")
        assert meta["time_horizon"] is not None
        assert "year" in meta["time_horizon"].lower()

    def test_catalyst_extraction(self):
        from src.extract_recommendations import extract_metadata
        meta = extract_metadata("Key catalyst: new product launch in Q2.")
        assert "catalyst" in meta.get("catalysts", "").lower() or "product" in meta.get("catalysts", "").lower()

    def test_risk_extraction(self):
        from src.extract_recommendations import extract_metadata
        meta = extract_metadata("The main risk is rising interest rates.")
        assert meta["risks"] is not None and len(meta["risks"]) > 0
