"""Per-fund risk analytics: currency-level and fund-level IRR, and NAV schedules per currency."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from fund_analytics.loader import LoadResult, Rejection
from fund_analytics.models import Cashflow
from fund_analytics.valuation import Cashflows, nav_schedule, xirr

# Allowed rounding error, in currency units, for the NAV sanity checks.
NAV_CHECK_TOLERANCE = 0.01


class IrrLevel(StrEnum):
    CURRENCY = "currency"
    FUND = "fund"


@dataclass(frozen=True)
class IrrResult:
    fund: str
    level: IrrLevel
    currency: str  # local currency, or the fund's base currency at fund level
    irr: float | None  # None when no IRR exists, e.g. the investment row was rejected
    rejected_row_ids: tuple[str, ...]  # data-quality flag: rejected rows from this fund
    error: str | None = None


@dataclass(frozen=True)
class NavSchedule:
    fund: str
    currency: str  # local currency; NAV values are in this currency
    irr: float | None  # the currency-level IRR used as the discount rate
    points: tuple[tuple[date, float], ...]  # (date, NAV) on every cashflow date
    exit_value: Decimal | None  # sum of the cashflows on the final date, exact
    rejected_row_ids: tuple[str, ...]
    error: str | None = None

    @property
    def passes_sanity_checks(self) -> bool:
        """The brief's checks: NAV on the first date is 0, NAV on the last date is the exit value.

        Discounting at the IRR of the same cashflows makes both hold by construction, so a
        failure means a bug in the IRR or NAV code, not bad input data.
        """
        if not self.points or self.exit_value is None:
            return False
        opening, closing = self.points[0][1], self.points[-1][1]
        exit_value = float(self.exit_value)
        return abs(opening) <= NAV_CHECK_TOLERANCE and abs(closing - exit_value) <= NAV_CHECK_TOLERANCE


def compute_analytics(result: LoadResult) -> tuple[list[IrrResult], list[NavSchedule]]:
    """Per fund: IRR and NAV schedule per local currency, and the fund-level IRR on base amounts."""
    by_fund: dict[str, list[Cashflow]] = defaultdict(list)
    for cashflow in result.valid:
        by_fund[cashflow.fund_name].append(cashflow)
    flagged = _rejected_ids_by_fund(result.rejected, by_fund)

    irrs, schedules = [], []
    for fund in sorted(by_fund):
        cashflows = by_fund[fund]
        for currency in sorted({c.local_currency for c in cashflows}):
            leg = [c for c in cashflows if c.local_currency == currency]
            flows = [(c.cashflow_date, float(c.amount_local)) for c in leg]
            irr = _irr_result(fund, IrrLevel.CURRENCY, currency, flows, flagged[fund])
            irrs.append(irr)
            schedules.append(_nav_schedule(irr, flows, _exit_value(leg)))

        base = cashflows[0].base_currency  # the loader guarantees one base currency per fund
        flows = [(c.cashflow_date, float(c.amount_base)) for c in cashflows]
        irrs.append(_irr_result(fund, IrrLevel.FUND, base, flows, flagged[fund]))
    return irrs, schedules


def _nav_schedule(irr: IrrResult, flows: Cashflows, exit_value: Decimal) -> NavSchedule:
    """NAV schedule in local currency, discounted at the currency-level IRR."""
    if irr.irr is None:
        return NavSchedule(irr.fund, irr.currency, None, (), None, irr.rejected_row_ids, irr.error)
    points = tuple(nav_schedule(flows, irr.irr))
    return NavSchedule(irr.fund, irr.currency, irr.irr, points, exit_value, irr.rejected_row_ids)


def _exit_value(cashflows: list[Cashflow]) -> Decimal:
    """Sum of the local amounts on the last cashflow date."""
    last_date = max(c.cashflow_date for c in cashflows)
    return sum((c.amount_local for c in cashflows if c.cashflow_date == last_date), Decimal(0))


def _irr_result(
    fund: str, level: IrrLevel, currency: str, flows: Cashflows, flagged: tuple[str, ...]
) -> IrrResult:
    # One fund's bad data (e.g. a rejected investment row) must not stop the other results.
    try:
        return IrrResult(fund, level, currency, xirr(flows), flagged)
    except ValueError as exc:
        return IrrResult(fund, level, currency, None, flagged, error=str(exc))


def _rejected_ids_by_fund(rejected: list[Rejection], funds: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """IDs of rejected rows per fund; a row whose fund name can't be read flags every fund."""
    ids: dict[str, list[str]] = {fund: [] for fund in funds}
    for rejection in rejected:
        raw_fund = _text(rejection.raw.get("Fund Name"))
        for fund in ids:
            if raw_fund is None or raw_fund == fund:
                ids[fund].append(str(rejection.row_id))
    return {fund: tuple(row_ids) for fund, row_ids in ids.items()}


def _text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return " ".join(value.split())
