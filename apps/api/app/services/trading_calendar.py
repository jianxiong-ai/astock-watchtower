import re
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from typing import Iterable, List, Optional, Set
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from app.config import get_settings


SSE_CLOSED_URL = "https://www.sse.com.cn/disclosure/dealinstruc/closed/"
SZSE_NOTICE_INDEX_URL = "https://www.szse.cn/disclosure/notice/index.html"


@dataclass
class ExchangeCalendarSource:
    exchange: str
    source_name: str
    source_url: str
    fetched_at: str
    closed_dates: Set[date] = field(default_factory=set)
    notices: List[str] = field(default_factory=list)
    warning: str = ""


_CALENDAR_CACHE: dict[int, tuple[datetime, List[ExchangeCalendarSource]]] = {}


@dataclass
class TradingDayResult:
    is_trading_day: bool
    date: str
    timezone: str
    source: str
    warning: str = ""


def _text_from_html(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text


def _dates_between(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _extract_year(text: str, fallback_year: int) -> int:
    match = re.search(r"(20\d{2})\s*年(?:部分节假日|休市安排|年度休市安排)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"(20\d{2})\s*年", text)
    return int(match.group(1)) if match else fallback_year


def _parse_chinese_closed_dates(text: str, fallback_year: int) -> Set[date]:
    compact = re.sub(r"\s+", "", text)
    page_year = _extract_year(compact, fallback_year)
    closed_dates: Set[date] = set()
    date_range_pattern = re.compile(
        r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日(?:（[^）]*）)?"
        r"(?:至(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日(?:（[^）]*）)?)?"
        r"休市"
    )

    for match in date_range_pattern.finditer(compact):
        start_year_raw, start_month, start_day, end_year_raw, end_month, end_day = match.groups()
        start_year = int(start_year_raw) if start_year_raw else page_year
        end_year = int(end_year_raw) if end_year_raw else start_year
        start = date(start_year, int(start_month), int(start_day))
        end = date(end_year, int(end_month or start_month), int(end_day or start_day))
        if end < start:
            end = date(start.year, start.month, start.day)
        closed_dates.update(_dates_between(start, end))

    return closed_dates


async def fetch_sse_calendar(target_year: int) -> ExchangeCalendarSource:
    fetched_at = datetime.now(ZoneInfo(get_settings().scheduler_timezone)).isoformat(timespec="seconds")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with httpx.AsyncClient(timeout=12, headers=headers, follow_redirects=True) as client:
            response = await client.get(SSE_CLOSED_URL)
            response.raise_for_status()
        text = _text_from_html(response.text)
        closed_dates = {item for item in _parse_chinese_closed_dates(text, target_year) if item.year in {target_year - 1, target_year, target_year + 1}}
        notices = re.findall(r"关于[^。\n]{0,40}休市安排[^。\n]*", text)
        return ExchangeCalendarSource(
            exchange="SSE",
            source_name="上交所官方休市安排",
            source_url=SSE_CLOSED_URL,
            fetched_at=fetched_at,
            closed_dates=closed_dates,
            notices=notices[:8],
        )
    except Exception as exc:
        return ExchangeCalendarSource(
            exchange="SSE",
            source_name="上交所官方休市安排",
            source_url=SSE_CLOSED_URL,
            fetched_at=fetched_at,
            warning=f"SSE 官方日历读取失败：{exc}",
        )


def _szse_index_url(page: int) -> str:
    if page == 0:
        return SZSE_NOTICE_INDEX_URL
    return f"https://www.szse.cn/disclosure/notice/index_{page}.html"


async def fetch_szse_calendar(target_year: int, max_pages: int = 60) -> ExchangeCalendarSource:
    settings = get_settings()
    fetched_at = datetime.now(ZoneInfo(settings.scheduler_timezone)).isoformat(timespec="seconds")
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/disclosure/notice/index.html"}
    closed_dates: Set[date] = set()
    notices: List[str] = []
    warnings: List[str] = []

    async with httpx.AsyncClient(timeout=10, headers=headers, follow_redirects=True) as client:
        for page in range(max_pages):
            if page:
                await asyncio.sleep(0.05)
            try:
                index_url = _szse_index_url(page)
                response = await client.get(index_url)
                if response.status_code == 404:
                    break
                response.raise_for_status()
            except Exception as exc:
                warnings.append(f"SZSE 公告列表第 {page} 页读取失败：{exc}")
                break

            article_matches = re.finditer(
                r"var curHref = '([^']+)'.*?var curTitle ='([^']+)'.*?<span class=\"time\">\s*([^<]+)",
                response.text,
                re.S,
            )
            candidate_urls: List[tuple[str, str, str]] = []
            for match in article_matches:
                href, title, published_at = match.groups()
                title = title.strip()
                published_at = published_at.strip()
                if "休市" not in title:
                    continue
                if str(target_year) not in title and str(target_year - 1) not in published_at:
                    continue
                candidate_urls.append((urljoin(index_url, href), title, published_at))

            for url, title, published_at in candidate_urls:
                try:
                    article = await client.get(url)
                    article.raise_for_status()
                    text = _text_from_html(article.text)
                    dates = _parse_chinese_closed_dates(text, target_year)
                    if dates:
                        closed_dates.update(dates)
                        notices.append(f"{published_at} {title} {url}")
                except Exception as exc:
                    warnings.append(f"SZSE 公告读取失败：{title} {exc}")

            if notices and any(f"关于{target_year}年部分节假日休市安排" in item for item in notices):
                break

    if closed_dates and not any(f"关于{target_year}年部分节假日休市安排" in item for item in notices):
        warnings.append("SZSE 未抓取到年度休市通知，仅抓取到单项休市公告；完整年度判断以其他可得官方来源和本地配置交叉校验。")

    return ExchangeCalendarSource(
        exchange="SZSE",
        source_name="深交所官方本所公告/休市安排",
        source_url=SZSE_NOTICE_INDEX_URL,
        fetched_at=fetched_at,
        closed_dates=closed_dates,
        notices=notices[:8],
        warning="；".join(warnings[:3]),
    )


def _configured_holiday_dates() -> Set[date]:
    dates: Set[date] = set()
    for item in get_settings().holiday_dates:
        try:
            dates.add(date.fromisoformat(item))
        except ValueError:
            continue
    return dates


async def check_a_share_trading_day(now: Optional[datetime] = None) -> TradingDayResult:
    settings = get_settings()
    timezone = ZoneInfo(settings.scheduler_timezone)
    local_now = now.astimezone(timezone) if now else datetime.now(timezone)
    local_date = local_now.date()

    sources = await fetch_official_exchange_calendars(local_date.year)
    official_closed_dates: Set[date] = set()
    source_parts: List[str] = []
    warnings: List[str] = []
    for source in sources:
        if source.closed_dates:
            official_closed_dates.update(source.closed_dates)
            source_parts.append(f"{source.source_name}（{source.source_url}，抓取 {source.fetched_at}）")
        if source.warning:
            warnings.append(source.warning)

    configured_closed_dates = _configured_holiday_dates()
    if configured_closed_dates:
        official_closed_dates.update(configured_closed_dates)
        source_parts.append("本地 A_SHARE_HOLIDAYS 配置")

    if not source_parts:
        source_parts.append("本地工作日兜底判断")
        warnings.append("官方交易日历全部读取失败；仅使用周末和 A_SHARE_HOLIDAYS 兜底，可能漏掉临时休市。")

    is_weekend = local_date.weekday() >= 5
    is_closed_by_calendar = local_date in official_closed_dates
    is_trading_day = not is_weekend and not is_closed_by_calendar

    if not warnings and len([source for source in sources if source.closed_dates]) < 2:
        warnings.append("仅部分官方交易所日历成功读取；已使用可得官方来源判断。")

    return TradingDayResult(
        is_trading_day=is_trading_day,
        date=local_date.isoformat(),
        timezone=settings.scheduler_timezone,
        source="；".join(source_parts),
        warning="；".join(warnings),
    )


async def fetch_official_exchange_calendars(target_year: int) -> List[ExchangeCalendarSource]:
    settings = get_settings()
    now = datetime.now(ZoneInfo(settings.scheduler_timezone))
    cached = _CALENDAR_CACHE.get(target_year)
    if cached:
        cached_at, cached_sources = cached
        if (now - cached_at).total_seconds() < 6 * 60 * 60:
            return cached_sources

    sse = await fetch_sse_calendar(target_year)
    szse = await fetch_szse_calendar(target_year)
    sources = [sse, szse]
    _CALENDAR_CACHE[target_year] = (now, sources)
    return sources
