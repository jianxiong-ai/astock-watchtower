import tempfile

import pandas as pd

from app.services.excel_import import parse_trade_excel_with_report


def test_parse_trade_excel_with_report_imports_valid_rows_and_reports_errors():
    rows = [
        {
            "symbol": "600519.SH",
            "trade_date": "2026-06-26 10:30:00",
            "side": "买入",
            "price": 1500,
            "quantity": 100,
            "fee": 5,
            "note": "valid",
        },
        {
            "symbol": "600519.SH",
            "trade_date": "2026-06-26 10:31:00",
            "side": "bad",
            "price": 1500,
            "quantity": 100,
            "fee": 5,
            "note": "invalid side",
        },
        {
            "symbol": "",
            "trade_date": "2026-06-26 10:32:00",
            "side": "买入",
            "price": 1500,
            "quantity": 100,
            "fee": 5,
            "note": "blank symbol",
        },
        {
            "symbol": "000001.SZ",
            "trade_date": "2026-06-26 10:33:00",
            "side": "卖出",
            "price": -1,
            "quantity": 100,
            "fee": 5,
            "note": "bad price",
        },
    ]

    with tempfile.NamedTemporaryFile(suffix=".xlsx") as file:
        pd.DataFrame(rows).to_excel(file.name, index=False)
        result = parse_trade_excel_with_report(file.name)

    assert result.total_rows == 4
    assert len(result.trades) == 1
    assert result.trade_row_numbers == [2]
    assert result.skipped_blank_rows == 1
    assert len(result.errors) == 2
    assert result.errors[0].row_number == 3
    assert "交易方向" in result.errors[0].reason
    assert result.errors[1].row_number == 5
    assert "成交价格" in result.errors[1].reason


def test_parse_trade_excel_with_report_rejects_missing_required_columns():
    with tempfile.NamedTemporaryFile(suffix=".xlsx") as file:
        pd.DataFrame([{"symbol": "600519.SH"}]).to_excel(file.name, index=False)
        try:
            parse_trade_excel_with_report(file.name)
        except ValueError as exc:
            assert "缺少必要列" in str(exc)
        else:
            raise AssertionError("missing required columns should raise ValueError")
