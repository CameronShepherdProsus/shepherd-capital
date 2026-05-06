"""
Normalisation and adjustment layer.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional, Tuple

from .data_model import (
    AnnualFinancials, NormalisedFinancials, PeriodKey, FiscalPeriod,
    DataStatus, AccountingStandard,
)

logger = logging.getLogger(__name__)


def _safe_div(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def normalise_annual(
    financials: List[AnnualFinancials],
    include_leases_in_debt: bool = True,
    fx_rate: float = 1.0,
    normalised_tax_rate: Optional[float] = None,
) -> List[NormalisedFinancials]:
    results = []
    for af in financials:
        inc = af.income
        bs = af.balance
        cf = af.cashflow

        rep_rev = inc.revenue
        rep_ebit = inc.ebit
        rep_ebitda = inc.ebitda
        rep_ni = inc.net_income
        rep_fcf = cf.fcf()
        rep_shares = inc.shares_diluted or bs.shares_outstanding
        rep_bv = bs.equity
        rep_net_debt = bs.net_debt(include_leases=include_leases_in_debt)
        rep_cfo = cf.cfo
        rep_capex = cf.capex
        rep_divs = cf.dividends_paid
        rep_buybacks = cf.buybacks

        econ_shares = inc.shares_diluted or bs.shares_outstanding

        adj_ni = rep_ni
        ni_bridge: List[Tuple[str, float]] = []

        if normalised_tax_rate and inc.pretax_income and rep_ni is not None:
            reported_etf = inc.effective_tax_rate()
            if reported_etf is not None:
                implied_tax = inc.pretax_income * normalised_tax_rate
                reported_tax = inc.pretax_income * reported_etf
                tax_delta = -(implied_tax - reported_tax)
                if abs(tax_delta) > 1.0:
                    adj_ni = inc.pretax_income * (1 - normalised_tax_rate)
                    ni_bridge.append(("Tax rate normalisation", tax_delta))

        ebit_margin = _safe_div(rep_ebit, rep_rev)
        net_margin = _safe_div(rep_ni, rep_rev)

        prior_equity: Optional[float] = None
        if results:
            prior_equity = results[-1].reported_book_value
        roe = _safe_div(rep_ni, prior_equity) if prior_equity else None

        invested_capital = None
        if bs.equity is not None and rep_net_debt is not None:
            invested_capital = bs.equity + rep_net_debt
        roc = _safe_div(rep_ebit, invested_capital) if invested_capital else None

        fcf_conv = _safe_div(rep_fcf, rep_ni)

        def fx(v: Optional[float]) -> Optional[float]:
            return v * fx_rate if v is not None else None

        norm = NormalisedFinancials(
            period=inc.period,
            reported_revenue=rep_rev,
            reported_ebit=rep_ebit,
            reported_ebitda=rep_ebitda,
            reported_net_income=rep_ni,
            reported_fcf=rep_fcf,
            reported_shares_diluted=rep_shares,
            reported_book_value=rep_bv,
            reported_net_debt=rep_net_debt,
            reported_cfo=rep_cfo,
            reported_capex=rep_capex,
            reported_dividends=rep_divs,
            reported_buybacks=rep_buybacks,
            adj_revenue=fx(rep_rev),
            adj_ebit=fx(rep_ebit),
            adj_ebitda=fx(rep_ebitda),
            adj_net_income=fx(adj_ni),
            adj_fcf=fx(rep_fcf),
            adj_shares_diluted=econ_shares,
            adj_book_value=fx(rep_bv),
            adj_net_debt=fx(rep_net_debt),
            ni_bridge=ni_bridge,
            ebit_bridge=[],
            ebit_margin=ebit_margin,
            net_margin=net_margin,
            roe=roe,
            roc=roc,
            fcf_conversion=fcf_conv,
            leases_in_debt=include_leases_in_debt,
            effective_tax_rate=inc.effective_tax_rate(),
            normalised_tax_rate=normalised_tax_rate,
        )
        results.append(norm)

    return results


def build_ttm(
    quarterly: List[AnnualFinancials],
    latest_annual: Optional[AnnualFinancials] = None,
) -> Optional[NormalisedFinancials]:
    if len(quarterly) < 4:
        if latest_annual:
            logger.info("Fewer than 4 quarters; using latest annual as TTM proxy")
            norms = normalise_annual([latest_annual])
            if norms:
                ttm = norms[0]
                ttm.period = PeriodKey(
                    period_end=latest_annual.income.period.period_end,
                    fiscal_year=latest_annual.income.period.fiscal_year,
                    fiscal_period=FiscalPeriod.TTM,
                    form=latest_annual.income.period.form,
                    audited=False,
                )
                return ttm
        return None

    q4 = quarterly[:4]

    def sum_flow(attr: str) -> Optional[float]:
        vals = [getattr(q.income, attr) for q in q4]
        if all(v is None for v in vals):
            return None
        return sum(v for v in vals if v is not None)

    def sum_cf(attr: str) -> Optional[float]:
        vals = [getattr(q.cashflow, attr) for q in q4]
        if all(v is None for v in vals):
            return None
        return sum(v for v in vals if v is not None)

    latest_q = q4[0]
    bs = latest_q.balance

    ttm_rev = sum_flow("revenue")
    ttm_ebit = sum_flow("ebit")
    ttm_ni = sum_flow("net_income")
    ttm_da = sum_flow("da")
    ttm_ebitda = (ttm_ebit + ttm_da) if (ttm_ebit is not None and ttm_da is not None) else None
    ttm_cfo = sum_cf("cfo")
    ttm_capex = sum_cf("capex")
    ttm_fcf = (ttm_cfo - ttm_capex) if (ttm_cfo is not None and ttm_capex is not None) else None
    ttm_divs = sum_cf("dividends_paid")
    ttm_buybacks = sum_cf("buybacks")

    shares = latest_q.income.shares_diluted or bs.shares_outstanding
    net_debt = bs.net_debt(include_leases=True)

    period = PeriodKey(
        period_end=latest_q.income.period.period_end,
        fiscal_year=latest_q.income.period.fiscal_year,
        fiscal_period=FiscalPeriod.TTM,
        form="TTM",
        audited=False,
    )

    ebit_margin = _safe_div(ttm_ebit, ttm_rev)
    net_margin = _safe_div(ttm_ni, ttm_rev)
    ttm_fcf_conv = _safe_div(ttm_fcf, ttm_ni)

    return NormalisedFinancials(
        period=period,
        reported_revenue=ttm_rev,
        reported_ebit=ttm_ebit,
        reported_ebitda=ttm_ebitda,
        reported_net_income=ttm_ni,
        reported_fcf=ttm_fcf,
        reported_shares_diluted=shares,
        reported_book_value=bs.equity,
        reported_net_debt=net_debt,
        reported_cfo=ttm_cfo,
        reported_capex=ttm_capex,
        reported_dividends=ttm_divs,
        reported_buybacks=ttm_buybacks,
        adj_revenue=ttm_rev,
        adj_ebit=ttm_ebit,
        adj_ebitda=ttm_ebitda,
        adj_net_income=ttm_ni,
        adj_fcf=ttm_fcf,
        adj_shares_diluted=shares,
        adj_book_value=bs.equity,
        adj_net_debt=net_debt,
        ebit_margin=ebit_margin,
        net_margin=net_margin,
        fcf_conversion=ttm_fcf_conv,
        leases_in_debt=True,
    )


def compute_growth_rates(normalised: List[NormalisedFinancials]) -> List[dict]:
    result = []
    for i, n in enumerate(normalised):
        if i >= len(normalised) - 1:
            result.append({"revenue_growth": None, "ebit_growth": None,
                           "ni_growth": None, "fcf_growth": None})
            continue
        older = normalised[i + 1]

        def yoy(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
            if curr is None or prev is None or prev == 0:
                return None
            return (curr / prev) - 1.0

        result.append({
            "revenue_growth": yoy(n.reported_revenue, older.reported_revenue),
            "ebit_growth": yoy(n.reported_ebit, older.reported_ebit),
            "ni_growth": yoy(n.reported_net_income, older.reported_net_income),
            "fcf_growth": yoy(n.reported_fcf, older.reported_fcf),
        })
    return result


def estimate_cost_of_equity(
    beta: Optional[float],
    risk_free_rate: float = 0.045,
    equity_risk_premium: float = 0.055,
) -> float:
    b = beta if beta and 0.1 <= beta <= 4.0 else 1.0
    return risk_free_rate + b * equity_risk_premium


def estimate_wacc(
    cost_of_equity: float,
    cost_of_debt_pretax: Optional[float],
    tax_rate: Optional[float],
    equity_value: Optional[float],
    net_debt: Optional[float],
) -> Optional[float]:
    if equity_value is None or net_debt is None:
        return None
    if net_debt <= 0:
        return cost_of_equity

    total = equity_value + net_debt
    if total <= 0:
        return None

    we = equity_value / total
    wd = net_debt / total

    if cost_of_debt_pretax is None:
        cost_of_debt_pretax = 0.05
    tax = tax_rate if tax_rate else 0.21

    kd_at = cost_of_debt_pretax * (1 - tax)
    return cost_of_equity * we + kd_at * wd


def flag_recurring_one_offs(normalised: List[NormalisedFinancials]) -> List[str]:
    warnings_list = []
    years_with_adjustments = sum(1 for n in normalised if n.ni_bridge)
    if years_with_adjustments >= 3:
        warnings_list.append(
            f"Non-recurring adjustments present in {years_with_adjustments} of "
            f"{len(normalised)} years — treat recurring 'one-offs' sceptically."
        )
    return warnings_list
