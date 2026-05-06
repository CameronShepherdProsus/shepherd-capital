"""
Core data model: as-reported financial statements, normalised fields,
valuation outputs, and provenance metadata.

All values stored in reporting currency (millions) unless noted.
Per-share values in reporting currency per share.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class FilingRegime(str, Enum):
    US_DOMESTIC = "us_domestic"
    FPI_SEC = "fpi_sec"
    EU_REGULATED = "eu_regulated"
    EURONEXT = "euronext"
    UK = "uk"
    CANADIAN = "canadian"
    UNKNOWN = "unknown"


class AccountingStandard(str, Enum):
    US_GAAP = "us_gaap"
    IFRS = "ifrs"
    OTHER = "other"


class DataStatus(str, Enum):
    AS_REPORTED = "as_reported"
    ADJUSTED = "adjusted"
    ESTIMATED = "estimated"


class FiscalPeriod(str, Enum):
    FY = "FY"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    TTM = "TTM"
    H1 = "H1"
    H2 = "H2"


@dataclass
class Provenance:
    source_type: str
    source_id: str
    period_end: date
    filed_at: Optional[date]
    status: DataStatus
    reporting_currency: str
    valuation_currency: str
    accounting_standard: AccountingStandard
    units: str = "millions"
    scale: float = 1_000_000
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    estimate_snapshot_time: Optional[datetime] = None
    parser_version: str = "1.0.0"
    valuation_engine_version: str = "1.0.0"
    notes: List[str] = field(default_factory=list)


@dataclass
class PeriodKey:
    period_end: date
    fiscal_year: int
    fiscal_period: FiscalPeriod
    form: str
    audited: bool
    accession: Optional[str] = None


@dataclass
class IncomeStatement:
    period: PeriodKey
    revenue: Optional[float] = None
    cost_of_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_expenses: Optional[float] = None
    ebit: Optional[float] = None
    interest_expense: Optional[float] = None
    pretax_income: Optional[float] = None
    tax_expense: Optional[float] = None
    net_income: Optional[float] = None
    minority_interest: Optional[float] = None
    net_income_common: Optional[float] = None
    da: Optional[float] = None
    ebitda: Optional[float] = None
    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None
    shares_basic: Optional[float] = None
    shares_diluted: Optional[float] = None
    non_recurring_items: Optional[float] = None
    normalised_ebit: Optional[float] = None
    normalised_net_income: Optional[float] = None

    def compute_ebitda(self) -> None:
        if self.ebit is not None and self.da is not None:
            self.ebitda = self.ebit + self.da

    def effective_tax_rate(self) -> Optional[float]:
        if self.pretax_income and self.tax_expense and self.pretax_income != 0:
            return self.tax_expense / self.pretax_income
        return None

    def ebit_margin(self) -> Optional[float]:
        if self.ebit is not None and self.revenue:
            return self.ebit / self.revenue
        return None

    def net_margin(self) -> Optional[float]:
        if self.net_income is not None and self.revenue:
            return self.net_income / self.revenue
        return None


@dataclass
class BalanceSheet:
    period: PeriodKey
    total_assets: Optional[float] = None
    total_liabilities: Optional[float] = None
    equity: Optional[float] = None
    minority_interest_bs: Optional[float] = None
    cash: Optional[float] = None
    short_term_investments: Optional[float] = None
    accounts_receivable: Optional[float] = None
    inventory: Optional[float] = None
    current_assets: Optional[float] = None
    ppe_net: Optional[float] = None
    goodwill: Optional[float] = None
    intangibles: Optional[float] = None
    right_of_use_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    accounts_payable: Optional[float] = None
    short_term_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    lease_liabilities_current: Optional[float] = None
    lease_liabilities_noncurrent: Optional[float] = None
    preferred_equity: Optional[float] = None
    shares_outstanding: Optional[float] = None

    def net_debt(self, include_leases: bool = True) -> Optional[float]:
        cash = (self.cash or 0) + (self.short_term_investments or 0)
        debt = (self.short_term_debt or 0) + (self.long_term_debt or 0)
        if include_leases:
            debt += (self.lease_liabilities_current or 0) + (self.lease_liabilities_noncurrent or 0)
        if self.total_assets is None:
            return None
        return debt - cash

    def book_value_per_share(self) -> Optional[float]:
        if self.equity and self.shares_outstanding:
            return self.equity / self.shares_outstanding
        return None

    def balance_check(self) -> Optional[float]:
        if self.total_assets and self.total_liabilities and self.equity:
            equity_side = self.equity + (self.minority_interest_bs or 0)
            return abs(self.total_assets - (self.total_liabilities + equity_side))
        return None


@dataclass
class CashFlowStatement:
    period: PeriodKey
    cfo: Optional[float] = None
    capex: Optional[float] = None
    acquisitions: Optional[float] = None
    disposals: Optional[float] = None
    cfi: Optional[float] = None
    dividends_paid: Optional[float] = None
    buybacks: Optional[float] = None
    net_borrowing: Optional[float] = None
    cff: Optional[float] = None
    fx_effect: Optional[float] = None
    net_change_in_cash: Optional[float] = None
    opening_cash: Optional[float] = None
    closing_cash: Optional[float] = None
    interest_paid: Optional[float] = None
    tax_paid: Optional[float] = None

    def fcf(self) -> Optional[float]:
        if self.cfo is not None and self.capex is not None:
            return self.cfo - self.capex
        return None

    def fcfe(self, net_income: Optional[float], da: Optional[float],
             change_nwc: Optional[float]) -> Optional[float]:
        if any(v is None for v in [net_income, da, self.capex, change_nwc, self.net_borrowing]):
            return None
        return net_income + da - self.capex - change_nwc + self.net_borrowing

    def cash_flow_check(self) -> Optional[float]:
        if any(v is None for v in [self.opening_cash, self.cfo, self.cfi,
                                    self.cff, self.closing_cash]):
            return None
        computed = (self.opening_cash + self.cfo + self.cfi + self.cff
                    + (self.fx_effect or 0))
        return abs(computed - self.closing_cash)


@dataclass
class AnnualFinancials:
    income: IncomeStatement
    balance: BalanceSheet
    cashflow: CashFlowStatement
    provenance: Provenance

    def __post_init__(self):
        self.income.compute_ebitda()

    def change_in_nwc(self) -> Optional[float]:
        if (self.balance.accounts_receivable is None or
                self.balance.inventory is None or
                self.balance.accounts_payable is None):
            return None
        nwc = (self.balance.accounts_receivable +
               self.balance.inventory -
               self.balance.accounts_payable)
        return nwc


@dataclass
class SegmentData:
    period: PeriodKey
    segment_name: str
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    assets: Optional[float] = None
    geography: Optional[str] = None
    revenue_share_pct: Optional[float] = None


@dataclass
class CompanyProfile:
    ticker: str
    name: str
    exchange: str
    regime: FilingRegime
    accounting_standard: AccountingStandard
    reporting_currency: str
    valuation_currency: str
    cik: Optional[str] = None
    isin: Optional[str] = None
    lei: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = None
    segments: List[SegmentData] = field(default_factory=list)
    revenue_drivers: List[str] = field(default_factory=list)
    moat_commentary: Optional[str] = None


@dataclass
class MarketData:
    ticker: str
    price: float
    price_date: date
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    beta: Optional[float] = None
    currency: str = "USD"
    shares_outstanding: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None


@dataclass
class NormalisedFinancials:
    period: PeriodKey
    # Reported
    reported_revenue: Optional[float] = None
    reported_ebit: Optional[float] = None
    reported_ebitda: Optional[float] = None
    reported_net_income: Optional[float] = None
    reported_fcf: Optional[float] = None
    reported_shares_diluted: Optional[float] = None
    reported_book_value: Optional[float] = None
    reported_net_debt: Optional[float] = None
    reported_cfo: Optional[float] = None
    reported_capex: Optional[float] = None
    reported_dividends: Optional[float] = None
    reported_buybacks: Optional[float] = None
    # Adjusted
    adj_revenue: Optional[float] = None
    adj_ebit: Optional[float] = None
    adj_ebitda: Optional[float] = None
    adj_net_income: Optional[float] = None
    adj_fcf: Optional[float] = None
    adj_shares_diluted: Optional[float] = None
    adj_book_value: Optional[float] = None
    adj_net_debt: Optional[float] = None
    # Bridges
    ebit_bridge: List[tuple] = field(default_factory=list)
    ni_bridge: List[tuple] = field(default_factory=list)
    # Computed ratios
    ebit_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roc: Optional[float] = None
    fcf_conversion: Optional[float] = None
    leases_in_debt: bool = True
    effective_tax_rate: Optional[float] = None
    normalised_tax_rate: Optional[float] = None


@dataclass
class DataPackage:
    profile: CompanyProfile
    market: MarketData
    annual: List[NormalisedFinancials]
    ttm: Optional[NormalisedFinancials] = None
    quarterly: List[NormalisedFinancials] = field(default_factory=list)
    raw_annual: List[AnnualFinancials] = field(default_factory=list)
    data_quality_flags: List[str] = field(default_factory=list)
    confidence: str = "medium"
    provenance: List[Provenance] = field(default_factory=list)


# --- Valuation outputs ---

@dataclass
class SensitivityGrid:
    row_label: str
    col_label: str
    row_values: List[float]
    col_values: List[float]
    grid: List[List[float]]


@dataclass
class DCFResult:
    method: str
    equity_value_per_share: float
    equity_value_total: float
    pv_explicit: float
    pv_terminal: float
    terminal_value: float
    cost_of_equity: float
    wacc: Optional[float]
    terminal_growth: float
    forecast_years: int
    forecast_cash_flows: List[float]
    discount_rates: List[float]
    ev_to_equity_bridge: Optional[Dict[str, float]] = None
    sensitivity: Optional[SensitivityGrid] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class ResidualIncomeResult:
    equity_value_per_share: float
    opening_book_value_per_share: float
    pv_residual_income: float
    pv_terminal: float
    cost_of_equity: float
    forecast_roe: List[float]
    forecast_ri: List[float]
    forecast_bvps: List[float]
    notes: List[str] = field(default_factory=list)


@dataclass
class PayoutResult:
    method: str
    equity_value_per_share: float
    cost_of_equity: float
    terminal_growth: float
    forecast_payouts: List[float]
    pv_explicit: float
    pv_terminal: float
    notes: List[str] = field(default_factory=list)


@dataclass
class ComparablesResult:
    equity_value_per_share: float
    multiple_used: str
    peer_multiple_median: float
    peer_multiple_range: tuple
    target_metric: float
    ev_target: Optional[float]
    ev_to_equity_bridge: Optional[Dict[str, float]]
    peer_tickers: List[str]
    notes: List[str] = field(default_factory=list)


@dataclass
class ConsensusEstimate:
    source: str
    analyst_id: Optional[str]
    estimate_date: Optional[date]
    fiscal_year: int
    revenue: Optional[float] = None
    ebit: Optional[float] = None
    ebitda: Optional[float] = None
    eps: Optional[float] = None
    dps: Optional[float] = None
    fcf: Optional[float] = None
    net_debt: Optional[float] = None
    capex: Optional[float] = None
    staleness_flag: bool = False


@dataclass
class SyntheticConsensus:
    fair_value_per_share: float
    low: float
    high: float
    method: str
    analyst_count: Optional[int]
    dispersion_pct: Optional[float]
    component_values: Dict[str, float] = field(default_factory=dict)
    component_weights: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


@dataclass
class Verdict:
    label: str
    upside_downside_pct: float
    current_price: float
    fair_value_mid: float
    fair_value_low: float
    fair_value_high: float
    verdict_buffer_pct: float = 0.10
    rationale: str = ""


@dataclass
class ValuationOutput:
    company: CompanyProfile
    market: MarketData
    valuation_date: date
    dcf_fcfe: Optional[DCFResult] = None
    dcf_fcff: Optional[DCFResult] = None
    residual_income: Optional[ResidualIncomeResult] = None
    total_payout: Optional[PayoutResult] = None
    ddm: Optional[PayoutResult] = None
    comparables: Optional[ComparablesResult] = None
    consensus: Optional[SyntheticConsensus] = None
    verdict: Optional[Verdict] = None
    data_quality_flags: List[str] = field(default_factory=list)
    confidence: str = "medium"
    provenance: List[Provenance] = field(default_factory=list)
