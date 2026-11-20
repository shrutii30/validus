from datetime import date, timedelta

import pytest

from fund_analytics.valuation import npv, xirr

START = date(2025, 9, 30)


def test_one_year_ten_percent():
    flows = [(START, -100.0), (START + timedelta(days=365), 110.0)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)


def test_two_years_compounded():
    flows = [(START, -100.0), (START + timedelta(days=730), 121.0)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)


def test_negative_return():
    flows = [(START, -100.0), (START + timedelta(days=365), 80.0)]
    assert xirr(flows) == pytest.approx(-0.20, abs=1e-9)


def test_npv_at_irr_is_zero_for_a_quarterly_coupon_loan():
    # Same shape as the sample loans: invest, 19 quarterly coupons, principal back.
    coupon_dates = [date(2025 + (m - 1) // 12, (m - 1) % 12 + 1, 1) for m in range(13, 70, 3)]
    flows = [(START, -150.0)] + [(d, 3.0) for d in coupon_dates] + [(date(2030, 9, 30), 150.0)]

    rate = xirr(flows)

    assert npv(rate, flows, START) == pytest.approx(0.0, abs=1e-6)


def test_order_of_cashflows_does_not_matter():
    flows = [(START + timedelta(days=365), 110.0), (START, -100.0)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)


@pytest.mark.parametrize(
    "flows",
    [
        [(START, 100.0), (START + timedelta(days=365), 110.0)],  # no outflow
        [(START, -100.0), (START + timedelta(days=365), -10.0)],  # no inflow
        [],
    ],
)
def test_irr_needs_both_signs(flows):
    with pytest.raises(ValueError, match="at least one negative and one positive"):
        xirr(flows)


def test_npv_before_and_after_as_of_date():
    flows = [(START + timedelta(days=365), 110.0)]
    assert npv(0.10, flows, START) == pytest.approx(100.0)
    assert npv(0.10, flows, START + timedelta(days=730)) == pytest.approx(121.0)
