"""NPV, IRR and NAV schedule using actual dates and a 365-day year (Excel's XIRR convention)."""

from collections.abc import Sequence
from datetime import date

DAYS_PER_YEAR = 365.0

# Bracket for the solver: just above -100% up to +1,000% a year.
LOWEST_RATE = -0.9999
HIGHEST_RATE = 10.0
TOLERANCE = 1e-12
MAX_ITERATIONS = 500

Cashflows = Sequence[tuple[date, float]]


def npv(rate: float, cashflows: Cashflows, as_of: date) -> float:
    """Value of the cashflows at `as_of`, discounted (or compounded, if earlier) at `rate`."""
    # float() because mypy types float ** float as Any (it can be complex for negative bases).
    return float(
        sum(amount / (1.0 + rate) ** ((when - as_of).days / DAYS_PER_YEAR) for when, amount in cashflows)
    )


def xirr(cashflows: Cashflows) -> float:
    """Annual rate at which the cashflows' NPV at the first cashflow date is zero.

    Solved by bisection: slower than Newton's method but always converges once the
    root is bracketed, which matters more here than speed.
    """
    if not any(amount < 0 for _, amount in cashflows) or not any(amount > 0 for _, amount in cashflows):
        raise ValueError("IRR needs at least one negative and one positive cashflow")

    start = min(when for when, _ in cashflows)
    low, high = LOWEST_RATE, HIGHEST_RATE
    npv_low = npv(low, cashflows, start)
    if npv_low * npv(high, cashflows, start) > 0:
        raise ValueError(f"no IRR between {low:.2%} and {high:.0%}")

    for _ in range(MAX_ITERATIONS):
        mid = (low + high) / 2
        npv_mid = npv(mid, cashflows, start)
        if abs(npv_mid) < TOLERANCE or (high - low) / 2 < TOLERANCE:
            return mid
        if npv_low * npv_mid < 0:
            high = mid
        else:
            low, npv_low = mid, npv_mid
    return (low + high) / 2


def nav_schedule(cashflows: Cashflows, rate: float) -> list[tuple[date, float]]:
    """NAV on every cashflow date t = NPV at t of all cashflows dated on or after t.

    Cashflows on t itself count as remaining, so NAV is the value just before they are
    paid. With `rate` = the IRR this makes NAV on the first date 0 and NAV on the last
    date equal to the exit cashflow, which are the brief's two sanity checks.
    """
    dates = sorted({when for when, _ in cashflows})
    return [
        (as_of, npv(rate, [(when, amount) for when, amount in cashflows if when >= as_of], as_of))
        for as_of in dates
    ]
