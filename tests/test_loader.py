import pytest

from fund_analytics.loader import load_cashflows, read_rows, validate_rows

HEADER = (
    "ID,Fund Name,Date,Cashflow Type,Local Currency,"
    "Cashflow Amount Local,Cashflow Amount Base,Base Currency\n"
)
GOOD_LINE = '2,Fund I,31/12/2025 00:00,Interest,GBP,"2,500,000","2,864,345",EUR\n'


def test_sample_file_planted_errors_are_found(data_file):
    result = load_cashflows(data_file)

    assert len(result.valid) == 125
    assert [(r.row_id, r.reasons) for r in result.rejected] == [
        ("17", ("Local Currency: unknown currency code 'GPB'",))
    ]
    assert [(f.row_id, f.column, f.cleaned) for f in result.fixes] == [
        (21, "Date", "2030-09-30"),
        (51, "Date", "2027-09-30"),
    ]


def test_sample_file_contains_both_funds_and_three_currencies(data_file):
    result = load_cashflows(data_file)

    assert {c.fund_name for c in result.valid} == {"Fund I", "Fund II"}
    assert {c.local_currency for c in result.valid} == {"GBP", "EUR", "USD"}
    assert {c.base_currency for c in result.valid} == {"EUR"}


def test_duplicate_ids_reject_every_copy(raw_row):
    other = {**raw_row, "Date": "31/03/2026 00:00"}
    result = validate_rows([raw_row, other, {**raw_row, "ID": 3}])

    assert [c.id for c in result.valid] == [3]
    assert [(r.row_id, r.reasons) for r in result.rejected] == [
        (2, ("ID: duplicate ID 2",)),
        (2, ("ID: duplicate ID 2",)),
    ]


def test_conflicting_base_currencies_reject_the_whole_fund(raw_row):
    rows = [
        raw_row,
        {**raw_row, "ID": 3},
        {**raw_row, "ID": 4, "Base Currency": "USD"},
        {**raw_row, "ID": 5, "Fund Name": "Fund II"},
    ]
    result = validate_rows(rows)

    assert [c.id for c in result.valid] == [5]
    reason = ("Base Currency: Fund I has conflicting base currencies EUR, USD",)
    assert [(r.row_id, r.reasons) for r in result.rejected] == [(2, reason), (3, reason), (4, reason)]


def test_fixes_are_dropped_for_rows_rejected_by_cross_row_checks(raw_row):
    messy = {**raw_row, "Date": " 31/12/2025 00:00"}
    result = validate_rows([messy, {**raw_row, "Date": "31/03/2026 00:00"}])

    assert result.valid == []
    assert result.fixes == []


def test_missing_column_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("ID,Fund Name\n1,Fund I\n")

    with pytest.raises(ValueError, match="missing columns"):
        read_rows(path)


def test_blank_rows_are_skipped(tmp_path):
    path = tmp_path / "blank.csv"
    path.write_text(HEADER + GOOD_LINE + "\n,,,,,,,\n")

    rows, malformed = read_rows(path)

    assert len(rows) == 1
    assert malformed == []


def test_blank_cell_becomes_missing_value(tmp_path):
    path = tmp_path / "blank_cell.csv"
    path.write_text(HEADER + GOOD_LINE.replace("GBP", ""))

    result = load_cashflows(path)

    assert [(r.row_id, r.reasons) for r in result.rejected] == [("2", ("Local Currency: missing value",))]


def test_unquoted_comma_in_amount_is_rejected(tmp_path):
    path = tmp_path / "unquoted.csv"
    path.write_text(HEADER + "3,Fund I,31/12/2025 00:00,Interest,GBP,2,500,000,2864345,EUR\n")

    result = load_cashflows(path)

    assert result.valid == []
    assert [(r.row_id, r.reasons) for r in result.rejected] == [
        ("3", ("expected 8 fields, got 10 (unquoted comma in a number?)",))
    ]


def test_byte_order_mark_is_ignored(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(HEADER + GOOD_LINE, encoding="utf-8-sig")

    assert len(load_cashflows(path).valid) == 1
