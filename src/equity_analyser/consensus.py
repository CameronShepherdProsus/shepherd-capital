"""
Synthetic consensus fair price aggregator.
"""
from __future__ import annotations

import statistics
from typing import Dict, Optional

from .data_model import (
    DCFResult, ResidualIncomeResult, PayoutResult, ComparablesResult,
    SyntheticConsensus, Verdict,
)


DEFAULT_WEIGHTS_NON_FINANCIAL = {
    "dcf":              0.35,
    "residual_income":  0.25,
    "payout":           0.15,
    "comparables":      0.25,
}

DEFAULT_WEIGHTS_FINANCIAL = {
    "dcf":              0.10,
    "residual_income":  0.45,
    "payout":           0.20,
    "comparables":      0.25,
}


def build_synthetic_consensus(
    dcf_result: Optional[DCFResult],
    ri_result: Optional[ResidualIncomeResult],
    payout_result: Optional[PayoutResult],
    comp_result: Optional[ComparablesResult],
    is_financial: bool = False,
    custom_weights: Optional[Dict[str, float]] = None,
) -> Optional[SyntheticConsensus]:
    weights = custom_weights or (
        DEFAULT_WEIGHTS_FINANCIAL if is_financial else DEFAULT_WEIGHTS_NON_FINANCIAL
    )

    component_values: Dict[str, float] = {}
    component_weights: Dict[str, float] = {}

    if dcf_result and dcf_result.equity_value_per_share > 0:
        component_values["dcf"] = dcf_result.equity_value_per_share
        component_weights["dcf"] = weights.get("dcf", 0.35)

    if ri_result and ri_result.equity_value_per_share > 0:
        component_values["residual_income"] = ri_result.equity_value_per_share
        component_weights["residual_income"] = weights.get("residual_income", 0.25)

    if payout_result and payout_result.equity_value_per_share > 0:
        component_values["payout"] = payout_result.equity_value_per_share
        component_weights["payout"] = weights.get("payout", 0.15)

    if comp_result and comp_result.equity_value_per_share > 0:
        component_values["comparables"] = comp_result.equity_value_per_share
        component_weights["comparables"] = weights.get("comparables", 0.25)

    if not component_values:
        return None

    total_w = sum(component_weights.values())
    if total_w <= 0:
        return None
    norm_weights = {k: v / total_w for k, v in component_weights.items()}

    fair_value = sum(
        component_values[k] * norm_weights[k]
        for k in component_values
    )

    all_values = list(component_values.values())
    low = min(all_values)
    high = max(all_values)

    if len(all_values) >= 2:
        std = statistics.stdev(all_values)
        dispersion_pct = std / fair_value if fair_value else None
    else:
        dispersion_pct = None

    notes = [
        "Synthetic consensus from intrinsic models (no broker target prices used)",
        f"Models included: {', '.join(component_values.keys())}",
    ]
    if len(component_values) < 3:
        notes.append(
            f"Only {len(component_values)} model(s) available — "
            "fair-value range is less robust; treat with caution"
        )

    return SyntheticConsensus(
        fair_value_per_share=round(fair_value, 4),
        low=round(low, 4),
        high=round(high, 4),
        method="synthetic_consensus",
        analyst_count=None,
        dispersion_pct=round(dispersion_pct, 4) if dispersion_pct else None,
        component_values={k: round(v, 4) for k, v in component_values.items()},
        component_weights={k: round(v, 4) for k, v in norm_weights.items()},
        notes=notes,
    )


def derive_verdict(
    consensus: SyntheticConsensus,
    current_price: float,
    verdict_buffer_pct: float = 0.10,
) -> Verdict:
    low = consensus.low
    high = consensus.high
    mid = consensus.fair_value_per_share

    undervalue_threshold = low * (1 - verdict_buffer_pct)
    overvalue_threshold = high * (1 + verdict_buffer_pct)

    upside = (mid - current_price) / current_price if current_price else 0.0

    if current_price < undervalue_threshold:
        label = "undervalued"
        rationale = (
            f"Price ({current_price:.2f}) is >{verdict_buffer_pct:.0%} below the "
            f"fair-value low ({low:.2f}). Implied upside to mid: {upside:+.1%}."
        )
    elif current_price > overvalue_threshold:
        label = "overvalued"
        rationale = (
            f"Price ({current_price:.2f}) is >{verdict_buffer_pct:.0%} above the "
            f"fair-value high ({high:.2f}). Implied downside to mid: {upside:+.1%}."
        )
    else:
        label = "fairly_valued"
        rationale = (
            f"Price ({current_price:.2f}) is within the fair-value range "
            f"({low:.2f} – {high:.2f}) with {verdict_buffer_pct:.0%} buffer. "
            f"Upside to mid: {upside:+.1%}."
        )

    return Verdict(
        label=label,
        upside_downside_pct=round(upside, 4),
        current_price=round(current_price, 4),
        fair_value_mid=round(mid, 4),
        fair_value_low=round(low, 4),
        fair_value_high=round(high, 4),
        verdict_buffer_pct=verdict_buffer_pct,
        rationale=rationale,
    )
