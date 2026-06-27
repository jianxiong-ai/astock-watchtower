from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PushLog
from app.schemas import PushLogOut, SchedulerRunRequest, SchedulerRunResponse, SchedulerStatus
from app.services.scheduler import get_scheduler_status
from app.services.subscription_runner import run_subscription_scan

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status", response_model=SchedulerStatus)
def status() -> SchedulerStatus:
    return get_scheduler_status()


@router.post("/run-now", response_model=SchedulerRunResponse)
async def run_now(payload: SchedulerRunRequest) -> SchedulerRunResponse:
    return await run_subscription_scan(send=payload.send, force_notify=payload.force_notify)


@router.get("/logs", response_model=List[PushLogOut])
def logs(limit: int = 30, symbol: str = "", db: Session = Depends(get_db)) -> List[PushLog]:
    safe_limit = min(max(limit, 1), 100)
    stmt = select(PushLog)
    if symbol:
        stmt = stmt.where(PushLog.symbol == symbol)
    stmt = stmt.order_by(PushLog.created_at.desc(), PushLog.id.desc()).limit(safe_limit)
    return list(db.scalars(stmt))
