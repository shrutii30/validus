from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def data_file() -> Path:
    """The sample cashflow CSV from the brief."""
    return Path(__file__).resolve().parents[1] / "data" / "CST_Case_Study_data.csv"


@pytest.fixture
def raw_row() -> dict:
    """A clean row exactly as it comes out of the CSV reader."""
    return {
        "ID": "2",
        "Fund Name": "Fund I",
        "Date": "31/12/2025 00:00",
        "Cashflow Type": "Interest",
        "Local Currency": "GBP",
        "Cashflow Amount Local": "2,500,000",
        "Cashflow Amount Base": "2,864,345",
        "Base Currency": "EUR",
    }


@pytest.fixture
def loan_rows() -> Callable[[str, str, int], list[dict]]:
    """Build a loan's rows: invest 100 on 30/09/2025, get 110 back a year later (10% IRR)."""

    def build(fund: str, currency: str, first_id: int) -> list[dict]:
        common = {"Fund Name": fund, "Local Currency": currency, "Base Currency": "EUR"}
        return [
            {
                **common,
                "ID": first_id,
                "Date": "30/09/2025",
                "Cashflow Type": "Investment",
                "Cashflow Amount Local": "-100",
                "Cashflow Amount Base": "-100",
            },
            {
                **common,
                "ID": first_id + 1,
                "Date": "30/09/2026",
                "Cashflow Type": "Principal Repayment",
                "Cashflow Amount Local": "110",
                "Cashflow Amount Base": "110",
            },
        ]

    return build
