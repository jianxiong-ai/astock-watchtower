from datetime import datetime
from dataclasses import dataclass, field
import math
from typing import Dict, List

import pandas as pd

from app.schemas import TradeCreate


COLUMN_ALIASES: Dict[str, str] = {
    "股票代码": "symbol",
    "代码": "symbol",
    "成交时间": "trade_date",
    "交易时间": "trade_date",
    "日期": "trade_date",
    "方向": "side",
    "买卖": "side",
    "价格": "price",
    "成交价": "price",
    "数量": "quantity",
    "股数": "quantity",
    "费用": "fee",
    "手续费": "fee",
    "备注": "note",
}


@dataclass
class TradeImportError:
    row_number: int
    reason: str
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class TradeImportResult:
    trades: List[TradeCreate] = field(default_factory=list)
    trade_row_numbers: List[int] = field(default_factory=list)
    errors: List[TradeImportError] = field(default_factory=list)
    skipped_blank_rows: int = 0
    total_rows: int = 0
    columns: List[str] = field(default_factory=list)


def _normalize_side(value: object) -> str:
    text = str(value).strip().lower()
    if text in {"买入", "买", "buy", "b"}:
        return "buy"
    if text in {"卖出", "卖", "sell", "s"}:
        return "sell"
    raise ValueError(f"无法识别交易方向：{value}")


def _row_preview(row: pd.Series) -> Dict[str, object]:
    preview: Dict[str, object] = {}
    for key, value in row.to_dict().items():
        if pd.isna(value):
            preview[str(key)] = ""
        elif isinstance(value, (datetime, pd.Timestamp)):
            preview[str(key)] = value.isoformat()
        else:
            preview[str(key)] = str(value)
    return preview


def parse_trade_excel_with_report(file_path: str) -> TradeImportResult:
    df = pd.read_excel(file_path)
    df = df.rename(columns={col: COLUMN_ALIASES.get(str(col).strip(), str(col).strip()) for col in df.columns})
    required = {"symbol", "trade_date", "side", "price", "quantity"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Excel 缺少必要列：{', '.join(sorted(missing))}")

    result = TradeImportResult(total_rows=len(df), columns=[str(item) for item in df.columns])
    for index, row in df.iterrows():
        row_number = int(index) + 2
        if pd.isna(row["symbol"]):
            result.skipped_blank_rows += 1
            continue
        try:
            price = float(row["price"])
            if not math.isfinite(price) or price <= 0:
                raise ValueError("成交价格必须大于 0")
            quantity = int(row["quantity"])
            if quantity <= 0:
                raise ValueError("成交数量必须是正整数")
            fee_raw = row.get("fee", 0)
            fee = 0.0 if pd.isna(fee_raw) else float(fee_raw or 0)
            if not math.isfinite(fee) or fee < 0:
                raise ValueError("交易费用不能为负数")
            result.trades.append(
                TradeCreate(
                    symbol=str(row["symbol"]).strip(),
                    trade_date=pd.to_datetime(row["trade_date"]).to_pydatetime(),
                    side=_normalize_side(row["side"]),
                    price=price,
                    quantity=quantity,
                    fee=fee,
                    note="" if pd.isna(row.get("note", "")) else str(row.get("note", "")),
                )
            )
            result.trade_row_numbers.append(row_number)
        except Exception as exc:
            result.errors.append(TradeImportError(row_number=row_number, reason=str(exc), raw=_row_preview(row)))
    return result


def parse_trade_excel(file_path: str) -> List[TradeCreate]:
    return parse_trade_excel_with_report(file_path).trades
