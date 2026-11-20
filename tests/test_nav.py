from datetime import date, timedelta

import pytest

from fund_analytics.analytics import compute_analytics
from fund_analytics.loader import load_cashflows, validate_rows
from fund_analytics.valuation import nav_schedule, xirr

START = date(2025, 9, 30)


def schedules_of(result):
    _, schedules = compute_analytics(result)
    return schedules


def test_simple_loan_schedule():
    # Invest 100, receive 10 after a year and 110 after two: IRR is exactly 10%.
    flows = [
        (START, -100.0),
        (START + timedelta(days=365), 10.0),
        (START + timedelta(days=730), 110.0),
    ]
    rate = xirr(flows)

    schedule = nav_schedule(flows, rate)

    assert [d for d, _ in schedule] == [d for d, _ in flows]
    assert schedule[0][1] == pytest.approx(0.0, abs=1e-6)
    # One year in, before the coupon is paid: coupon 10 + 110 discounted one year = 110.
    assert schedule[1][1] == pytest.approx(110.0)
    assert schedule[2][1] == pytest.approx(110.0)


def test_cashflows_on_the_same_date_are_combined():
    flows = [
        (START, -100.0),
        (START + timedelta(days=365), 10.0),
        (START + timedelta(days=365), 100.0),
    ]

    schedule = nav_schedule(flows, xirr(flows))

    assert len(schedule) == 2
    assert schedule[1][1] == pytest.approx(110.0)


def test_sample_file_schedules_pass_the_briefs_sanity_checks(data_file):
    schedules = schedules_of(load_cashflows(data_file))

    assert {(s.fund, s.currency) for s in schedules} == {
        (fund, currency) for fund in ("Fund I", "Fund II") for currency in ("EUR", "GBP", "USD")
    }
    for s in schedules:
        assert s.passes_sanity_checks, (s.fund, s.currency)
        assert s.points[0][0] == date(2025, 9, 30)
        assert s.points[-1] == (date(2030, 9, 30), pytest.approx(float(s.exit_value), abs=0.01))


def test_sample_file_exit_values_and_point_counts(data_file):
    schedules = {(s.fund, s.currency): s for s in schedules_of(load_cashflows(data_file))}

    assert schedules["Fund I", "GBP"].exit_value == 100_000_000
    assert schedules["Fund II", "USD"].exit_value == 280_000_000
    # 21 quarterly dates, except Fund I GBP which lost 30/09/2029 to rejected row 17.
    assert len(schedules["Fund II", "GBP"].points) == 21
    assert len(schedules["Fund I", "GBP"].points) == 20
    assert date(2029, 9, 30) not in dict(schedules["Fund I", "GBP"].points)


def test_schedule_carries_the_data_quality_flag(data_file):
    for s in schedules_of(load_cashflows(data_file)):
        assert s.rejected_row_ids == (("17",) if s.fund == "Fund I" else ())


def test_no_irr_gives_an_empty_schedule_that_fails_the_checks(loan_rows):
    rows = loan_rows("Fund A", "GBP", 1)[1:]  # investment missing

    (schedule,) = schedules_of(validate_rows(rows))

    assert schedule.points == ()
    assert schedule.error is not None
    assert not schedule.passes_sanity_checks
