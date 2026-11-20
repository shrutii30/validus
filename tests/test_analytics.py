import pytest

from fund_analytics.analytics import IrrLevel, compute_analytics
from fund_analytics.loader import Rejection, load_cashflows, validate_rows


def irrs_of(result):
    irrs, _ = compute_analytics(result)
    return irrs


def by_key(irrs):
    return {(irr.fund, irr.level, irr.currency): irr for irr in irrs}


def test_sample_file_irrs(data_file):
    irrs = by_key(irrs_of(load_cashflows(data_file)))

    assert len(irrs) == 8  # 2 funds x (3 currencies + fund level)
    # EUR and USD legs are identical in shape across funds, so their IRRs match.
    assert irrs["Fund I", IrrLevel.CURRENCY, "EUR"].irr == pytest.approx(0.078870, abs=1e-6)
    assert irrs["Fund I", IrrLevel.CURRENCY, "USD"].irr == pytest.approx(0.120515, abs=1e-6)
    assert irrs["Fund II", IrrLevel.CURRENCY, "EUR"].irr == pytest.approx(0.078870, abs=1e-6)
    assert irrs["Fund II", IrrLevel.CURRENCY, "USD"].irr == pytest.approx(0.120515, abs=1e-6)
    # Fund I GBP is missing the rejected coupon (row 17), so it is lower than Fund II GBP.
    assert irrs["Fund I", IrrLevel.CURRENCY, "GBP"].irr == pytest.approx(0.094771, abs=1e-6)
    assert irrs["Fund II", IrrLevel.CURRENCY, "GBP"].irr == pytest.approx(0.099507, abs=1e-6)
    assert irrs["Fund I", IrrLevel.FUND, "EUR"].irr == pytest.approx(0.099233, abs=1e-6)
    assert irrs["Fund II", IrrLevel.FUND, "EUR"].irr == pytest.approx(0.100476, abs=1e-6)


def test_fund_level_irr_lies_between_its_currency_irrs(data_file):
    irrs = irrs_of(load_cashflows(data_file))
    for fund in ("Fund I", "Fund II"):
        currency_irrs = [i.irr for i in irrs if i.fund == fund and i.level == IrrLevel.CURRENCY]
        fund_irr = next(i.irr for i in irrs if i.fund == fund and i.level == IrrLevel.FUND)
        assert min(currency_irrs) < fund_irr < max(currency_irrs)


def test_row_17_flags_every_fund_i_result_and_nothing_in_fund_ii(data_file):
    for irr in irrs_of(load_cashflows(data_file)):
        expected = ("17",) if irr.fund == "Fund I" else ()
        assert irr.rejected_row_ids == expected, (irr.fund, irr.currency)


def test_rejection_flags_every_result_of_its_fund_only(loan_rows):
    result = validate_rows(
        loan_rows("Fund A", "GBP", 1) + loan_rows("Fund A", "USD", 3) + loan_rows("Fund B", "GBP", 5)
    )
    result.rejected.append(Rejection("9", ("bad date",), {"Fund Name": " Fund A", "Local Currency": "USD"}))

    for irr in irrs_of(result):
        expected = ("9",) if irr.fund == "Fund A" else ()
        assert irr.rejected_row_ids == expected, (irr.fund, irr.currency)


def test_rejection_with_unreadable_fund_flags_every_fund(loan_rows):
    result = validate_rows(loan_rows("Fund A", "GBP", 1) + loan_rows("Fund B", "GBP", 3))
    result.rejected.append(Rejection("9", ("wrong field count",), {"fields": ["9", "Fund ?"]}))

    assert all(irr.rejected_row_ids == ("9",) for irr in irrs_of(result))


def test_missing_investment_gives_no_irr_instead_of_crashing(loan_rows):
    rows = loan_rows("Fund A", "GBP", 1)[1:] + loan_rows("Fund A", "USD", 3)

    irrs = by_key(irrs_of(validate_rows(rows)))

    gbp = irrs["Fund A", IrrLevel.CURRENCY, "GBP"]
    assert gbp.irr is None
    assert "at least one negative and one positive" in gbp.error
    assert irrs["Fund A", IrrLevel.CURRENCY, "USD"].irr == pytest.approx(0.10, abs=1e-9)
