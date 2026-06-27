from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import analysis, announcements, positions, scheduler, subscriptions, system, trades
from app.services.scheduler import start_scheduler, stop_scheduler


settings = get_settings()

app = FastAPI(
    title="astock-watchtower API",
    description="Self-hosted A-share subscription and analysis tool.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(subscriptions.router)
app.include_router(trades.router)
app.include_router(positions.router)
app.include_router(analysis.router)
app.include_router(announcements.router)
app.include_router(scheduler.router)
app.include_router(system.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "astock-watchtower-api"}
