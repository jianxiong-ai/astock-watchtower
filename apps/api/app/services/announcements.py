import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Announcement
from app.services.fact_extraction import save_extracted_facts
from app.services.pdf_extraction import extract_pdf_from_url
from app.services.symbols import NormalizedSymbol, normalize_symbol


SSE_ANNOUNCEMENT_API = "https://query.sse.com.cn/security/stock/queryCompanyBulletin.do"
SSE_ANNOUNCEMENT_PAGE = "https://www.sse.com.cn/disclosure/listedinfo/announcement/"
SZSE_ANNOUNCEMENT_API = "https://www.szse.cn/api/disc/announcement/annList"
SZSE_ANNOUNCEMENT_PAGE = "https://www.szse.cn/disclosure/listed/notice/index.html"
SZSE_STATIC_BASE = "https://disc.static.szse.cn"


@dataclass
class AnnouncementItem:
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
    pdf_page_count: int = 0
    pdf_text_chars: int = 0
    pdf_table_count: int = 0
    pdf_table_excerpt: str = ""
    structured_summary: str = ""


@dataclass
class AnnouncementSyncResult:
    symbol: str
    fetched: int
    inserted: int
    updated: int
    announcements: List[Announcement]
    new_announcements: List[Announcement]
    source: str
    warning: str = ""


@dataclass
class AnnouncementAssessment:
    importance: str
    event_summary: str
    why_matters: str
    next_evidence: str
    affected_layers: str


def classify_announcement(title: str, raw_category: str = "") -> str:
    text = f"{title} {raw_category}"
    rules = [
        ("定期报告", ["年度报告", "半年度报告", "季度报告", "一季报", "三季报", "年报", "半年报"]),
        ("业绩预告/快报", ["业绩预告", "业绩快报", "盈利预告"]),
        ("权益分派/分红", ["权益分派", "利润分配", "分红", "派息", "派发现金红利"]),
        ("股东大会", ["股东大会", "法律意见", "决议公告"]),
        ("管理层/治理", ["董事", "监事", "高管", "总经理", "董事会秘书", "任职资格", "辞职", "聘任"]),
        ("监管/处罚", ["监管", "处罚", "处分", "问询函", "警示函", "立案", "行政处罚"]),
        ("重大交易/投资", ["重大资产", "收购", "出售", "投资", "重组", "关联交易", "对外投资"]),
        ("融资/资本动作", ["可转债", "公司债", "定增", "非公开发行", "回购", "增发", "配股"]),
        ("担保/诉讼/风险", ["担保", "诉讼", "仲裁", "冻结", "质押", "减持", "风险提示"]),
    ]
    for label, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return label
    return raw_category or "其他"


def _should_reextract_pdf(existing: Announcement, announcement_type: str) -> bool:
    if existing.pdf_extract_status != "success":
        return True
    if announcement_type != "定期报告":
        return False

    settings = get_settings()
    if existing.pdf_page_count > settings.pdf_extract_max_pages and existing.pdf_text_chars < settings.periodic_report_pdf_text_max_chars * 0.45:
        return True
    if existing.pdf_page_count > settings.pdf_table_max_pages and existing.pdf_table_count < 20:
        return True

    text = f"{existing.pdf_text_excerpt or ''}\n{existing.pdf_table_excerpt or ''}"
    if existing.symbol == "600362.SH":
        deep_keywords = ["自产铜精矿含铜", "阴极铜", "TC", "全球显性库存", "经营活动产生的现金流量净额"]
        return not any(keyword in text for keyword in deep_keywords)
    if existing.symbol == "601336.SH":
        deep_keywords = ["新业务价值", "内含价值", "核心偿付能力", "综合偿付能力", "投资收益率"]
        return not any(keyword in text for keyword in deep_keywords)
    return False


def assess_announcement(symbol: str, title: str, announcement_type: str, raw_category: str = "") -> AnnouncementAssessment:
    text = f"{title} {announcement_type} {raw_category}"
    importance = "watch"
    affected_layers = ["事件层"]

    if announcement_type in {"定期报告", "业绩预告/快报", "监管/处罚", "重大交易/投资"}:
        importance = "high"
    elif announcement_type in {"权益分派/分红", "管理层/治理", "融资/资本动作", "担保/诉讼/风险"}:
        importance = "medium"

    if any(keyword in text for keyword in ["立案", "行政处罚", "纪律处分", "重大资产", "重组", "业绩预告", "业绩快报"]):
        importance = "high"
    if any(keyword in text for keyword in ["法律意见", "股东大会决议", "股东会决议"]) and importance == "watch":
        affected_layers.append("治理/程序验证")

    if symbol == "600362.SH":
        affected_layers.append("江西铜业事件层")
        if any(keyword in text for keyword in ["年度报告", "季度报告", "半年度报告", "业绩"]):
            affected_layers.extend(["现金流/资本开支", "成本/毛利", "产量/资源自给"])
        if any(keyword in text for keyword in ["铜箔", "矿山", "矿业", "冶炼", "可转债", "债券", "回购"]):
            affected_layers.extend(["项目/融资", "估值与稀释"])
    elif symbol == "601336.SH":
        affected_layers.append("新华保险事件层")
        if any(keyword in text for keyword in ["年度报告", "季度报告", "半年度报告", "业绩"]):
            affected_layers.extend(["NBV/EV/CSM", "投资收益", "偿付能力"])
        if any(keyword in text for keyword in ["董事", "高管", "任职资格", "偿付", "资本", "债券", "分红"]):
            affected_layers.extend(["治理/资本", "股东回报"])
    else:
        affected_layers.append("通用事件层")

    summary = (
        f"基于官方公告标题和分类的规则摘要：公司披露《{title}》，当前归类为“{announcement_type}”。"
        "尚未解析 PDF 正文，具体数字与条款需以后续正文解析或人工核验为准。"
    )

    why_map = {
        "定期报告": "可能更新收入、利润、现金流、资产负债、行业核心 KPI 和管理层展望，是基本面判断的核心证据。",
        "业绩预告/快报": "通常会提前改变盈利预期和估值基准，若与市场预期偏离较大，可能形成高优先级触发。",
        "权益分派/分红": "影响股东回报、除权除息、现金分配和资本留存，需要结合盈利质量与资本需求判断。",
        "股东大会": "多为治理或程序性事项；若涉及分红、融资、重大交易或章程变化，需要进一步核对议案内容。",
        "管理层/治理": "关键人员或治理结构变化可能影响战略执行、风控和资本配置，需要观察后续经营表述。",
        "监管/处罚": "可能影响公司声誉、合规成本、业务约束和估值折价，需核对处罚对象、金额和整改要求。",
        "重大交易/投资": "可能改变资产结构、盈利来源、资本开支、杠杆或稀释风险，是事件层高优先级证据。",
        "融资/资本动作": "可能影响资本结构、利息成本、股本稀释、回购或分红能力，需要核对条款和用途。",
        "担保/诉讼/风险": "可能增加或暴露或有负债、信用风险、质押/减持压力，需要追踪金额、对象和进展。",
    }
    why_matters = why_map.get(announcement_type, "该公告可能提供新的公司事件或信息披露线索，需要判断是否改变监控假设。")

    next_map = {
        "定期报告": "解析报告正文与财务表：收入/利润/现金流/负债/行业核心 KPI，并与上一期和原监控阈值比较。",
        "业绩预告/快报": "核对预告区间、同比/环比、原因说明和正式报告发布日期。",
        "权益分派/分红": "核对每股派息、股权登记日、除权除息日、派息率和资金来源。",
        "股东大会": "核对议案全文、表决结果、是否包含分红/融资/重大交易/章程修改等实质事项。",
        "管理层/治理": "核对人员职责、任期、背景、监管核准条件和后续经营策略表述。",
        "监管/处罚": "核对监管文号、处罚/整改金额、责任主体、整改期限和公司后续公告。",
        "重大交易/投资": "核对交易金额、估值、资金来源、审批条件、交割进度和业绩承诺。",
        "融资/资本动作": "核对发行规模、利率/转股价/回购价、期限、资金用途和稀释或财务成本。",
        "担保/诉讼/风险": "核对涉案/担保金额、对手方、期限、资产冻结或预计负债计提。",
    }
    next_evidence = next_map.get(announcement_type, "打开官方 PDF 核验正文，判断是否应进入核心监控骨架。")

    return AnnouncementAssessment(
        importance=importance,
        event_summary=summary,
        why_matters=why_matters,
        next_evidence=next_evidence,
        affected_layers="、".join(dict.fromkeys(affected_layers)),
    )


def _stock_code(symbol: NormalizedSymbol) -> str:
    return symbol.symbol[:6]


def _parse_datetime(value: object) -> datetime:
    settings = get_settings()
    timezone = ZoneInfo(settings.scheduler_timezone)
    if isinstance(value, datetime):
        return value.astimezone(timezone) if value.tzinfo else value.replace(tzinfo=timezone)
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone)
        except ValueError:
            continue
    return datetime.now(timezone)


async def fetch_sse_announcements(symbol: NormalizedSymbol, begin: datetime, end: datetime) -> List[AnnouncementItem]:
    params = {
        "isPagination": "true",
        "productId": _stock_code(symbol),
        "keyWord": "",
        "securityType": "0101,120100,020100,020200,120200",
        "reportType2": "",
        "reportType": "ALL",
        "beginDate": begin.date().isoformat(),
        "endDate": end.date().isoformat(),
        "pageHelp.pageSize": "50",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": SSE_ANNOUNCEMENT_PAGE}
    async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
        response = await client.get(SSE_ANNOUNCEMENT_API, params=params)
        response.raise_for_status()
    data = response.json()
    rows = data.get("pageHelp", {}).get("data", []) or []
    result: List[AnnouncementItem] = []
    for row in rows:
        title = str(row.get("TITLE") or "").strip()
        relative_url = str(row.get("URL") or "").strip()
        if not title or not relative_url:
            continue
        raw_category = str(row.get("BULLETIN_TYPE") or row.get("BULLETIN_HEADING") or "").strip()
        announcement_type = classify_announcement(title, raw_category)
        assessment = assess_announcement(symbol.symbol, title, announcement_type, raw_category)
        source_url = relative_url if relative_url.startswith("http") else f"https://www.sse.com.cn{relative_url}"
        result.append(
            AnnouncementItem(
                symbol=symbol.symbol,
                exchange=symbol.exchange,
                company_name=str(row.get("SECURITY_NAME") or ""),
                title=title,
                announcement_type=announcement_type,
                published_at=_parse_datetime(row.get("ADDDATE") or row.get("SSEDATE")),
                source="SSE",
                source_url=source_url,
                external_id=relative_url,
                raw_category=raw_category,
                importance=assessment.importance,
                event_summary=assessment.event_summary,
                why_matters=assessment.why_matters,
                next_evidence=assessment.next_evidence,
                affected_layers=assessment.affected_layers,
            )
        )
    return result


async def fetch_szse_announcements(symbol: NormalizedSymbol, begin: datetime, end: datetime) -> List[AnnouncementItem]:
    url = f"{SZSE_ANNOUNCEMENT_API}?random={random.random()}"
    payload = {
        "seDate": [begin.date().isoformat(), end.date().isoformat()],
        "stock": [_stock_code(symbol)],
        "channelCode": ["listedNotice_disc"],
        "pageSize": 50,
        "pageNum": 1,
    }
    headers = {
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": "https://www.szse.cn",
        "Referer": SZSE_ANNOUNCEMENT_PAGE,
        "User-Agent": "Mozilla/5.0",
        "X-Request-Type": "ajax",
        "X-Requested-With": "XMLHttpRequest",
    }
    async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    rows = response.json().get("data", []) or []
    result: List[AnnouncementItem] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        attach_path = str(row.get("attachPath") or "").strip()
        if not title or not attach_path:
            continue
        announcement_type = classify_announcement(title)
        assessment = assess_announcement(symbol.symbol, title, announcement_type)
        source_url = attach_path if attach_path.startswith("http") else f"{SZSE_STATIC_BASE}{attach_path}"
        sec_names = row.get("secName") or []
        result.append(
            AnnouncementItem(
                symbol=symbol.symbol,
                exchange=symbol.exchange,
                company_name=str(sec_names[0] if sec_names else ""),
                title=title,
                announcement_type=announcement_type,
                published_at=_parse_datetime(row.get("publishTime")),
                source="SZSE",
                source_url=source_url,
                external_id=str(row.get("annId") or row.get("id") or attach_path),
                raw_category=str(row.get("bigCategoryId") or ""),
                importance=assessment.importance,
                event_summary=assessment.event_summary,
                why_matters=assessment.why_matters,
                next_evidence=assessment.next_evidence,
                affected_layers=assessment.affected_layers,
            )
        )
    return result


async def fetch_official_announcements(symbol: str, days: int = 30) -> List[AnnouncementItem]:
    normalized = normalize_symbol(symbol)
    timezone = ZoneInfo(get_settings().scheduler_timezone)
    end = datetime.now(timezone)
    begin = end - timedelta(days=days)
    if normalized.exchange == "SH":
        return await fetch_sse_announcements(normalized, begin, end)
    if normalized.exchange == "SZ":
        return await fetch_szse_announcements(normalized, begin, end)
    raise ValueError(f"暂不支持该交易所公告抓取：{normalized.exchange}")


async def sync_official_announcements(db: Session, symbol: str, days: int = 30) -> AnnouncementSyncResult:
    normalized = normalize_symbol(symbol)
    warning = ""
    try:
        items = await fetch_official_announcements(normalized.symbol, days=days)
    except Exception as exc:
        items = []
        warning = f"官方公告读取失败：{exc}"

    inserted = 0
    updated = 0
    touched: List[Announcement] = []
    new_announcements: List[Announcement] = []
    for item in items:
        existing = db.scalar(
            select(Announcement).where(
                Announcement.source == item.source,
                Announcement.external_id == item.external_id,
            )
        )
        if existing:
            existing.title = item.title
            existing.announcement_type = item.announcement_type
            existing.company_name = item.company_name
            existing.published_at = item.published_at
            existing.source_url = item.source_url
            existing.raw_category = item.raw_category
            existing.importance = item.importance
            existing.event_summary = item.event_summary
            existing.why_matters = item.why_matters
            existing.next_evidence = item.next_evidence
            existing.affected_layers = item.affected_layers
            if _should_reextract_pdf(existing, item.announcement_type):
                extraction = await extract_pdf_from_url(item.source_url, item.title, item.announcement_type)
                existing.pdf_extract_status = extraction.status
                existing.pdf_extract_error = extraction.error
                existing.pdf_extracted_at = extraction.extracted_at
                existing.pdf_page_count = extraction.page_count
                existing.pdf_text_chars = extraction.text_chars
                existing.pdf_text_excerpt = extraction.text_excerpt
                existing.pdf_table_count = extraction.table_count
                existing.pdf_table_excerpt = extraction.table_excerpt
                existing.structured_summary = extraction.structured_summary
            updated += 1
            touched.append(existing)
        else:
            extraction = await extract_pdf_from_url(item.source_url, item.title, item.announcement_type)
            announcement = Announcement(
                symbol=item.symbol,
                exchange=item.exchange,
                company_name=item.company_name,
                title=item.title,
                announcement_type=item.announcement_type,
                published_at=item.published_at,
                source=item.source,
                source_url=item.source_url,
                external_id=item.external_id,
                raw_category=item.raw_category,
                importance=item.importance,
                event_summary=item.event_summary,
                why_matters=item.why_matters,
                next_evidence=item.next_evidence,
                affected_layers=item.affected_layers,
                pdf_extract_status=extraction.status,
                pdf_extract_error=extraction.error,
                pdf_extracted_at=extraction.extracted_at,
                pdf_page_count=extraction.page_count,
                pdf_text_chars=extraction.text_chars,
                pdf_text_excerpt=extraction.text_excerpt,
                pdf_table_count=extraction.table_count,
                pdf_table_excerpt=extraction.table_excerpt,
                structured_summary=extraction.structured_summary,
            )
            db.add(announcement)
            inserted += 1
            touched.append(announcement)
            new_announcements.append(announcement)
    db.commit()
    for item in touched:
        db.refresh(item)
    for item in touched:
        save_extracted_facts(db, item)

    source = SSE_ANNOUNCEMENT_PAGE if normalized.exchange == "SH" else SZSE_ANNOUNCEMENT_PAGE
    return AnnouncementSyncResult(
        symbol=normalized.symbol,
        fetched=len(items),
        inserted=inserted,
        updated=updated,
        announcements=sorted(touched, key=lambda item: item.published_at, reverse=True),
        new_announcements=sorted(new_announcements, key=lambda item: item.published_at, reverse=True),
        source=source,
        warning=warning,
    )


def list_stored_announcements(db: Session, symbol: Optional[str] = None, limit: int = 50) -> List[Announcement]:
    query = select(Announcement).order_by(Announcement.published_at.desc(), Announcement.id.desc()).limit(limit)
    if symbol:
        query = (
            select(Announcement)
            .where(Announcement.symbol == normalize_symbol(symbol).symbol)
            .order_by(Announcement.published_at.desc(), Announcement.id.desc())
            .limit(limit)
        )
    return list(db.scalars(query))
