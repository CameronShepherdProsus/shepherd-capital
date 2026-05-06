"""
yfinance → DataPackage bridge.

Maps yfinance financials (all values in native currency units) to the
data model (values in millions). Handles missing/NaN fields gracefully.
"""
from __future__ import annotations

import logging
import warnings
from datetime import date, datetime
from typing import List, Optional

import pandas as pd
import yfinance as yf

from .data_model import (
    AccountingStandard, AnnualFinancials, BalanceSheet, CashFlowStatement,
    CompanyProfile, DataPackage, DataStatus, FilingRegime, FiscalPeriod,
    IncomeStatement, MarketData, NormalisedFinancials, PeriodKey, Provenance,
)
from .adjustments import normalise_annual, build_ttm

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)


def _sf(val) -> Optional[float]:
    """Safe cast to float; returns None for NaN/None/non-numeric."""
    if val is None:
        return None
    try:
        f = float(val)
        import math
        return None if (pd.isna(f) or not math.isfinite(f)) else f
    except (TypeError, ValueError):
        return None


def _get(df: pd.DataFrame, col, *names: str) -> Optional[float]:
    """Extract a value from a DataFrame row (indexed by metric name) at column col."""
    for name in names:
        if name in df.index:
            try:
                return _sf(df.loc[name, col])
            except (KeyError, TypeError):
                pass
    return None


def _to_m(v: Optional[float]) -> Optional[float]:
    """Convert raw yfinance value (units) to millions."""
    return v / 1_000_000 if v is not None else None


def _build_period(col_date, is_quarterly: bool = False) -> PeriodKey:
    try:
        d = col_date.date() if hasattr(col_date, "date") else date(int(str(col_date)[:4]), 12, 31)
        fy = d.year
    except Exception:
        fy = 2020
        d = date(2020, 12, 31)
    return PeriodKey(
        period_end=d,
        fiscal_year=fy,
        fiscal_period=FiscalPeriod.Q1 if is_quarterly else FiscalPeriod.FY,
        form="10-Q" if is_quarterly else "10-K",
        audited=not is_quarterly,
    )


def _build_income(fin_df: pd.DataFrame, col) -> IncomeStatement:
    g = lambda *n: _to_m(_get(fin_df, col, *n))
    period = _build_period(col)

    rev = g("Total Revenue")
    ebit = g("Operating Income", "EBIT", "Ebit")
    da = g("Reconciled Depreciation", "Depreciation And Amortization",
           "Depreciation Amortization Depletion", "Depreciation")
    ebitda = g("EBITDA", "Normalized EBITDA")
    if ebitda is None and ebit is not None and da is not None:
        ebitda = ebit + da

    ni = g("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
    pretax = g("Pretax Income")
    tax = g("Tax Provision")
    interest = g("Interest Expense", "Interest Expense Non Operating")
    shares_dil_raw = _get(fin_df, col, "Diluted Average Shares", "Diluted Shares")
    shares_bas_raw = _get(fin_df, col, "Basic Average Shares", "Basic Shares")

    return IncomeStatement(
        period=period,
        revenue=rev,
        ebit=ebit,
        ebitda=ebitda,
        net_income=ni,
        pretax_income=pretax,
        tax_expense=tax,
        interest_expense=abs(interest) if interest is not None else None,
        da=da,
        shares_diluted=shares_dil_raw / 1e6 if shares_dil_raw else None,
        shares_basic=shares_bas_raw / 1e6 if shares_bas_raw else None,
    )


def _build_balance(bs_df: Optional[pd.DataFrame], col) -> BalanceSheet:
    period = _build_period(col)
    if bs_df is None or bs_df.empty:
        return BalanceSheet(period=period)
    g = lambda *n: _to_m(_get(bs_df, col, *n))
    g_raw = lambda *n: _get(bs_df, col, *n)

    shares_raw = g_raw("Ordinary Shares Number", "Share Issued")

    return BalanceSheet(
        period=period,
        total_assets=g("Total Assets"),
        total_liabilities=g("Total Liabilities Net Minority Interest", "Total Liabilities"),
        equity=g("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"),
        cash=g("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
        short_term_investments=g("Other Short Term Investments", "Available For Sale Securities"),
        long_term_debt=g("Long Term Debt"),
        short_term_debt=g("Current Debt", "Short Long Term Debt",
                          "Current Debt And Capital Lease Obligation"),
        accounts_receivable=g("Accounts Receivable", "Net Receivables"),
        inventory=g("Inventory"),
        accounts_payable=g("Accounts Payable"),
        goodwill=g("Goodwill"),
        intangibles=g("Other Intangible Assets", "Intangible Assets"),
        shares_outstanding=shares_raw / 1e6 if shares_raw else None,
    )


def _build_cashflow(cf_df: Optional[pd.DataFrame], col) -> CashFlowStatement:
    period = _build_period(col)
    if cf_df is None or cf_df.empty:
        return CashFlowStatement(period=period)
    g = lambda *n: _to_m(_get(cf_df, col, *n))

    cfo = g("Operating Cash Flow")
    capex_raw = _to_m(_get(cf_df, col, "Capital Expenditure"))
    capex = abs(capex_raw) if capex_raw is not None else None

    divs_raw = _to_m(_get(cf_df, col, "Common Stock Dividend Paid", "Cash Dividends Paid",
                          "Payment Of Dividends"))
    divs = abs(divs_raw) if divs_raw is not None else None

    buybacks_raw = _to_m(_get(cf_df, col, "Repurchase Of Capital Stock",
                              "Common Stock Repurchase"))
    buybacks = abs(buybacks_raw) if buybacks_raw is not None else None

    net_borrow = g("Net Issuance Payments Of Debt", "Net Long Term Debt Issuance",
                   "Net Debt Issuance")

    return CashFlowStatement(
        period=period,
        cfo=cfo,
        capex=capex,
        dividends_paid=divs,
        buybacks=buybacks,
        net_borrowing=net_borrow,
    )


def fetch_data_package(ticker: str, valuation_currency: str = "USD") -> Optional[DataPackage]:
    """Fetch all financial data for ticker and return a DataPackage, or None on failure."""
    try:
        tkr = yf.Ticker(ticker)
        info = tkr.info or {}
    except Exception as e:
        logger.warning(f"{ticker}: yf.Ticker failed: {e}")
        return None

    price = _sf(info.get("currentPrice") or info.get("regularMarketPrice"))
    if not price:
        logger.warning(f"{ticker}: no price available")
        return None

    reporting_currency = info.get("currency", "USD") or "USD"
    exchange = info.get("exchange", "UNKNOWN") or "UNKNOWN"

    # Regime heuristic: US exchanges → US_DOMESTIC, otherwise UNKNOWN
    us_exchanges = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "CBOE", "NYB"}
    if exchange.upper() in us_exchanges or reporting_currency == "USD":
        regime = FilingRegime.US_DOMESTIC
        accounting = AccountingStandard.US_GAAP
    else:
        regime = FilingRegime.UNKNOWN
        accounting = AccountingStandard.IFRS

    market_cap_raw = _sf(info.get("marketCap"))
    ev_raw = _sf(info.get("enterpriseValue"))
    shares_raw = _sf(info.get("sharesOutstanding"))

    market = MarketData(
        ticker=ticker,
        price=price,
        price_date=date.today(),
        market_cap=market_cap_raw / 1e6 if market_cap_raw else None,
        enterprise_value=ev_raw / 1e6 if ev_raw else None,
        beta=_sf(info.get("beta")),
        currency=reporting_currency,
        shares_outstanding=shares_raw / 1e6 if shares_raw else None,
        sector=info.get("sector"),
        industry=info.get("industry"),
    )

    profile = CompanyProfile(
        ticker=ticker,
        name=info.get("longName") or info.get("shortName") or ticker,
        exchange=exchange,
        regime=regime,
        accounting_standard=accounting,
        reporting_currency=reporting_currency,
        valuation_currency=valuation_currency,
        sector=info.get("sector"),
        industry=info.get("industry"),
        description=(info.get("longBusinessSummary") or "")[:500],
    )

    # Annual financials
    try:
        fin_df = tkr.financials
        bs_df = tkr.balance_sheet
        cf_df = tkr.cashflow
    except Exception as e:
        logger.warning(f"{ticker}: financials fetch failed: {e}")
        return None

    if fin_df is None or fin_df.empty:
        logger.warning(f"{ticker}: empty income statement")
        return None

    annual_raw: List[AnnualFinancials] = []
    prov_base = Provenance(
        source_type="yfinance",
        source_id=ticker,
        period_end=date.today(),
        filed_at=None,
        status=DataStatus.AS_REPORTED,
        reporting_currency=reporting_currency,
        valuation_currency=valuation_currency,
        accounting_standard=accounting,
    )

    for col in fin_df.columns[:10]:
        try:
            income = _build_income(fin_df, col)
            balance = _build_balance(bs_df, col)
            cashflow = _build_cashflow(cf_df, col)
            prov = Provenance(
                source_type="yfinance",
                source_id=ticker,
                period_end=income.period.period_end,
                filed_at=None,
                status=DataStatus.AS_REPORTED,
                reporting_currency=reporting_currency,
                valuation_currency=valuation_currency,
                accounting_standard=accounting,
            )
            annual_raw.append(AnnualFinancials(income=income, balance=balance,
                                               cashflow=cashflow, provenance=prov))
        except Exception as e:
            logger.debug(f"{ticker}: skipping annual col {col}: {e}")

    if not annual_raw:
        logger.warning(f"{ticker}: no annual periods parsed")
        return None

    annual_norm = normalise_annual(annual_raw)

    # TTM from quarterly
    ttm_norm: Optional[NormalisedFinancials] = None
    try:
        q_fin = tkr.quarterly_financials
        q_bs = tkr.quarterly_balance_sheet
        q_cf = tkr.quarterly_cashflow

        if q_fin is not None and not q_fin.empty and len(q_fin.columns) >= 4:
            q_raw: List[AnnualFinancials] = []
            for col in q_fin.columns[:4]:
                try:
                    q_income = _build_income(q_fin, col)
                    q_income.period = _build_period(col, is_quarterly=True)
                    q_balance = _build_balance(q_bs, col)
                    q_balance.period = q_income.period
                    q_cashflow = _build_cashflow(q_cf, col)
                    q_cashflow.period = q_income.period
                    prov = Provenance(
                        source_type="yfinance", source_id=ticker,
                        period_end=q_income.period.period_end, filed_at=None,
                        status=DataStatus.AS_REPORTED,
                        reporting_currency=reporting_currency,
                        valuation_currency=valuation_currency,
                        accounting_standard=accounting,
                    )
                    q_raw.append(AnnualFinancials(q_income, q_balance, q_cashflow, prov))
                except Exception:
                    pass
            ttm_norm = build_ttm(q_raw, annual_raw[0] if annual_raw else None)
    except Exception as e:
        logger.debug(f"{ticker}: TTM build failed: {e}")

    flags: List[str] = []
    if len(annual_norm) < 3:
        flags.append(f"Only {len(annual_norm)} year(s) of annual data")
    if ttm_norm is None:
        flags.append("TTM data unavailable — using latest annual")

    return DataPackage(
        profile=profile,
        market=market,
        annual=annual_norm,
        ttm=ttm_norm,
        raw_annual=annual_raw,
        data_quality_flags=flags,
        confidence="high" if len(annual_norm) >= 5 else "medium" if len(annual_norm) >= 3 else "low",
        provenance=[af.provenance for af in annual_raw[:3]],
    )
