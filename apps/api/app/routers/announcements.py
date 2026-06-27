from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Announcement, ExtractedFact
from app.schemas import AnnouncementOut, AnnouncementQualityRequest, AnnouncementRefreshRequest, AnnouncementRefreshResponse, ExtractedFactOut
from app.services.analysis import FIELD_LABELS
from app.services.announcements import list_stored_announcements, sync_official_announcements
from app.services.fact_extraction import list_extracted_facts
from app.services.indicators import infer_industry
from app.services.sector_mapping import build_sector_indicator_mapping
from app.services.symbols import normalize_symbol

router = APIRouter(prefix="/api/announcements", tags=["announcements"])


@router.get("", response_model=List[AnnouncementOut])
def list_announcements(symbol: str = "", limit: int = 50, db: Session = Depends(get_db)) -> List[object]:
    return list_stored_announcements(db, symbol=symbol or None, limit=max(1, min(limit, 200)))


@router.get("/facts", response_model=List[ExtractedFactOut])
def list_facts(symbol: str = "", announcement_id: int = 0, limit: int = 200, db: Session = Depends(get_db)) -> List[object]:
    return list_extracted_facts(
        db,
        symbol=symbol,
        announcement_id=announcement_id or None,
        limit=max(1, min(limit, 500)),
    )


@router.post("/refresh", response_model=AnnouncementRefreshResponse)
async def refresh_announcements(payload: AnnouncementRefreshRequest, db: Session = Depends(get_db)) -> AnnouncementRefreshResponse:
    try:
        result = await sync_official_announcements(db, payload.symbol, days=payload.days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnnouncementRefreshResponse(
        symbol=result.symbol,
        fetched=result.fetched,
        inserted=result.inserted,
        updated=result.updated,
        announcements=result.announcements,
        source=result.source,
        warning=result.warning,
    )


def _fact_label(field_name: str) -> str:
    label = FIELD_LABELS.get(field_name)
    if label is None and field_name.endswith("_change_pct"):
        base_name = field_name[: -len("_change_pct")]
        label = f"{FIELD_LABELS.get(base_name, base_name)}变化率"
    return label or field_name


def _format_fact_value(fact: ExtractedFact) -> str:
    if fact.numeric_value is None:
        return fact.field_value
    if fact.unit == "CNY":
        return f"¥{fact.numeric_value:,.0f}"
    if fact.unit == "%":
        return f"{fact.numeric_value:.2f}%"
    if fact.unit == "CNY/share":
        return f"¥{fact.numeric_value:.2f}/股"
    return fact.field_value


def _quality_fact_dict(fact: ExtractedFact, announcement: Announcement) -> Dict[str, Any]:
    return {
        "id": fact.id,
        "announcement_id": fact.announcement_id,
        "announcement_title": announcement.title,
        "announcement_type": announcement.announcement_type,
        "published_at": announcement.published_at.isoformat(timespec="seconds"),
        "source_url": announcement.source_url,
        "fact_type": fact.fact_type,
        "field_name": fact.field_name,
        "label": _fact_label(fact.field_name),
        "value": _format_fact_value(fact),
        "raw_value": fact.field_value,
        "unit": fact.unit,
        "numeric_value": fact.numeric_value,
        "confidence": fact.confidence,
        "extractor": fact.extractor,
        "source_text": fact.source_text,
    }


@router.post("/quality")
async def announcement_quality(payload: AnnouncementQualityRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        normalized = normalize_symbol(payload.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sync_warning = ""
    source = ""
    if payload.sync:
        try:
            result = await sync_official_announcements(db, normalized.symbol, days=payload.days)
            sync_warning = result.warning
            source = result.source
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            sync_warning = f"同步官方公告失败：{exc}"

    announcements = list(
        db.scalars(
            select(Announcement)
            .where(Announcement.symbol == normalized.symbol)
            .order_by(Announcement.published_at.desc(), Announcement.id.desc())
            .limit(100)
        )
    )
    facts = list(
        db.scalars(
            select(ExtractedFact)
            .where(ExtractedFact.symbol == normalized.symbol)
            .order_by(ExtractedFact.created_at.desc(), ExtractedFact.id.asc())
            .limit(1000)
        )
    )
    by_announcement = {item.id: item for item in announcements}
    facts_by_announcement: Dict[int, List[ExtractedFact]] = {}
    for fact in facts:
        if fact.announcement_id in by_announcement:
            facts_by_announcement.setdefault(fact.announcement_id, []).append(fact)

    fact_dicts = [
        _quality_fact_dict(fact, by_announcement[fact.announcement_id])
        for fact in facts
        if fact.announcement_id in by_announcement
    ]
    company_name = next((item.company_name for item in announcements if item.company_name), "")
    industry = infer_industry(company_name, normalized.symbol)
    fact_types = sorted({str(item["fact_type"]) for item in fact_dicts})
    fact_summary = {
        "status": "Available" if fact_dicts else "Missing",
        "recent_facts": fact_dicts,
        "coverage": {fact_type: "available" for fact_type in fact_types},
    }
    sector_mapping = build_sector_indicator_mapping(industry, fact_summary)

    announcement_rows = []
    warnings = []
    for item in announcements:
        item_facts = facts_by_announcement.get(item.id, [])
        fact_type_counts: Dict[str, int] = {}
        for fact in item_facts:
            fact_type_counts[fact.fact_type] = fact_type_counts.get(fact.fact_type, 0) + 1
        if item.pdf_extract_status != "success":
            warnings.append(f"{item.title}：PDF 抽取状态 {item.pdf_extract_status or 'not_attempted'}")
        if item.announcement_type in {"定期报告", "权益分派/分红", "业绩预告/快报"} and not item_facts:
            warnings.append(f"{item.title}：未抽出结构化事实")
        if item.announcement_type == "定期报告" and not item.pdf_table_count:
            warnings.append(f"{item.title}：未识别到 PDF 表格")
        announcement_rows.append(
            {
                "id": item.id,
                "title": item.title,
                "announcement_type": item.announcement_type,
                "importance": item.importance,
                "published_at": item.published_at.isoformat(timespec="seconds"),
                "source": item.source,
                "source_url": item.source_url,
                "pdf_extract_status": item.pdf_extract_status,
                "pdf_extract_error": item.pdf_extract_error,
                "pdf_page_count": item.pdf_page_count,
                "pdf_text_chars": item.pdf_text_chars,
                "pdf_table_count": item.pdf_table_count,
                "fact_count": len(item_facts),
                "fact_type_counts": fact_type_counts,
                "facts": [_quality_fact_dict(fact, item) for fact in item_facts],
                "table_excerpt": item.pdf_table_excerpt[:3000],
            }
        )

    fact_type_counts: Dict[str, int] = {}
    for item in fact_dicts:
        fact_type = str(item["fact_type"])
        fact_type_counts[fact_type] = fact_type_counts.get(fact_type, 0) + 1

    return {
        "symbol": normalized.symbol,
        "exchange": normalized.exchange,
        "company_name": company_name or normalized.symbol,
        "industry": industry,
        "synced": payload.sync,
        "sync_source": source,
        "sync_warning": sync_warning,
        "announcement_count": len(announcements),
        "fact_count": len(fact_dicts),
        "fact_type_counts": fact_type_counts,
        "sector_mapping_coverage": sector_mapping["coverage"],
        "sector_missing_inputs": sector_mapping["missing_inputs"],
        "sector_mapped_metrics": sector_mapping["rows"],
        "warnings": warnings[:50],
        "announcements": announcement_rows,
    }
