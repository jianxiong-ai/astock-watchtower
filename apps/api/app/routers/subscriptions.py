from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import PushLog, Subscription, Trade
from app.schemas import SubscriptionCreate, SubscriptionOut, SubscriptionUpdate
from app.services.analysis import analyze_ashare
from app.services.announcements import sync_official_announcements
from app.services.notifier import send_feishu_card, send_feishu_text
from app.services.positions import calculate_positions
from app.services.push_renderer import build_feishu_report_card, render_subscription_message
from app.services.symbols import resolve_symbol_query

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("", response_model=List[SubscriptionOut])
def list_subscriptions(db: Session = Depends(get_db)) -> List[Subscription]:
    return list(db.scalars(select(Subscription).order_by(Subscription.created_at.desc())))


@router.post("", response_model=SubscriptionOut)
async def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)) -> Subscription:
    active_count = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.is_active.is_(True))) or 0
    if payload.is_active and active_count >= 3:
        raise HTTPException(status_code=400, detail="最多只能订阅 3 只股票")

    normalized = await resolve_symbol_query(payload.symbol)
    existing = db.scalar(select(Subscription).where(Subscription.symbol == normalized.symbol))
    if existing:
        raise HTTPException(status_code=400, detail=f"{normalized.symbol} 已存在订阅")

    item = Subscription(
        symbol=normalized.symbol,
        exchange=normalized.exchange,
        name=payload.name,
        feishu_webhook=payload.feishu_webhook,
        feishu_secret=payload.feishu_secret,
        is_active=payload.is_active,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{subscription_id}", response_model=SubscriptionOut)
def update_subscription(subscription_id: int, payload: SubscriptionUpdate, db: Session = Depends(get_db)) -> Subscription:
    item = db.get(Subscription, subscription_id)
    if not item:
        raise HTTPException(status_code=404, detail="订阅不存在")

    if payload.is_active is True and not item.is_active:
        active_count = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.is_active.is_(True))) or 0
        if active_count >= 3:
            raise HTTPException(status_code=400, detail="最多只能订阅 3 只股票")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{subscription_id}")
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(Subscription, subscription_id)
    if not item:
        raise HTTPException(status_code=404, detail="订阅不存在")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/{subscription_id}/test-webhook")
@router.post("/{subscription_id}/send-analysis-push")
async def send_subscription_analysis_push(subscription_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(Subscription, subscription_id)
    if not item:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if not item.feishu_webhook:
        raise HTTPException(status_code=400, detail="尚未配置飞书 webhook")

    settings = get_settings()
    announcement_result = await sync_official_announcements(
        db,
        item.symbol,
        days=settings.analysis_announcement_lookback_days,
    )
    analysis = await analyze_ashare(item.symbol, include_intraday=False, db=db, sync_announcements=True)
    all_trades = list(db.scalars(select(Trade).order_by(Trade.trade_date.asc(), Trade.id.asc())))
    price_overrides = {
        item.symbol: {
            "price": analysis.snapshot.get("price"),
            "timestamp": analysis.snapshot.get("timestamp"),
            "source": analysis.snapshot.get("source"),
        }
    }
    all_positions = await calculate_positions(all_trades, price_overrides=price_overrides)
    positions_by_symbol = {position.symbol: position for position in all_positions}
    position = positions_by_symbol.get(item.symbol)
    portfolio_market_value = sum(float(position.market_value or 0) for position in all_positions) or None
    trigger_summary = "手动发送分析推送；不改变正式定时任务和触发规则"
    calendar_source = "手动发送分析推送：未按正式交易日门槛过滤"
    calendar_warning = "本次用于核对飞书展示内容；正式定时推送仍按交易日和触发规则执行。"
    message = render_subscription_message(
        analysis=analysis,
        position=position,
        trigger_summary=trigger_summary,
        calendar_source=calendar_source,
        calendar_warning=calendar_warning,
        new_announcements=announcement_result.new_announcements,
        announcement_warning=announcement_result.warning,
        portfolio_market_value=portfolio_market_value,
    )
    card = build_feishu_report_card(
        analysis=analysis,
        position=position,
        trigger_summary=trigger_summary,
        calendar_source=calendar_source,
        calendar_warning=calendar_warning,
        new_announcements=announcement_result.new_announcements,
        announcement_warning=announcement_result.warning,
        portfolio_market_value=portfolio_market_value,
    )

    secret = item.feishu_secret or settings.feishu_default_secret or None
    if settings.feishu_message_mode.lower() == "text":
        result = await send_feishu_text(item.feishu_webhook, message, secret)
    else:
        try:
            result = await send_feishu_card(item.feishu_webhook, card, secret)
        except Exception:
            result = await send_feishu_text(item.feishu_webhook, message, secret)

    db.add(
        PushLog(
            subscription_id=item.id,
            symbol=item.symbol,
            status="manual_analysis_sent",
            trigger_summary=trigger_summary,
            message=message,
        )
    )
    db.commit()
    return {
        "ok": True,
        "status": "manual_analysis_sent",
        "symbol": item.symbol,
        "message_preview": message,
        "report_sections": analysis.report_sections,
        "feishu_response": result,
    }
