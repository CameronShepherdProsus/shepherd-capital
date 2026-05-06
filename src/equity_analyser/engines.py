"""
Valuation engines: DCF (FCFF), Residual Income, Total Payout.

All engines return None if input data is insufficient.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

from .adjustments import compute_growth_rates, estimate_cost_of_equity, estimate_wacc
from .data_model import (
    DataPackage, DCFResult, PayoutResult, ResidualIncomeResult,
    SensitivityGrid,
)

logger = logging.getLogger(__name__)

_FORECAST_YEARS = 10
_STAGE2_START = 5
_TERMINAL_GROWTH = 0.025
_MAX_STAGE1_GROWTH = 0.30
_MIN_STAGE1_GROWTH = -0.05


def _clip_growth(g: float) -> float:
    return float(np.clip(g, _MIN_STAGE1_GROWTH, _MAX_STAGE1_GROWTH))


def run_dcf_fcff(pkg: DataPackage, terminal_growth: float = _TERMINAL_GROWTH) -> Optional[DCFResult]:
    """
    DCF using FCF from the cash flow statement as a FCFF proxy.
    Discounts at WACC where computable, else at cost of equity.
    EV bridge: subtract net debt to reach equity value.
    """
    base = pkg.ttm or (pkg.annual[0] if pkg.annual else None)
    if base is None:
        return None

    base_fcf = base.adj_fcf if base.adj_fcf is not None else base.reported_fcf
    if base_fcf is None or base_fcf <= 0:
        # Try reconstructing from CFO - capex
        cfo = base.reported_cfo
        capex = base.reported_capex
        if cfo is not None and capex is not None:
            base_fcf = cfo - capex
        if base_fcf is None or base_fcf <= 0:
            logger.debug(f"{pkg.profile.ticker}: non-positive base FCF; skipping DCF")
            return None

    # Historical growth rates (newest-first list → newest growth at index 0)
    growth_data = compute_growth_rates(pkg.annual)
    fcf_growths = [g["fcf_growth"] for g in growth_data if g.get("fcf_growth") is not None]
    rev_growths = [g["revenue_growth"] for g in growth_data if g.get("revenue_growth") is not None]

    raw_fcf_g = float(np.median(fcf_growths)) if len(fcf_growths) >= 2 else None
    raw_rev_g = float(np.median(rev_growths)) if rev_growths else None

    if raw_fcf_g is not None and raw_fcf_g >= 0:
        hist_growth = _clip_growth(raw_fcf_g)
    elif raw_rev_g is not None and raw_rev_g > 0:
        # FCF compressed by capex cycle — proxy via revenue growth at a discount
        # Weight 40% to FCF growth (floored at 0) and 60% to revenue growth
        fcf_floor = max(raw_fcf_g or 0, 0.0)
        hist_growth = _clip_growth(fcf_floor * 0.4 + raw_rev_g * 0.6)
    else:
        hist_growth = 0.04

    ke = estimate_cost_of_equity(pkg.market.beta)
    net_debt = base.adj_net_debt if base.adj_net_debt is not None else (base.reported_net_debt or 0)
    mv_equity = pkg.market.market_cap or 0
    wacc = estimate_wacc(ke, 0.05, 0.21, mv_equity, max(net_debt, 0))
    discount_rate = wacc if (wacc and wacc > terminal_growth) else ke

    # Ensure terminal_growth < discount_rate
    if terminal_growth >= discount_rate:
        terminal_growth = max(discount_rate - 0.015, 0.005)

    # Forecast FCFs: stage 1 (years 1-5 at hist_growth) → stage 2 (linear decay to terminal)
    curr_fcf = base_fcf
    forecast_fcfs: List[float] = []
    for t in range(1, _FORECAST_YEARS + 1):
        if t <= _STAGE2_START:
            g = hist_growth
        else:
            decay = (t - _STAGE2_START) / (_FORECAST_YEARS - _STAGE2_START)
            g = hist_growth + (terminal_growth - hist_growth) * decay
        curr_fcf = curr_fcf * (1 + g)
        forecast_fcfs.append(curr_fcf)

    pv_explicit = sum(f / (1 + discount_rate) ** t for t, f in enumerate(forecast_fcfs, 1))

    tv = forecast_fcfs[-1] * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_tv = tv / (1 + discount_rate) ** _FORECAST_YEARS

    equity_total = pv_explicit + pv_tv - net_debt

    shares = (base.adj_shares_diluted or base.reported_shares_diluted
              or pkg.market.shares_outstanding or 1)
    if shares <= 0:
        shares = 1

    ev_per_share = equity_total / shares

    # Sensitivity: Ke rows × g cols
    ke_range = [round(ke + d, 3) for d in (-0.02, -0.01, 0, 0.01, 0.02)]
    g_range = [round(terminal_growth + d, 3) for d in (-0.01, 0, 0.005, 0.01)]
    grid: List[List[float]] = []
    for ke_s in ke_range:
        row: List[float] = []
        for g_s in g_range:
            if g_s >= ke_s or ke_s <= 0:
                row.append(float("nan"))
                continue
            pv_e_s = sum(f / (1 + ke_s) ** t for t, f in enumerate(forecast_fcfs, 1))
            tv_s = forecast_fcfs[-1] * (1 + g_s) / (ke_s - g_s)
            pv_tv_s = tv_s / (1 + ke_s) ** _FORECAST_YEARS
            eq_s = (pv_e_s + pv_tv_s - net_debt) / shares
            row.append(round(eq_s, 2))
        grid.append(row)

    sensitivity = SensitivityGrid(
        row_label="Cost of equity (Ke)",
        col_label="Terminal growth (g)",
        row_values=ke_range,
        col_values=g_range,
        grid=grid,
    )

    return DCFResult(
        method="fcff",
        equity_value_per_share=round(max(ev_per_share, 0), 4),
        equity_value_total=round(max(equity_total, 0), 4),
        pv_explicit=round(pv_explicit, 4),
        pv_terminal=round(pv_tv, 4),
        terminal_value=round(tv, 4),
        cost_of_equity=ke,
        wacc=wacc,
        terminal_growth=terminal_growth,
        forecast_years=_FORECAST_YEARS,
        forecast_cash_flows=forecast_fcfs,
        discount_rates=[discount_rate] * _FORECAST_YEARS,
        ev_to_equity_bridge={"net_debt_deducted": round(net_debt, 2)},
        sensitivity=sensitivity,
        notes=[
            f"Base FCF (TTM/latest annual): {base_fcf:.0f}m",
            f"Stage-1 growth (years 1-{_STAGE2_START}): {hist_growth:.1%}",
            f"Terminal growth: {terminal_growth:.1%}",
            f"Discount rate: {discount_rate:.1%} ({'WACC' if wacc else 'Ke'})",
        ],
    )


def run_residual_income(pkg: DataPackage) -> Optional[ResidualIncomeResult]:
    """
    Edwards-Bell-Ohlson residual income model.
    Equity value = BVps + PV(RI stream, fading ROE → Ke over 10 years).
    """
    base = pkg.ttm or (pkg.annual[0] if pkg.annual else None)
    if base is None:
        return None

    # Book value per share
    bv = base.adj_book_value if base.adj_book_value is not None else base.reported_book_value
    shares = (base.adj_shares_diluted or base.reported_shares_diluted
              or pkg.market.shares_outstanding or 1)
    if not bv or bv <= 0 or shares <= 0:
        return None

    bvps = bv / shares
    ke = estimate_cost_of_equity(pkg.market.beta)

    # Compute ROE correctly as NI_t / BV_{t-1}.
    # pkg.annual is newest-first so pkg.annual[i+1] is the prior year.
    correct_roes: List[float] = []
    for i in range(len(pkg.annual) - 1):
        curr_n = pkg.annual[i]
        prev_n = pkg.annual[i + 1]
        ni_v = curr_n.adj_net_income or curr_n.reported_net_income
        bv_prev = prev_n.adj_book_value or prev_n.reported_book_value
        if ni_v is not None and bv_prev and bv_prev > 0:
            correct_roes.append(ni_v / bv_prev)

    if correct_roes:
        forecast_roe = float(np.clip(np.mean(correct_roes[:3]), 0.0, 0.60))
    else:
        ni = base.adj_net_income if base.adj_net_income is not None else base.reported_net_income
        if ni and bv and bv > 0:
            forecast_roe = float(np.clip(ni / bv, 0.0, 0.60))
        else:
            return None

    # Payout ratio (dividend + buybacks / NI, capped at 95%)
    divs = base.reported_dividends or 0
    buybacks = base.reported_buybacks or 0
    ni_base = abs(base.reported_net_income or 1)
    total_payout_ratio = min((divs + buybacks) / ni_base, 0.95) if ni_base > 0 else 0
    retention = 1.0 - total_payout_ratio

    forecast_ri: List[float] = []
    forecast_roe_list: List[float] = []
    forecast_bvps_list: List[float] = []

    curr_bvps = bvps
    for t in range(1, _FORECAST_YEARS + 1):
        # Fade ROE linearly from forecast_roe to Ke (zero RI at terminal)
        fade = t / _FORECAST_YEARS
        period_roe = forecast_roe * (1 - fade) + ke * fade
        eps = curr_bvps * period_roe
        ri = eps - ke * curr_bvps

        forecast_ri.append(ri)
        forecast_roe_list.append(period_roe)
        forecast_bvps_list.append(curr_bvps)

        curr_bvps = curr_bvps + eps * retention

    pv_ri = sum(ri / (1 + ke) ** t for t, ri in enumerate(forecast_ri, 1))

    equity_per_share = bvps + pv_ri  # terminal RI assumed zero (RI fades to 0)

    return ResidualIncomeResult(
        equity_value_per_share=round(max(equity_per_share, 0), 4),
        opening_book_value_per_share=round(bvps, 4),
        pv_residual_income=round(pv_ri, 4),
        pv_terminal=0.0,
        cost_of_equity=ke,
        forecast_roe=forecast_roe_list,
        forecast_ri=forecast_ri,
        forecast_bvps=forecast_bvps_list,
        notes=[
            f"Opening BVps: {bvps:.2f}",
            f"Forecast ROE: {forecast_roe:.1%} → {ke:.1%} (fades over 10y)",
            f"Retention rate: {retention:.0%}",
        ],
    )


def run_payout(pkg: DataPackage) -> Optional[PayoutResult]:
    """
    Total shareholder return model (dividends + buybacks per share).
    Only runs if TTM payout > 0.5% of current price.
    """
    base = pkg.ttm or (pkg.annual[0] if pkg.annual else None)
    if base is None:
        return None

    shares = (base.adj_shares_diluted or base.reported_shares_diluted
              or pkg.market.shares_outstanding or 1)
    if shares <= 0:
        return None

    divs = base.reported_dividends or 0
    buybacks = base.reported_buybacks or 0
    total_payout = divs + buybacks
    if total_payout <= 0:
        return None

    payout_per_share = total_payout / shares
    # Require at least 0.5% yield to bother running the model
    if payout_per_share / max(pkg.market.price, 1) < 0.005:
        return None

    ke = estimate_cost_of_equity(pkg.market.beta)
    terminal_growth = _TERMINAL_GROWTH
    if ke <= terminal_growth:
        return None

    # Historical payout growth (oldest-to-newest)
    payout_by_year = []
    for n in reversed(pkg.annual):
        p = (n.reported_dividends or 0) + (n.reported_buybacks or 0)
        payout_by_year.append(p)

    payout_growths = []
    for i in range(1, len(payout_by_year)):
        prev = payout_by_year[i - 1]
        curr = payout_by_year[i]
        if prev and prev > 0:
            payout_growths.append(curr / prev - 1)

    hist_g = float(np.clip(np.median(payout_growths), 0.0, 0.20)) if payout_growths else 0.05

    forecast_payouts: List[float] = []
    curr = payout_per_share
    for _ in range(1, 6):
        curr = curr * (1 + hist_g)
        forecast_payouts.append(curr)

    pv_explicit = sum(p / (1 + ke) ** t for t, p in enumerate(forecast_payouts, 1))
    tv = forecast_payouts[-1] * (1 + terminal_growth) / (ke - terminal_growth)
    pv_tv = tv / (1 + ke) ** 5

    equity_per_share = pv_explicit + pv_tv

    return PayoutResult(
        method="total_payout",
        equity_value_per_share=round(max(equity_per_share, 0), 4),
        cost_of_equity=ke,
        terminal_growth=terminal_growth,
        forecast_payouts=forecast_payouts,
        pv_explicit=round(pv_explicit, 4),
        pv_terminal=round(pv_tv, 4),
        notes=[
            f"TTM payout/share: {payout_per_share:.2f}",
            f"Payout growth (hist): {hist_g:.1%}",
        ],
    )
