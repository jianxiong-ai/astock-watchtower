from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.schemas import SchedulerStatus
from app.services.subscription_runner import run_subscription_scan


JOB_ID = "daily_a_share_subscription_scan"
_scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    settings = get_settings()
    if not settings.scheduler_enabled:
        return

    timezone = ZoneInfo(settings.scheduler_timezone)
    if not _scheduler.get_job(JOB_ID):
        _scheduler.add_job(
            run_subscription_scan,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=settings.scheduler_hour,
                minute=settings.scheduler_minute,
                timezone=timezone,
            ),
            id=JOB_ID,
            kwargs={"send": True, "force_notify": False},
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )

    if not _scheduler.running:
        _scheduler.start()


def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def get_scheduler_status() -> SchedulerStatus:
    settings = get_settings()
    job = _scheduler.get_job(JOB_ID) if _scheduler.running else None
    next_run_time = job.next_run_time.isoformat() if job and job.next_run_time else None
    cron = f"Mon-Fri {settings.scheduler_hour:02d}:{settings.scheduler_minute:02d}"
    return SchedulerStatus(
        enabled=settings.scheduler_enabled,
        timezone=settings.scheduler_timezone,
        cron=cron,
        job_id=JOB_ID,
        next_run_time=next_run_time,
        running=_scheduler.running,
    )
