from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_lightweight_columns()


def _ensure_lightweight_columns() -> None:
    """Tiny MVP migration helper until Alembic is introduced."""
    inspector = inspect(engine)
    if "announcements" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("announcements")}
    required = {
        "importance": "VARCHAR(16) DEFAULT 'watch'",
        "event_summary": "TEXT DEFAULT ''",
        "why_matters": "TEXT DEFAULT ''",
        "next_evidence": "TEXT DEFAULT ''",
        "affected_layers": "TEXT DEFAULT ''",
        "pdf_extract_status": "VARCHAR(32) DEFAULT 'not_attempted'",
        "pdf_extract_error": "TEXT DEFAULT ''",
        "pdf_extracted_at": "DATETIME",
        "pdf_page_count": "INTEGER DEFAULT 0",
        "pdf_text_chars": "INTEGER DEFAULT 0",
        "pdf_text_excerpt": "TEXT DEFAULT ''",
        "pdf_table_count": "INTEGER DEFAULT 0",
        "pdf_table_excerpt": "TEXT DEFAULT ''",
        "structured_summary": "TEXT DEFAULT ''",
    }
    with engine.begin() as connection:
        for name, ddl in required.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE announcements ADD COLUMN {name} {ddl}"))
