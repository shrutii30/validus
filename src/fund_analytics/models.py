"""Pydantic model for one projected cashflow row, including its cleaning rules.

Cleaning is limited to unambiguous formatting noise (whitespace, stray
characters, date/number formatting). Every such fix is recorded in the
validation context under "fixes" so the loader can report it. Anything that
would require guessing business data raises a ValueError, which rejects the row.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

# Fixed allow-list of ISO 4217 codes; anything else (e.g. "GPB") is rejected.
KNOWN_CURRENCIES = frozenset(
    {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SEK", "NOK", "DKK", "SGD", "HKD"}
)

# The first format is the file's standard one; the others are tolerated but logged as fixes.
DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y")

# Characters trimmed from the ends of text values, e.g. the stray backtick in row 51.
STRAY_CHARS = " \t\r\n`'\""


class CashflowType(StrEnum):
    INVESTMENT = "Investment"
    INTEREST = "Interest"
    PRINCIPAL_REPAYMENT = "Principal Repayment"


def _column(info: ValidationInfo) -> str:
    name = info.field_name
    assert name is not None  # always set inside a field validator
    return Cashflow.model_fields[name].alias or name


def _record_fix(info: ValidationInfo, raw: object, cleaned: object) -> None:
    if info.context is not None:
        info.context.setdefault("fixes", []).append((_column(info), raw, cleaned))


def _require_text(value: object) -> str:
    if value is None:
        raise ValueError("missing value")
    if not isinstance(value, str):
        raise ValueError(f"expected text, got {value!r}")
    return value


class Cashflow(BaseModel):
    model_config = ConfigDict(frozen=True, validate_by_name=True, validate_by_alias=True)

    id: int = Field(alias="ID", gt=0)
    fund_name: str = Field(alias="Fund Name", min_length=1)
    cashflow_date: date = Field(alias="Date")
    cashflow_type: CashflowType = Field(alias="Cashflow Type")
    local_currency: str = Field(alias="Local Currency")
    amount_local: Decimal = Field(alias="Cashflow Amount Local")
    amount_base: Decimal = Field(alias="Cashflow Amount Base")
    base_currency: str = Field(alias="Base Currency")

    @field_validator("fund_name", mode="before")
    @classmethod
    def _clean_text(cls, value: object, info: ValidationInfo) -> str:
        raw = _require_text(value)
        cleaned = " ".join(raw.split())
        if cleaned != raw:
            _record_fix(info, raw, cleaned)
        return cleaned

    @field_validator("cashflow_date", mode="before")
    @classmethod
    def _parse_date(cls, value: object, info: ValidationInfo) -> date:
        raw = _require_text(value)
        cleaned = " ".join(raw.strip(STRAY_CHARS).split())
        for position, fmt in enumerate(DATE_FORMATS):
            try:
                parsed = datetime.strptime(cleaned, fmt).date()
            except ValueError:
                continue
            if cleaned != raw or position != 0:
                _record_fix(info, raw, parsed.isoformat())
            return parsed
        raise ValueError(f"unreadable date {raw!r}, expected DD/MM/YYYY")

    @field_validator("cashflow_type", mode="before")
    @classmethod
    def _parse_type(cls, value: object, info: ValidationInfo) -> CashflowType:
        raw = _require_text(value)
        cleaned = " ".join(raw.split())
        for member in CashflowType:
            if cleaned.casefold() == member.value.casefold():
                if member.value != raw:
                    _record_fix(info, raw, member.value)
                return member
        allowed = ", ".join(member.value for member in CashflowType)
        raise ValueError(f"unknown cashflow type {raw!r}, expected one of: {allowed}")

    @field_validator("local_currency", "base_currency", mode="before")
    @classmethod
    def _check_currency(cls, value: object, info: ValidationInfo) -> str:
        raw = _require_text(value)
        cleaned = raw.strip().upper()
        if cleaned not in KNOWN_CURRENCIES:
            raise ValueError(f"unknown currency code {raw!r}")
        if cleaned != raw:
            _record_fix(info, raw, cleaned)
        return cleaned

    @field_validator("amount_local", "amount_base", mode="before")
    @classmethod
    def _clean_amount(cls, value: object, info: ValidationInfo) -> object:
        # Pydantic then parses the Decimal, rejecting non-numbers, NaN and infinity.
        if value is None:
            raise ValueError("missing value")
        if not isinstance(value, str):
            return value
        # Thousands separators are a normal number format in the CSV, so removing them is not a fix.
        without_commas = value.replace(",", "")
        cleaned = "".join(without_commas.split())
        if cleaned != without_commas:
            _record_fix(info, value, cleaned)
        return cleaned

    @model_validator(mode="after")
    def _check_sign(self) -> "Cashflow":
        must_be_negative = self.cashflow_type is CashflowType.INVESTMENT
        expected = "negative" if must_be_negative else "positive"
        for column, amount in (
            ("Cashflow Amount Local", self.amount_local),
            ("Cashflow Amount Base", self.amount_base),
        ):
            if amount == 0 or (amount < 0) != must_be_negative:
                raise ValueError(
                    f"{column} {amount} has the wrong sign for {self.cashflow_type.value}, "
                    f"expected {expected}"
                )
        return self
