"""Read the cashflow CSV and split rows into valid, fixed and rejected."""

import csv
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from fund_analytics.models import Cashflow

EXPECTED_COLUMNS = tuple(f.alias for f in Cashflow.model_fields.values())


@dataclass(frozen=True)
class Fix:
    row_id: int
    column: str
    raw: object
    cleaned: object


@dataclass(frozen=True)
class Rejection:
    row_id: object
    reasons: tuple[str, ...]
    raw: dict[str, Any]


@dataclass
class LoadResult:
    valid: list[Cashflow] = field(default_factory=list)
    fixes: list[Fix] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)


def read_rows(path: Path | str) -> tuple[list[dict[str, Any]], list[Rejection]]:
    """Return CSV rows as dicts keyed by header (blank cells as None), plus wrong-length rows."""
    # utf-8-sig also accepts the byte-order mark that Excel adds to CSV exports.
    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        header = [column.strip() for column in next(reader, [])]
        missing = [column for column in EXPECTED_COLUMNS if column not in header]
        if missing:
            raise ValueError(f"{path}: missing columns {missing}")

        rows, malformed = [], []
        for line in reader:
            if not any(cell.strip() for cell in line):
                continue
            if len(line) != len(header):
                reason = f"expected {len(header)} fields, got {len(line)} (unquoted comma in a number?)"
                malformed.append(Rejection(line[0], (reason,), {"fields": line}))
                continue
            rows.append(
                {column: cell if cell.strip() else None for column, cell in zip(header, line, strict=True)}
            )
    return rows, malformed


def validate_rows(rows: Iterable[dict[str, Any]]) -> LoadResult:
    """Validate each row on its own, then apply the cross-row checks."""
    result = LoadResult()
    for raw in rows:
        context: dict[str, list[tuple[str, object, object]]] = {"fixes": []}
        try:
            cashflow = Cashflow.model_validate(raw, context=context)
        except ValidationError as exc:
            reasons = tuple(_describe(error) for error in exc.errors())
            result.rejected.append(Rejection(raw.get("ID"), reasons, raw))
            continue
        result.valid.append(cashflow)
        result.fixes.extend(Fix(cashflow.id, *fix) for fix in context["fixes"])

    for check in (_reject_duplicate_ids, _reject_inconsistent_base_currency):
        result.valid, rejected = check(result.valid)
        result.rejected.extend(rejected)

    valid_ids = {cashflow.id for cashflow in result.valid}
    result.fixes = [fix for fix in result.fixes if fix.row_id in valid_ids]
    return result


def load_cashflows(path: Path | str) -> LoadResult:
    rows, malformed = read_rows(path)
    result = validate_rows(rows)
    result.rejected.extend(malformed)
    return result


def _describe(error: ErrorDetails) -> str:
    message = error["msg"].removeprefix("Value error, ")
    location = ".".join(str(part) for part in error["loc"])
    return f"{location}: {message}" if location else message


def _reject(cashflow: Cashflow, reason: str) -> Rejection:
    return Rejection(cashflow.id, (reason,), cashflow.model_dump(by_alias=True))


def _reject_duplicate_ids(
    cashflows: list[Cashflow],
) -> tuple[list[Cashflow], list[Rejection]]:
    # We can't tell which copy is right, so every row sharing an ID is rejected.
    counts = Counter(cashflow.id for cashflow in cashflows)
    kept = [cashflow for cashflow in cashflows if counts[cashflow.id] == 1]
    rejected = [
        _reject(cashflow, f"ID: duplicate ID {cashflow.id}")
        for cashflow in cashflows
        if counts[cashflow.id] > 1
    ]
    return kept, rejected


def _reject_inconsistent_base_currency(
    cashflows: list[Cashflow],
) -> tuple[list[Cashflow], list[Rejection]]:
    # Base currency is fund reference data: if a fund's rows disagree we can't tell which
    # is right, so every row of that fund is rejected.
    by_fund: dict[str, set[str]] = defaultdict(set)
    for cashflow in cashflows:
        by_fund[cashflow.fund_name].add(cashflow.base_currency)

    kept, rejected = [], []
    for cashflow in cashflows:
        bases = by_fund[cashflow.fund_name]
        if len(bases) == 1:
            kept.append(cashflow)
        else:
            reason = (
                f"Base Currency: {cashflow.fund_name} has conflicting base currencies "
                f"{', '.join(sorted(bases))}"
            )
            rejected.append(_reject(cashflow, reason))
    return kept, rejected
