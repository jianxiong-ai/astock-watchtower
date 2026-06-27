from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Subscription, Trade
from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.action_advice import build_position_action_advice
from app.services.analysis import analyze_ashare
from app.services.positions import calculate_positions

router = APIRouter(prefix="/api/analyze", tags=["analysis"])


@router.post("", response_model=AnalyzeResponse)
async def analyze(payload: AnalyzeRequest, db: Session = Depends(get_db)) -> AnalyzeResponse:
    try:
        analysis = await analyze_ashare(payload.query, include_intraday=payload.include_intraday, db=db, sync_announcements=True)
        subscription = db.scalar(select(Subscription).where(Subscription.symbol == analysis.symbol))
        if subscription:
            all_trades = list(db.scalars(select(Trade).order_by(Trade.trade_date.asc(), Trade.id.asc())))
            price_overrides = {
                analysis.symbol: {
                    "price": analysis.snapshot.get("price"),
                    "timestamp": analysis.snapshot.get("timestamp"),
                    "source": analysis.snapshot.get("source"),
                }
            }
            all_positions = await calculate_positions(all_trades, price_overrides=price_overrides)
            positions_by_symbol = {position.symbol: position for position in all_positions}
            position = positions_by_symbol.get(analysis.symbol)
            portfolio_market_value = sum(float(position.market_value or 0) for position in all_positions) or None
            analysis.position = position
            analysis.action_advice = build_position_action_advice(
                analysis,
                position,
                portfolio_market_value=portfolio_market_value,
            )
        return analysis
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"分析数据源暂不可用：{exc}") from exc
