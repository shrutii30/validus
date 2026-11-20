import pytest

from fund_analytics.__main__ import main


def test_path_argument_is_required(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "csv_path" in capsys.readouterr().err


def test_missing_file_is_reported(tmp_path, capsys):
    assert main([str(tmp_path / "nope.csv")]) == 1
    assert "file not found" in capsys.readouterr().err


def test_report_for_sample_file(data_file, capsys):
    assert main([str(data_file)]) == 0

    output = capsys.readouterr().out
    assert "126 rows, 125 valid, 1 rejected, 2 fixes" in output
    assert "ID 17   Local Currency: unknown currency code 'GPB'" in output
    assert "Fund I   GBP         9.4771%  WARNING incomplete data: rejected row(s) 17" in output
    assert "Fund II  Fund (EUR) 10.0476%\n" in output
    assert "NAV schedule, Fund I (local currency" in output
    assert "  2030-09-30     150,000,000.00     100,000,000.00     200,000,000.00" in output
    assert "  2029-09-30     150,700,406.74                  -" in output  # row 17's date
    assert "FX hedge recommendations (3-month rolling forwards, 100% of exposure" in output
    assert "  Fund I, GBP vs EUR  WARNING incomplete data: rejected row(s) 17" in output
    assert "    2025-09-30  2025-12-31  GBP  EUR      100,000,000.00" in output
    assert "Fund I, EUR vs EUR" not in output
    assert "-0.00" not in output
    assert "FAILED" not in output
