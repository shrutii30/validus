"""Usage: uv run python -m fund_analytics path/to/cashflows.csv"""

import argparse
import sys
from pathlib import Path

from fund_analytics.analytics import IrrLevel, NavSchedule, compute_analytics
from fund_analytics.hedging import HEDGE_RATIO, ROLL_MONTHS, HedgePlan, recommend_hedges
from fund_analytics.loader import load_cashflows


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fund_analytics",
        description=(
            "Validate a projected-cashflow CSV, report fixes and rejected rows, "
            "and compute IRRs and NAV schedules per fund."
        ),
    )
    parser.add_argument("csv_path", type=Path, help="path to the cashflow CSV file")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    path = parse_args(argv).csv_path
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    result = load_cashflows(path)
    total = len(result.valid) + len(result.rejected)
    print(
        f"{path.name}: {total} rows, {len(result.valid)} valid, "
        f"{len(result.rejected)} rejected, {len(result.fixes)} fixes"
    )

    if result.fixes:
        print("\nFixed (formatting only):")
        for fix in result.fixes:
            print(f"  ID {fix.row_id:<4} {fix.column}: {fix.raw!r} -> {fix.cleaned!r}")

    if result.rejected:
        print("\nRejected:")
        for rejection in result.rejected:
            print(f"  ID {rejection.row_id!s:<4} {'; '.join(rejection.reasons)}")

    print("\nIRR (actual dates, 365-day year):")
    irrs, schedules = compute_analytics(result)
    for irr in irrs:
        label = irr.currency if irr.level is IrrLevel.CURRENCY else f"Fund ({irr.currency})"
        value = f"{irr.irr:8.4%}" if irr.irr is not None else f"n/a ({irr.error})"
        print(f"  {irr.fund:<8} {label:<10} {value}{_warning(irr.rejected_row_ids)}")

    print_nav_schedules(schedules)
    print_hedges(recommend_hedges(result, schedules))
    return 0


def print_nav_schedules(schedules: list[NavSchedule]) -> None:
    """One table per fund: a row per date, a column per currency (NAV in local currency)."""
    for fund in sorted({s.fund for s in schedules}):
        fund_schedules = [s for s in schedules if s.fund == fund]
        print(f"\nNAV schedule, {fund} (local currency, discounted at each currency's IRR):")
        for s in fund_schedules:
            status = (
                "NAV(0) = 0 and final NAV = exit value: OK"
                if s.passes_sanity_checks
                else (f"FAILED ({s.error})" if s.error else "FAILED")
            )
            print(f"  {s.currency}: {status}{_warning(s.rejected_row_ids)}")

        navs = {s.currency: dict(s.points) for s in fund_schedules}
        dates = sorted({d for points in navs.values() for d in points})
        print(f"  {'Date':<10} " + " ".join(f"{s.currency:>18}" for s in fund_schedules))
        for d in dates:
            cells = (
                f"{_no_negative_zero(navs[s.currency][d]):>18,.2f}" if d in navs[s.currency] else f"{'-':>18}"
                for s in fund_schedules
            )
            print(f"  {d.isoformat():<10} " + " ".join(cells))


def print_hedges(plans: list[HedgePlan]) -> None:
    """One table per non-base-currency exposure: a row per 3-month FX forward."""
    print(
        f"\nFX hedge recommendations ({ROLL_MONTHS}-month rolling forwards, {HEDGE_RATIO:.0%} of exposure;"
        " forward rates left to execution):"
    )
    if not plans:
        print("  none: every exposure is in its fund's base currency")
    for plan in plans:
        pair = f"{plan.local_currency} vs {plan.base_currency}"
        print(f"\n  {plan.fund}, {pair}{_warning(plan.rejected_row_ids)}")
        if plan.error:
            print(f"    n/a ({plan.error})")
            continue
        print(f"    {'Trade date':<10}  {'Value date':<10}  {'Sell':<4} {'Buy':<4} {'Notional (local)':>18}")
        for trade in plan.trades:
            print(
                f"    {trade.trade_date.isoformat():<10}  {trade.value_date.isoformat():<10}  "
                f"{trade.sell_currency:<4} {trade.buy_currency:<4} {trade.notional_local:>18,.2f}"
            )


def _warning(rejected_row_ids: tuple[str, ...]) -> str:
    if not rejected_row_ids:
        return ""
    return f"  WARNING incomplete data: rejected row(s) {', '.join(rejected_row_ids)}"


def _no_negative_zero(value: float) -> float:
    # Rounding noise like -0.000004 would otherwise print as "-0.00".
    return 0.0 if abs(value) < 0.005 else value


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
