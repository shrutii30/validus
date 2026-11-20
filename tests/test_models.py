from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fund_analytics.models import Cashflow, CashflowType


def validate(row: dict) -> tuple[Cashflow, list]:
    context: dict[str, list[tuple[str, object, object]]] = {"fixes": []}
    return Cashflow.model_validate(row, context=context), context["fixes"]


def rejection_reasons(row: dict) -> str:
    with pytest.raises(ValidationError) as exc_info:
        Cashflow.model_validate(row)
    return str(exc_info.value)


def test_clean_row_is_parsed_without_fixes(raw_row):
    cashflow, fixes = validate(raw_row)

    assert cashflow.id == 2
    assert cashflow.fund_name == "Fund I"
    assert cashflow.cashflow_date == date(2025, 12, 31)
    assert cashflow.cashflow_type is CashflowType.INTEREST
    assert cashflow.local_currency == "GBP"
    assert cashflow.amount_local == Decimal(2500000)
    assert cashflow.amount_base == Decimal(2864345)
    assert cashflow.base_currency == "EUR"
    assert fixes == []


# --- Dates -------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_date",
    [
        " 30/09/2030  00:00:00",  # row 21: extra spaces and seconds
        "30/09/2030  00:00:00`",  # row 51: stray backtick
        "30/09/2030",  # no time
    ],
)
def test_date_formatting_noise_is_fixed_and_logged(raw_row, raw_date):
    cashflow, fixes = validate({**raw_row, "Date": raw_date})

    assert cashflow.cashflow_date == date(2030, 9, 30)
    assert fixes == [("Date", raw_date, "2030-09-30")]


@pytest.mark.parametrize("raw_date", ["2030-09-30", "31/02/2030 00:00", "not a date", ""])
def test_unreadable_date_is_rejected(raw_row, raw_date):
    assert "unreadable date" in rejection_reasons({**raw_row, "Date": raw_date})


# --- Currency ----------------------------------------------------------------


def test_currency_typo_is_rejected_not_corrected(raw_row):
    assert "unknown currency code 'GPB'" in rejection_reasons({**raw_row, "Local Currency": "GPB"})


def test_unknown_base_currency_is_rejected(raw_row):
    assert "unknown currency code 'XXX'" in rejection_reasons({**raw_row, "Base Currency": "XXX"})


def test_currency_case_and_spaces_are_fixed(raw_row):
    cashflow, fixes = validate({**raw_row, "Local Currency": " gbp "})

    assert cashflow.local_currency == "GBP"
    assert fixes == [("Local Currency", " gbp ", "GBP")]


# --- Cashflow type -----------------------------------------------------------


def test_cashflow_type_case_and_spaces_are_fixed(raw_row):
    cashflow, fixes = validate(
        {**raw_row, "Cashflow Type": " principal  repayment", "Cashflow Amount Local": 100}
    )

    assert cashflow.cashflow_type is CashflowType.PRINCIPAL_REPAYMENT
    assert fixes == [("Cashflow Type", " principal  repayment", "Principal Repayment")]


def test_unknown_cashflow_type_is_rejected(raw_row):
    assert "unknown cashflow type 'Fee'" in rejection_reasons({**raw_row, "Cashflow Type": "Fee"})


# --- Amounts -----------------------------------------------------------------


@pytest.mark.parametrize("raw_amount", ["2,500,000", "2500000"])  # ID 27/51 have no separators
def test_amount_with_or_without_thousands_separators_is_not_a_fix(raw_row, raw_amount):
    cashflow, fixes = validate({**raw_row, "Cashflow Amount Local": raw_amount})

    assert cashflow.amount_local == Decimal(2500000)
    assert fixes == []


@pytest.mark.parametrize(
    ("raw_amount", "expected"),
    [(" 2,500,000 ", Decimal(2500000)), ("2 500 000.50", Decimal("2500000.50"))],
)
def test_amount_formatting_noise_is_fixed_and_logged(raw_row, raw_amount, expected):
    cashflow, fixes = validate({**raw_row, "Cashflow Amount Local": raw_amount})

    assert cashflow.amount_local == expected
    assert fixes == [("Cashflow Amount Local", raw_amount, str(expected))]


@pytest.mark.parametrize(
    ("raw_amount", "reason"),
    [
        ("abc", "Input should be a valid decimal"),
        ("", "Input should be a valid decimal"),
        ("NaN", "Input should be a finite number"),
        ("inf", "Input should be a finite number"),
        (True, "Decimal input should be an integer, float, string or Decimal object"),
    ],
)
def test_non_numeric_amount_is_rejected(raw_row, raw_amount, reason):
    assert reason in rejection_reasons({**raw_row, "Cashflow Amount Base": raw_amount})


# --- Sign --------------------------------------------------------------------


def test_positive_investment_is_rejected(raw_row):
    row = {**raw_row, "Cashflow Type": "Investment"}
    assert "wrong sign for Investment, expected negative" in rejection_reasons(row)


def test_negative_interest_is_rejected(raw_row):
    row = {**raw_row, "Cashflow Amount Base": -2864345}
    assert "wrong sign for Interest, expected positive" in rejection_reasons(row)


def test_zero_amount_is_rejected(raw_row):
    assert "wrong sign" in rejection_reasons({**raw_row, "Cashflow Amount Local": 0})


# --- Missing values ----------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        "Fund Name",
        "Date",
        "Cashflow Type",
        "Local Currency",
        "Cashflow Amount Local",
        "Cashflow Amount Base",
        "Base Currency",
    ],
)
def test_missing_value_is_rejected(raw_row, column):
    assert "missing value" in rejection_reasons({**raw_row, column: None})


def test_missing_id_is_rejected(raw_row):
    assert "Input should be a valid integer" in rejection_reasons({**raw_row, "ID": None})


def test_blank_fund_name_is_rejected(raw_row):
    assert "Fund Name" in rejection_reasons({**raw_row, "Fund Name": "   "})
