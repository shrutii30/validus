from datetime import date
from decimal import Decimal

import pytest

from fund_analytics.analytics import compute_analytics
from fund_analytics.hedging import NOTIONAL_UNIT, add_months, recommend_hedges, roll_dates, rolling_forwards
from fund_analytics.loader import load_cashflows, validate_rows
from fund_analytics.valuation import npv, xirr

START = date(2025, 9, 30)


def plans_of(result):
    _, schedules = compute_analytics(result)
    return {(p.fund, p.local_currency): p for p in recommend_hedges(result, schedules)}


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2025, 9, 30), 3, date(2025, 12, 31)),  # month-end stays month-end
        (date(2025, 12, 31), 2, date(2026, 2, 28)),
        (date(2027, 11, 30), 3, date(2028, 2, 29)),  # leap year
        (date(2025, 1, 15), 3, date(2025, 4, 15)),
        (date(2025, 1, 30), 1, date(2025, 2, 28)),  # day clamped to a shorter month
    ],
)
def test_add_months(start, months, expected):
    assert add_months(start, months) == expected


def test_roll_dates_are_quarterly_and_capped_at_the_end():
    assert roll_dates(START, date(2026, 5, 15)) == [
        START,
        date(2025, 12, 31),
        date(2026, 3, 31),
        date(2026, 5, 15),
    ]


def test_forward_is_sized_on_the_exposure_after_that_days_cashflow():
    # Invest 100, get 110 back a year later: four 3-month forwards.
    flows = [(START, -100.0), (date(2026, 9, 30), 110.0)]
    rate = xirr(flows)

    trades = rolling_forwards(flows, rate, "GBP", "EUR")

    assert [(t.trade_date, t.value_date) for t in trades] == [
        (START, date(2025, 12, 31)),
        (date(2025, 12, 31), date(2026, 3, 31)),
        (date(2026, 3, 31), date(2026, 6, 30)),
        (date(2026, 6, 30), date(2026, 9, 30)),
    ]
    # On the investment date the exposure is the full 100, not NAV(0) = 0.
    assert trades[0].notional_local == Decimal("100.00")
    exposure = npv(rate, flows[1:], date(2026, 3, 31))
    assert trades[2].notional_local == Decimal(exposure).quantize(NOTIONAL_UNIT)
    assert all((t.sell_currency, t.buy_currency) == ("GBP", "EUR") for t in trades)


def test_negative_exposure_buys_the_local_currency():
    # A further investment after the repayment leaves the position owing local currency.
    flows = [(START, -100.0), (date(2025, 12, 31), 200.0), (date(2026, 3, 31), -95.0)]
    rate = 0.10  # any discount rate will do: the sign of the exposure is what's tested

    trades = rolling_forwards(flows, rate, "GBP", "EUR")

    assert (trades[1].sell_currency, trades[1].buy_currency) == ("EUR", "GBP")
    assert trades[1].notional_local == Decimal(95.0 / (1 + rate) ** (90 / 365)).quantize(NOTIONAL_UNIT)


def test_sample_file_hedges_only_non_base_currencies(data_file):
    plans = plans_of(load_cashflows(data_file))

    assert set(plans) == {(fund, ccy) for fund in ("Fund I", "Fund II") for ccy in ("GBP", "USD")}
    for plan in plans.values():
        assert plan.base_currency == "EUR"
        assert len(plan.trades) == 20  # 30/09/2025 to 30/09/2030, every 3 months
        assert plan.trades[0].trade_date == START
        assert plan.trades[-1].value_date == date(2030, 9, 30)
        assert all(t.sell_currency == plan.local_currency for t in plan.trades)


def test_sample_file_first_forward_hedges_the_full_investment(data_file):
    plans = plans_of(load_cashflows(data_file))

    assert plans["Fund I", "GBP"].trades[0].notional_local == Decimal("100000000.00")
    assert plans["Fund II", "USD"].trades[0].notional_local == Decimal("280000000.00")


def test_sample_file_plans_carry_the_data_quality_flag(data_file):
    for (fund, _), plan in plans_of(load_cashflows(data_file)).items():
        assert plan.rejected_row_ids == (("17",) if fund == "Fund I" else ())


def test_no_irr_gives_no_trades_and_the_reason(loan_rows):
    rows = loan_rows("Fund A", "GBP", 1)[1:]  # investment missing

    plan = plans_of(validate_rows(rows))["Fund A", "GBP"]

    assert plan.trades == ()
    assert plan.error is not None and "at least one negative and one positive" in plan.error


def test_base_currency_deals_get_no_plan(loan_rows):
    assert plans_of(validate_rows(loan_rows("Fund A", "EUR", 1))) == {}
