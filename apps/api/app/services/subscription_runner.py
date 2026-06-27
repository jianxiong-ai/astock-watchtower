from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import PushLog, Subscription, Trade
from app.schemas import SchedulerRunResponse, SchedulerSubscriptionResult
from app.services.analysis import analyze_ashare
from app.services.announcements import sync_official_announcements
from app.services.action_advice import build_position_action_advice
from app.services.notifier import send_feishu_card, send_feishu_text
from app.services.positions import calculate_positions
from app.services.push_renderer import build_feishu_report_card, build_trigger_summary, render_subscription_message
from app.services.trading_calendar import check_a_share_trading_day


async def _run_one_subscription(
    db: Session,
    subscription: Subscription,
    *,
    send: bool,
    force_notify: bool,
    calendar_source: str,
    calendar_warning: str,
) -> SchedulerSubscriptionResult:
    try:
        announcement_result = await sync_official_announcements(
            db,
            subscription.symbol,
            days=get_settings().announcement_lookback_days,
        )
        analysis = await analyze_ashare(subscription.symbol, include_intraday=False, db=db, sync_announcements=True)
        all_trades = list(db.scalars(select(Trade).order_by(Trade.trade_date.asc(), Trade.id.asc())))
        price_overrides = {
            subscription.symbol: {
                "price": analysis.snapshot.get("price"),
                "timestamp": analysis.snapshot.get("timestamp"),
                "source": analysis.snapshot.get("source"),
            }
        }
        all_positions = await calculate_positions(all_trades, price_overrides=price_overrides)
        positions_by_symbol = {item.symbol: item for item in all_positions}
        position = positions_by_symbol.get(subscription.symbol)
        portfolio_market_value = sum(float(item.market_value or 0) for item in all_positions) or None
        should_notify, trigger_summary = build_trigger_summary(
            analysis,
            position,
            force_notify=force_notify,
            new_announcements=announcement_result.new_announcements,
            announcement_warning=announcement_result.warning,
        )
        action_advice = build_position_action_advice(
            analysis,
            position,
            portfolio_market_value=portfolio_market_value,
        )
        message = render_subscription_message(
            analysis=analysis,
            position=position,
            trigger_summary=trigger_summary or "无触发",
            calendar_source=calendar_source,
            calendar_warning=calendar_warning,
            new_announcements=announcement_result.new_announcements,
            announcement_warning=announcement_result.warning,
            portfolio_market_value=portfolio_market_value,
        )
        card = build_feishu_report_card(
            analysis=analysis,
            position=position,
            trigger_summary=trigger_summary or "无触发",
            calendar_source=calendar_source,
            calendar_warning=calendar_warning,
            new_announcements=announcement_result.new_announcements,
            announcement_warning=announcement_result.warning,
            portfolio_market_value=portfolio_market_value,
        )

        status = "no_trigger"
        if should_notify and send:
            if not subscription.feishu_webhook:
                status = "skipped_missing_webhook"
            else:
                settings = get_settings()
                secret = subscription.feishu_secret or settings.feishu_default_secret or None
                if settings.feishu_message_mode.lower() == "text":
                    await send_feishu_text(subscription.feishu_webhook, message, secret)
                else:
                    try:
                        await send_feishu_card(subscription.feishu_webhook, card, secret)
                    except Exception:
                        await send_feishu_text(subscription.feishu_webhook, message, secret)
                status = "sent"
        elif should_notify:
            status = "dry_run"

        db.add(
            PushLog(
                subscription_id=subscription.id,
                symbol=subscription.symbol,
                status=status,
                trigger_summary=trigger_summary,
                message=message,
            )
        )
        db.commit()

        return SchedulerSubscriptionResult(
            subscription_id=subscription.id,
            symbol=subscription.symbol,
            name=subscription.name,
            status=status,
            should_notify=should_notify,
            trigger_summary=trigger_summary,
            message_preview=message,
            report_sections=analysis.report_sections,
            action_advice=action_advice,
            position=position,
        )
    except Exception as exc:
        error = str(exc)
        db.add(
            PushLog(
                subscription_id=subscription.id,
                symbol=subscription.symbol,
                status="failed",
                error=error,
            )
        )
        db.commit()
        return SchedulerSubscriptionResult(
            subscription_id=subscription.id,
            symbol=subscription.symbol,
            name=subscription.name,
            status="failed",
            should_notify=False,
            error=error,
        )


async def run_subscription_scan(*, send: bool = True, force_notify: bool = False) -> SchedulerRunResponse:
    settings = get_settings()
    timezone = ZoneInfo(settings.scheduler_timezone)
    started_at = datetime.now(timezone)
    trading_day = await check_a_share_trading_day(started_at)
    results: list[SchedulerSubscriptionResult] = []

    if not trading_day.is_trading_day:
        finished_at = datetime.now(timezone)
        return SchedulerRunResponse(
            trading_day=False,
            calendar_source=trading_day.source,
            calendar_warning=trading_day.warning,
            started_at=started_at.isoformat(timespec="seconds"),
            finished_at=finished_at.isoformat(timespec="seconds"),
            send=send,
            force_notify=force_notify,
            results=[],
        )

    db = SessionLocal()
    try:
        subscriptions = list(
            db.scalars(select(Subscription).where(Subscription.is_active.is_(True)).order_by(Subscription.created_at.asc()))
        )
        for subscription in subscriptions:
            result = await _run_one_subscription(
                db,
                subscription,
                send=send,
                force_notify=force_notify,
                calendar_source=trading_day.source,
                calendar_warning=trading_day.warning,
            )
            results.append(result)
    finally:
        db.close()

    finished_at = datetime.now(timezone)
    return SchedulerRunResponse(
        trading_day=True,
        calendar_source=trading_day.source,
        calendar_warning=trading_day.warning,
        started_at=started_at.isoformat(timespec="seconds"),
        finished_at=finished_at.isoformat(timespec="seconds"),
        send=send,
        force_notify=force_notify,
        results=results,
    )
