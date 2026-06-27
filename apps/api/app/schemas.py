from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SubscriptionBase(BaseModel):
    symbol: str = Field(..., examples=["600519.SH"])
    name: str = ""
    feishu_webhook: str = ""
    feishu_secret: str = ""
    is_active: bool = True


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    feishu_webhook: Optional[str] = None
    feishu_secret: Optional[str] = None
    is_active: Optional[bool] = None


class SubscriptionOut(SubscriptionBase):
    id: int
    exchange: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TradeBase(BaseModel):
    symbol: str = Field(..., examples=["600519.SH"])
    trade_date: datetime
    side: str = Field(..., pattern="^(buy|sell)$")
    price: float
    quantity: int
    fee: float = 0.0
    note: str = ""


class TradeCreate(TradeBase):
    pass


class TradeUpdate(BaseModel):
    trade_date: Optional[datetime] = None
    side: Optional[str] = Field(default=None, pattern="^(buy|sell)$")
    price: Optional[float] = None
    quantity: Optional[int] = None
    fee: Optional[float] = None
    note: Optional[str] = None


class TradeOut(TradeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PositionOut(BaseModel):
    symbol: str
    shares: int
    average_cost: float
    cost_basis: float
    realized_pnl: float
    total_buy_amount: float
    total_sell_amount: float
    total_fees: float
    latest_price: Optional[float] = None
    latest_price_time: Optional[str] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    total_pnl: Optional[float] = None
    source: str = ""
    warnings: List[str] = Field(default_factory=list)


class SchedulerRunRequest(BaseModel):
    send: bool = False
    force_notify: bool = True


class SchedulerSubscriptionResult(BaseModel):
    subscription_id: int
    symbol: str
    name: str = ""
    status: str
    should_notify: bool
    trigger_summary: str = ""
    message_preview: str = ""
    report_sections: List[Dict[str, Any]] = Field(default_factory=list)
    action_advice: Dict[str, Any] = Field(default_factory=dict)
    position: Optional[PositionOut] = None
    error: str = ""


class SchedulerRunResponse(BaseModel):
    trading_day: bool
    calendar_source: str
    calendar_warning: str = ""
    started_at: str
    finished_at: str
    send: bool
    force_notify: bool
    results: List[SchedulerSubscriptionResult] = Field(default_factory=list)


class SchedulerStatus(BaseModel):
    enabled: bool
    timezone: str
    cron: str
    job_id: str
    next_run_time: Optional[str] = None
    running: bool


class PushLogOut(BaseModel):
    id: int
    subscription_id: Optional[int] = None
    symbol: str = ""
    status: str
    trigger_summary: str = ""
    message: str = ""
    message_brief: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementOut(BaseModel):
    id: int
    symbol: str
    exchange: str
    company_name: str
    title: str
    announcement_type: str
    published_at: datetime
    source: str
    source_url: str
    external_id: str
    raw_category: str = ""
    importance: str = "watch"
    event_summary: str = ""
    why_matters: str = ""
    next_evidence: str = ""
    affected_layers: str = ""
    pdf_extract_status: str = "not_attempted"
    pdf_extract_error: str = ""
    pdf_extracted_at: Optional[datetime] = None
    pdf_page_count: int = 0
    pdf_text_chars: int = 0
    pdf_text_excerpt: str = ""
    pdf_table_count: int = 0
    pdf_table_excerpt: str = ""
    structured_summary: str = ""
    first_seen_at: datetime

    model_config = {"from_attributes": True}


class ExtractedFactOut(BaseModel):
    id: int
    announcement_id: int
    symbol: str
    fact_type: str
    field_name: str
    field_value: str
    unit: str = ""
    numeric_value: Optional[float] = None
    source_text: str = ""
    confidence: str = "medium"
    extractor: str = "rule"
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementRefreshRequest(BaseModel):
    symbol: str = Field(..., examples=["600519.SH"])
    days: int = Field(default=30, ge=1, le=365)


class AnnouncementQualityRequest(BaseModel):
    symbol: str = Field(..., examples=["000001.SZ"])
    days: int = Field(default=180, ge=1, le=365)
    sync: bool = True


class AnnouncementRefreshResponse(BaseModel):
    symbol: str
    fetched: int
    inserted: int
    updated: int
    announcements: List[AnnouncementOut] = Field(default_factory=list)
    source: str = ""
    warning: str = ""


class AnalyzeRequest(BaseModel):
    query: str = Field(..., examples=["贵州茅台", "600519", "600519.SH"])
    include_intraday: bool = True


class AnalyzeResponse(BaseModel):
    symbol: str
    name: str
    exchange: str
    industry: str
    data_mode: str
    decision: str
    market_weather: Dict[str, Any]
    snapshot: Dict[str, Any]
    universal_indicators: Dict[str, Any]
    sector_indicators: Dict[str, Any]
    events: List[Dict[str, Any]]
    stale_sources: List[Dict[str, Any]]
    missing_inputs: List[Dict[str, Any]]
    research_posture: Dict[str, Any]
    report_sections: List[Dict[str, Any]] = Field(default_factory=list)
    action_advice: Dict[str, Any] = Field(default_factory=dict)
    position: Optional[PositionOut] = None
    sources: List[Dict[str, str]]
