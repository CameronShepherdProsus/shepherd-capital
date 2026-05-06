"""
Orchestrates fetch → validate → model → consensus → verdict for one ticker.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from .consensus import build_synthetic_consensus, derive_verdict
from .data_model import ValuationOutput
from .engines import run_dcf_fcff, run_payout, run_residual_income
from .fetcher import fetch_data_package
from .validation import run_all_validations

logger = logging.getLogger(__name__)

_FINANCIAL_SECTORS = {"Financial Services", "Financials", "Banks", "Insurance"}


def run_valuation(ticker: str) -> Optional[ValuationOutput]:
    """
    Full valuation pipeline for one ticker.
    Returns ValuationOutput (possibly without a verdict if data is insufficient).
    """
    pkg = fetch_data_package(ticker)
    if pkg is None:
        logger.warning(f"{ticker}: no data package")
        return None

    # Validation (non-blocking — we proceed even on hard fails but flag them)
    val = run_all_validations(
        raw_annual=pkg.raw_annual,
        normalised=pkg.annual,
        reporting_currency=pkg.profile.reporting_currency,
        valuation_currency=pkg.profile.valuation_currency,
        fx_rate=1.0,
    )

    flags = list(pkg.data_quality_flags)
    for issue in val.hard_failures():
        flags.append(f"[hard fail] {issue.message}")
    for issue in val.soft_failures():
        flags.append(f"[soft fail] {issue.message}")

    # Valuation models
    dcf = run_dcf_fcff(pkg)
    ri = run_residual_income(pkg)
    payout = run_payout(pkg)

    is_financial = (pkg.profile.sector or "") in _FINANCIAL_SECTORS

    consensus = build_synthetic_consensus(
        dcf_result=dcf,
        ri_result=ri,
        payout_result=payout,
        comp_result=None,
        is_financial=is_financial,
    )

    verdict = derive_verdict(consensus, pkg.market.price) if consensus else None

    # Confidence: downgrade if hard fails or limited data
    confidence = val.confidence
    if val.hard_failures():
        confidence = "low"

    return ValuationOutput(
        company=pkg.profile,
        market=pkg.market,
        valuation_date=date.today(),
        dcf_fcff=dcf,
        residual_income=ri,
        total_payout=payout,
        consensus=consensus,
        verdict=verdict,
        data_quality_flags=flags,
        confidence=confidence,
        provenance=pkg.provenance,
    )
