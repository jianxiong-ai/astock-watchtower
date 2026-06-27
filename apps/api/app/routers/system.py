from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.config import get_settings
from app.db import SessionLocal
from app.models import Announcement, ExtractedFact, PushLog, Subscription, Trade
from app.services.scheduler import get_scheduler_status
from app.services.trading_calendar import check_a_share_trading_day


router = APIRouter(prefix="/api/system", tags=["system"])


def _safe_count(db, model) -> int:
    try:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)
    except Exception:
        return 0


@router.get("/health")
async def system_health() -> dict:
    settings = get_settings()
    timezone = ZoneInfo(settings.scheduler_timezone)
    checked_at = datetime.now(timezone).isoformat(timespec="seconds")
    database = {"ok": False, "tables": {}, "error": ""}
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        database = {
            "ok": True,
            "url_kind": settings.database_url.split(":", 1)[0],
            "tables": {
                "subscriptions": _safe_count(db, Subscription),
                "trades": _safe_count(db, Trade),
                "announcements": _safe_count(db, Announcement),
                "extracted_facts": _safe_count(db, ExtractedFact),
                "push_logs": _safe_count(db, PushLog),
            },
            "error": "",
        }
    except Exception as exc:
        database["error"] = str(exc)
    finally:
        db.close()

    trading_day = await check_a_share_trading_day(datetime.now(timezone))
    scheduler = get_scheduler_status().model_dump()
    checks = {
        "database": "ok" if database["ok"] else "failed",
        "scheduler": "ok" if scheduler.get("running") or not settings.scheduler_enabled else "warning",
        "trading_calendar": "warning" if trading_day.warning else "ok",
        "feishu_mode": settings.feishu_message_mode,
        "pdf_extraction": "configured",
    }
    overall = "ok"
    if database["ok"] is False:
        overall = "failed"
    elif any(value == "warning" for value in checks.values()):
        overall = "warning"

    return {
        "ok": overall != "failed",
        "status": overall,
        "service": "astock-watchtower-api",
        "checked_at": checked_at,
        "timezone": settings.scheduler_timezone,
        "checks": checks,
        "database": database,
        "scheduler": scheduler,
        "trading_day": trading_day.__dict__,
        "configuration": {
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_time": f"{settings.scheduler_hour:02d}:{settings.scheduler_minute:02d}",
            "announcement_lookback_days": settings.announcement_lookback_days,
            "analysis_announcement_lookback_days": settings.analysis_announcement_lookback_days,
            "feishu_message_mode": settings.feishu_message_mode,
            "cors_origins": settings.cors_origins,
        },
        "data_sources": [
            {"name": "SSE calendar/announcements", "type": "official"},
            {"name": "SZSE calendar/announcements", "type": "official"},
            {"name": "Sina quote", "type": "secondary"},
            {"name": "Eastmoney/Tencent valuation and kline", "type": "secondary"},
        ],
    }
