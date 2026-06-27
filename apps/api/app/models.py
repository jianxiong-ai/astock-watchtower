from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    exchange: Mapped[str] = mapped_column(String(8), default="")
    feishu_webhook: Mapped[str] = mapped_column(Text, default="")
    feishu_secret: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    trade_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    side: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[int] = mapped_column(Integer)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PushLog(Base):
    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    subscription_id: Mapped[int] = mapped_column(Integer, index=True, nullable=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    trigger_summary: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    exchange: Mapped[str] = mapped_column(String(8), index=True)
    company_name: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(Text)
    announcement_type: Mapped[str] = mapped_column(String(64), index=True, default="其他")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(String(256), index=True)
    raw_category: Mapped[str] = mapped_column(String(128), default="")
    importance: Mapped[str] = mapped_column(String(16), index=True, default="watch")
    event_summary: Mapped[str] = mapped_column(Text, default="")
    why_matters: Mapped[str] = mapped_column(Text, default="")
    next_evidence: Mapped[str] = mapped_column(Text, default="")
    affected_layers: Mapped[str] = mapped_column(Text, default="")
    pdf_extract_status: Mapped[str] = mapped_column(String(32), index=True, default="not_attempted")
    pdf_extract_error: Mapped[str] = mapped_column(Text, default="")
    pdf_extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    pdf_page_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_text_chars: Mapped[int] = mapped_column(Integer, default=0)
    pdf_text_excerpt: Mapped[str] = mapped_column(Text, default="")
    pdf_table_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_table_excerpt: Mapped[str] = mapped_column(Text, default="")
    structured_summary: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExtractedFact(Base):
    __tablename__ = "extracted_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    announcement_id: Mapped[int] = mapped_column(Integer, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    fact_type: Mapped[str] = mapped_column(String(64), index=True)
    field_name: Mapped[str] = mapped_column(String(128), index=True)
    field_value: Mapped[str] = mapped_column(Text, default="")
    unit: Mapped[str] = mapped_column(String(32), default="")
    numeric_value: Mapped[float] = mapped_column(Float, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    extractor: Mapped[str] = mapped_column(String(64), default="rule")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
