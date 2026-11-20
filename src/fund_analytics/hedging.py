"""FX hedge recommendations: 3-month rolling FX forwards at 100% of each non-base-currency exposure.

The exposure hedged on a roll date t is the NPV at t of the cashflows dated strictly
after t, discounted at the currency's IRR: the position's value just after that day's
cashflow is paid. NAV(t) itself counts the cashflow on t, so NAV(0) = 0 and would give
no hedge on the investment date, when the exposure is largest.

No forward rates are produced: there is no market data, so the rate is left to execution.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fund_analytics.analytics import NavSchedule
from fund_analytics.loader import LoadResult
from fund_analytics.valuation import Cashflows, npv

HEDGE_RATIO = 1.0
ROLL_MONTHS = 3

# Exposures smaller than this, in currency units, are treated as zero (no trade).
MIN_NOTIONAL = 0.01

# Trade notionals are rounded to this unit (cents), whatever the currency.
NOTIONAL_UNIT = Decimal("0.01")


@dataclass(frozen=True)
class HedgeTrade:
    trade_date: date
    value_date: date
    sell_currency: str
    buy_currency: str
    notional_local: Decimal  # in the deal's local currency, whichever side it is on; rounded to cents


@dataclass(frozen=True)
class HedgePlan:
    fund: str
    local_currency: str
    base_currency: str
    trades: tuple[HedgeTrade, ...]
    rejected_row_ids: tuple[str, ...]  # the fund's data-quality flag, as on NavSchedule
    error: str | None = None


def recommend_hedges(result: LoadResult, schedules: list[NavSchedule]) -> list[HedgePlan]:
    """One plan per (fund, local currency) whose currency differs from the fund's base currency."""
    flows: dict[tuple[str, str], list[tuple[date, float]]] = defaultdict(list)
    base_currency: dict[str, str] = {}
    for cashflow in result.valid:
        key = (cashflow.fund_name, cashflow.local_currency)
        flows[key].append((cashflow.cashflow_date, float(cashflow.amount_local)))
        base_currency[cashflow.fund_name] = cashflow.base_currency  # one per fund (loader check)

    plans = []
    for schedule in schedules:
        fund, currency, base = schedule.fund, schedule.currency, base_currency[schedule.fund]
        if currency == base:
            continue  # e.g. EUR deals in a EUR fund carry no FX risk
        if schedule.irr is None:
            plans.append(HedgePlan(fund, currency, base, (), schedule.rejected_row_ids, schedule.error))
            continue
        trades = rolling_forwards(flows[fund, currency], schedule.irr, currency, base)
        plans.append(HedgePlan(fund, currency, base, trades, schedule.rejected_row_ids))
    return plans


def rolling_forwards(
    cashflows: Cashflows, rate: float, local_currency: str, base_currency: str
) -> tuple[HedgeTrade, ...]:
    """A forward for each 3-month period from the first to the last cashflow date."""
    dates = roll_dates(min(when for when, _ in cashflows), max(when for when, _ in cashflows))
    trades = []
    for trade_date, value_date in zip(dates, dates[1:], strict=False):
        remaining = [(when, amount) for when, amount in cashflows if when > trade_date]
        exposure = HEDGE_RATIO * npv(rate, remaining, trade_date)
        if abs(exposure) < MIN_NOTIONAL:
            continue
        # Long the local currency (positive exposure): sell it forward for base currency.
        sell, buy = (local_currency, base_currency) if exposure > 0 else (base_currency, local_currency)
        notional = Decimal(abs(exposure)).quantize(NOTIONAL_UNIT)
        trades.append(HedgeTrade(trade_date, value_date, sell, buy, notional))
    return tuple(trades)


def roll_dates(start: date, end: date) -> list[date]:
    """start, start + 3 months, start + 6 months, ... with the last one capped at end."""
    dates = [start]
    step = 1
    while dates[-1] < end:
        dates.append(min(add_months(start, ROLL_MONTHS * step), end))
        step += 1
    return dates


def add_months(start: date, months: int) -> date:
    """Same day `months` later; a month-end date stays a month-end (30/09 + 3 months = 31/12)."""
    month_index = start.month - 1 + months
    year, month = start.year + month_index // 12, month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    if start.day == calendar.monthrange(start.year, start.month)[1]:
        return date(year, month, last_day)
    return date(year, month, min(start.day, last_day))
