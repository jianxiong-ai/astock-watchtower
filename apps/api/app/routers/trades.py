import os
import tempfile
from collections import Counter
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Trade
from app.schemas import TradeCreate, TradeOut, TradeUpdate
from app.services.excel_import import TradeImportError, parse_trade_excel_with_report
from app.services.symbols import normalize_symbol, resolve_symbol_query

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=List[TradeOut])
async def list_trades(symbol: str = "", db: Session = Depends(get_db)) -> List[Trade]:
    stmt = select(Trade).order_by(Trade.trade_date.desc())
    if symbol:
        normalized = await resolve_symbol_query(symbol)
        stmt = stmt.where(Trade.symbol == normalized.symbol)
    return list(db.scalars(stmt))


@router.post("", response_model=TradeOut)
async def create_trade(payload: TradeCreate, db: Session = Depends(get_db)) -> Trade:
    normalized = await resolve_symbol_query(payload.symbol)
    item = Trade(
        symbol=normalized.symbol,
        trade_date=payload.trade_date,
        side=payload.side,
        price=payload.price,
        quantity=payload.quantity,
        fee=payload.fee,
        note=payload.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{trade_id}", response_model=TradeOut)
def update_trade(trade_id: int, payload: TradeUpdate, db: Session = Depends(get_db)) -> Trade:
    item = db.get(Trade, trade_id)
    if not item:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(Trade, trade_id)
    if not item:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/upload-excel")
async def upload_trade_excel(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        try:
            import_result = parse_trade_excel_with_report(tmp_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        items = []
        errors = list(import_result.errors)
        symbol_counter: Counter[str] = Counter()
        side_counter: Counter[str] = Counter()
        dates = []
        for row_number, trade in zip(import_result.trade_row_numbers, import_result.trades):
            try:
                normalized = normalize_symbol(trade.symbol)
            except ValueError as exc:
                errors.append(
                    TradeImportError(
                        row_number=row_number,
                        reason=str(exc),
                        raw={"symbol": trade.symbol, "trade_date": trade.trade_date.isoformat(), "side": trade.side},
                    )
                )
                continue
            item = Trade(
                symbol=normalized.symbol,
                trade_date=trade.trade_date,
                side=trade.side,
                price=trade.price,
                quantity=trade.quantity,
                fee=trade.fee,
                note=trade.note,
            )
            db.add(item)
            items.append(item)
            symbol_counter[normalized.symbol] += 1
            side_counter[trade.side] += 1
            dates.append(trade.trade_date)
        db.commit()
        return {
            "ok": True,
            "total_rows": import_result.total_rows,
            "imported": len(items),
            "failed": len(errors),
            "skipped_blank_rows": import_result.skipped_blank_rows,
            "columns": import_result.columns,
            "symbol_counts": dict(symbol_counter),
            "side_counts": dict(side_counter),
            "date_range": {
                "min": min(dates).isoformat() if dates else "",
                "max": max(dates).isoformat() if dates else "",
            },
            "errors": [
                {"row_number": error.row_number, "reason": error.reason, "raw": error.raw}
                for error in errors[:20]
            ],
            "error_preview_truncated": len(errors) > 20,
        }
    finally:
        os.unlink(tmp_path)
