from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Trade
from app.schemas import PositionOut
from app.services.positions import calculate_positions
from app.services.symbols import resolve_symbol_query

router = APIRouter(prefix="/api/positions", tags=["positions"])


@router.get("", response_model=List[PositionOut])
async def list_positions(symbol: str = "", db: Session = Depends(get_db)) -> List[PositionOut]:
    stmt = select(Trade).order_by(Trade.trade_date.asc(), Trade.id.asc())
    normalized_symbol = None
    if symbol:
        normalized = await resolve_symbol_query(symbol)
        normalized_symbol = normalized.symbol
        stmt = stmt.where(Trade.symbol == normalized.symbol)
    trades = list(db.scalars(stmt))
    return await calculate_positions(trades, symbol=normalized_symbol)
