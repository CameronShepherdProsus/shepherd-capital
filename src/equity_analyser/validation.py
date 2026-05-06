"""
Validation layer — hard fails and soft fails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .data_model import AnnualFinancials, NormalisedFinancials


class Severity(str, Enum):
    HARD_FAIL = "hard_fail"
    SOFT_FAIL = "soft_fail"
    WARNING = "warning"


@dataclass
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    detail: Optional[str] = None


@dataclass
class ValidationResult:
    passed: bool
    issues: List[ValidationIssue] = field(default_factory=list)
    confidence: str = "high"

    def hard_failures(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.HARD_FAIL]

    def soft_failures(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.SOFT_FAIL]

    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]


BALANCE_TOLERANCE = 0.02
CASH_FLOW_TOLERANCE = 0.02
MIN_YEARS_FOR_HIGH_CONFIDENCE = 5
MIN_YEARS_FOR_ANY_OUTPUT = 2


def validate_balance_sheet(af: AnnualFinancials) -> List[ValidationIssue]:
    issues = []
    bs = af.balance
    check = bs.balance_check()
    if check is not None:
        threshold = max(5.0, (bs.total_assets or 0) * BALANCE_TOLERANCE)
        if check > threshold:
            from datetime import date as _date
            is_old = bs.period.period_end < _date(2018, 1, 1)
            severity = Severity.WARNING if is_old else Severity.HARD_FAIL
            issues.append(ValidationIssue(
                severity=severity,
                code="BS_IMBALANCE",
                message=f"Balance sheet imbalance of {check:.1f}m in {bs.period.period_end}",
                detail=f"Assets={bs.total_assets}, L={bs.total_liabilities}, E={bs.equity}",
            ))
    return issues


def validate_cash_flow(af: AnnualFinancials) -> List[ValidationIssue]:
    issues = []
    cf = af.cashflow
    check = cf.cash_flow_check()
    if check is not None:
        threshold = max(10.0, (af.balance.total_assets or 0) * CASH_FLOW_TOLERANCE)
        if check > threshold:
            issues.append(ValidationIssue(
                severity=Severity.HARD_FAIL,
                code="CF_IMBALANCE",
                message=f"Cash-flow statement does not reconcile in {cf.period.period_end}: {check:.1f}m",
            ))
    return issues


def validate_share_count(normalised: List[NormalisedFinancials]) -> List[ValidationIssue]:
    issues = []
    for n in normalised:
        if n.reported_shares_diluted is None or n.reported_shares_diluted <= 0:
            issues.append(ValidationIssue(
                severity=Severity.HARD_FAIL,
                code="SHARES_MISSING",
                message=f"Diluted share count missing or zero in {n.period.period_end}",
            ))
    return issues


def validate_terminal_growth(terminal_growth: float, discount_rate: float) -> List[ValidationIssue]:
    issues = []
    if terminal_growth >= discount_rate:
        issues.append(ValidationIssue(
            severity=Severity.HARD_FAIL,
            code="TV_GROWTH_EXCEEDS_RATE",
            message=f"Terminal growth ({terminal_growth:.1%}) >= discount rate ({discount_rate:.1%})",
        ))
    return issues


def validate_adjusted_has_reported(normalised: List[NormalisedFinancials]) -> List[ValidationIssue]:
    issues = []
    for n in normalised:
        pairs = [
            ("adj_ebit", "reported_ebit"),
            ("adj_net_income", "reported_net_income"),
            ("adj_fcf", "reported_fcf"),
        ]
        for adj_attr, rep_attr in pairs:
            adj_val = getattr(n, adj_attr, None)
            rep_val = getattr(n, rep_attr, None)
            if adj_val is not None and rep_val is None:
                issues.append(ValidationIssue(
                    severity=Severity.HARD_FAIL,
                    code="ADJUSTED_WITHOUT_REPORTED",
                    message=f"Adjusted {adj_attr} present but {rep_attr} missing in {n.period.period_end}",
                ))
    return issues


def validate_currency_consistency(
    reporting_currency: str, valuation_currency: str, fx_rate: float
) -> List[ValidationIssue]:
    issues = []
    if reporting_currency != valuation_currency and fx_rate == 1.0:
        issues.append(ValidationIssue(
            severity=Severity.HARD_FAIL,
            code="CURRENCY_MISMATCH_NO_FX",
            message=f"Currency mismatch ({reporting_currency} vs {valuation_currency}) with FX=1.0",
        ))
    return issues


def validate_data_completeness(normalised: List[NormalisedFinancials]) -> List[ValidationIssue]:
    issues = []
    n = len(normalised)

    if n < MIN_YEARS_FOR_ANY_OUTPUT:
        issues.append(ValidationIssue(
            severity=Severity.HARD_FAIL,
            code="INSUFFICIENT_HISTORY",
            message=f"Only {n} year(s) of data — minimum {MIN_YEARS_FOR_ANY_OUTPUT} required",
        ))
        return issues

    if n < MIN_YEARS_FOR_HIGH_CONFIDENCE:
        issues.append(ValidationIssue(
            severity=Severity.SOFT_FAIL,
            code="LIMITED_HISTORY",
            message=f"Only {n} years of history (target 10) — wider valuation range",
        ))

    missing_rev = sum(1 for x in normalised if x.reported_revenue is None)
    missing_ni = sum(1 for x in normalised if x.reported_net_income is None)
    missing_fcf = sum(1 for x in normalised if x.reported_fcf is None)

    if missing_rev > n // 2:
        issues.append(ValidationIssue(severity=Severity.SOFT_FAIL, code="REVENUE_GAPS",
                                      message=f"Revenue missing in {missing_rev}/{n} periods"))
    if missing_ni > n // 2:
        issues.append(ValidationIssue(severity=Severity.SOFT_FAIL, code="NET_INCOME_GAPS",
                                      message=f"Net income missing in {missing_ni}/{n} periods"))
    if missing_fcf > n // 2:
        issues.append(ValidationIssue(severity=Severity.SOFT_FAIL, code="FCF_GAPS",
                                      message=f"FCF missing in {missing_fcf}/{n} periods"))

    return issues


def validate_restated_periods(normalised: List[NormalisedFinancials]) -> List[ValidationIssue]:
    issues = []
    seen_years = {}
    for n in normalised:
        fy = n.period.fiscal_year
        if fy in seen_years:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="DUPLICATE_FISCAL_YEAR",
                message=f"Fiscal year {fy} appears more than once — possible restatement",
            ))
        seen_years[fy] = True
    return issues


def run_all_validations(
    raw_annual: List[AnnualFinancials],
    normalised: List[NormalisedFinancials],
    reporting_currency: str,
    valuation_currency: str,
    fx_rate: float,
    terminal_growth: Optional[float] = None,
    discount_rate: Optional[float] = None,
) -> ValidationResult:
    all_issues: List[ValidationIssue] = []

    for af in raw_annual:
        all_issues.extend(validate_balance_sheet(af))
        all_issues.extend(validate_cash_flow(af))

    all_issues.extend(validate_share_count(normalised))
    all_issues.extend(validate_adjusted_has_reported(normalised))
    all_issues.extend(validate_currency_consistency(
        reporting_currency, valuation_currency, fx_rate
    ))
    all_issues.extend(validate_data_completeness(normalised))
    all_issues.extend(validate_restated_periods(normalised))

    if terminal_growth is not None and discount_rate is not None:
        all_issues.extend(validate_terminal_growth(terminal_growth, discount_rate))

    hard_fails = [i for i in all_issues if i.severity == Severity.HARD_FAIL]
    soft_fails = [i for i in all_issues if i.severity == Severity.SOFT_FAIL]

    passed = len(hard_fails) == 0

    if not passed:
        confidence = "low"
    elif soft_fails:
        confidence = "medium"
    elif len(normalised) >= MIN_YEARS_FOR_HIGH_CONFIDENCE:
        confidence = "high"
    else:
        confidence = "medium"

    return ValidationResult(passed=passed, issues=all_issues, confidence=confidence)
