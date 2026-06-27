import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from pypdf import PdfReader

from app.config import get_settings


ACW_SC_V2_ARG2 = "3000176000856006061501533003690027800375"
ACW_SC_V2_UNSBOX_INDEXES = [
    0xF,
    0x23,
    0x1D,
    0x18,
    0x21,
    0x10,
    0x1,
    0x26,
    0xA,
    0x9,
    0x13,
    0x1F,
    0x28,
    0x1B,
    0x16,
    0x17,
    0x19,
    0xD,
    0x6,
    0xB,
    0x27,
    0x12,
    0x14,
    0x8,
    0xE,
    0x15,
    0x20,
    0x1A,
    0x2,
    0x1E,
    0x7,
    0x4,
    0x11,
    0x5,
    0x3,
    0x1C,
    0x22,
    0x25,
    0xC,
    0x24,
]


@dataclass
class PdfExtractionResult:
    status: str
    text_excerpt: str = ""
    text_chars: int = 0
    page_count: int = 0
    table_count: int = 0
    table_excerpt: str = ""
    structured_summary: str = ""
    extracted_at: Optional[datetime] = None
    error: str = ""


def _acw_unsbox(arg: str) -> str:
    result = [""] * len(ACW_SC_V2_UNSBOX_INDEXES)
    for index, char in enumerate(arg):
        for target_index, source_position in enumerate(ACW_SC_V2_UNSBOX_INDEXES):
            if source_position == index + 1:
                result[target_index] = char
                break
    return "".join(result)


def _hex_xor(left: str, right: str) -> str:
    limit = min(len(left), len(right))
    return "".join(
        f"{int(left[index:index + 2], 16) ^ int(right[index:index + 2], 16):02x}"
        for index in range(0, limit, 2)
    )


def _solve_acw_sc_v2_cookie(html: str) -> Optional[str]:
    match = re.search(r"var\s+arg1\s*=\s*'([0-9a-fA-F]+)'", html)
    if not match:
        return None
    return _hex_xor(_acw_unsbox(match.group(1)), ACW_SC_V2_ARG2)


def _cookie_domains(url: str) -> List[str]:
    hostname = urlparse(url).hostname or ""
    domains = [hostname] if hostname else []
    if hostname.endswith("sse.com.cn"):
        domains.extend([".sse.com.cn", ".static.sse.com.cn"])
    return list(dict.fromkeys(domains))


async def _download_pdf_response(client: httpx.AsyncClient, url: str) -> httpx.Response:
    response = await client.get(url)
    response.raise_for_status()
    if response.content.startswith(b"%PDF"):
        return response

    content_type = response.headers.get("content-type", "").lower()
    if "text/html" in content_type and b"acw_sc__v2" in response.content:
        cookie = _solve_acw_sc_v2_cookie(response.text)
        if cookie:
            for domain in _cookie_domains(str(response.url)):
                client.cookies.set("acw_sc__v2", cookie, domain=domain, path="/")
            retry = await client.get(url)
            retry.raise_for_status()
            return retry
    return response


def _clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_candidates(pattern: str, text: str, limit: int = 8) -> List[str]:
    seen = []
    for match in re.finditer(pattern, text):
        value = match.group(0).strip()
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def _extract_sentences(text: str, keywords: List[str], limit: int = 5) -> List[str]:
    normalized = re.sub(r"\s+", "", text)
    pieces = re.split(r"(?<=[。；;])", normalized)
    result = []
    for piece in pieces:
        if len(piece) < 8:
            continue
        if any(keyword in piece for keyword in keywords):
            result.append(piece[:180])
        if len(result) >= limit:
            break
    return result


def _clean_table_cell(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _format_table(table: List[List[object]], page_number: int, table_number: int, max_rows: int = 12) -> str:
    rows = []
    for row in table[:max_rows]:
        cleaned = [_clean_table_cell(cell) for cell in row]
        if any(cleaned):
            rows.append(" | ".join(cleaned))
    if not rows:
        return ""
    return f"[page {page_number} table {table_number}]\n" + "\n".join(rows)


def _extract_pdf_tables(content: bytes, max_pages: int, max_tables: int, max_chars: int) -> tuple[int, str]:
    try:
        import pdfplumber
    except Exception:
        return 0, ""

    table_blocks = []
    table_count = 0
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_index, page in enumerate(pdf.pages[: max(1, max_pages)], start=1):
                tables = page.extract_tables() or []
                for table_index, table in enumerate(tables, start=1):
                    if not table:
                        continue
                    formatted = _format_table(table, page_index, table_index)
                    if not formatted:
                        continue
                    table_count += 1
                    if len(table_blocks) < max_tables:
                        table_blocks.append(formatted)
                    if table_count >= max_tables and sum(len(block) for block in table_blocks) >= max_chars:
                        break
                if table_count >= max_tables and sum(len(block) for block in table_blocks) >= max_chars:
                    break
    except Exception:
        return 0, ""

    excerpt = "\n\n".join(table_blocks)
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip()
    return table_count, excerpt


def build_structured_summary(
    title: str,
    announcement_type: str,
    text: str,
    page_count: int,
    text_chars: int,
    table_count: int = 0,
) -> str:
    dates = _extract_candidates(r"\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}", text, limit=6)
    money = _extract_candidates(r"(?:人民币)?[0-9,，.]+(?:万|亿)?元|[0-9,，.]+(?:万|亿)?股", text, limit=8)
    percentages = _extract_candidates(r"[+-]?\d+(?:\.\d+)?%", text, limit=8)

    keywords_by_type = {
        "定期报告": ["营业收入", "归属于", "净利润", "现金流", "资产负债", "每股收益", "分红"],
        "业绩预告/快报": ["预计", "归属于", "净利润", "同比", "增长", "下降", "原因"],
        "权益分派/分红": ["每股", "派发", "现金红利", "股权登记日", "除权除息日", "派息"],
        "股东大会": ["审议", "通过", "反对", "弃权", "表决", "议案"],
        "管理层/治理": ["任职资格", "辞职", "聘任", "董事", "高级管理人员", "任期"],
        "监管/处罚": ["监管", "处罚", "整改", "警示", "处分", "违规"],
        "重大交易/投资": ["交易", "收购", "出售", "投资", "对价", "交割", "评估"],
        "融资/资本动作": ["发行", "募集资金", "利率", "转股", "回购", "债券", "期限"],
        "担保/诉讼/风险": ["担保", "诉讼", "仲裁", "冻结", "质押", "风险"],
    }
    key_sentences = _extract_sentences(text, keywords_by_type.get(announcement_type, ["公告", "公司", "事项"]))

    lines = [
        f"PDF 正文抽取成功：共 {page_count} 页，抽取约 {text_chars} 个字符；以下为规则结构化摘要，仍需结合原文核验。",
        f"公告主题：{title}",
        f"公告类型：{announcement_type}",
    ]
    if table_count:
        lines.append(f"识别表格：约 {table_count} 个；表格片段已单独保存，适合后续财报字段解析。")
    if dates:
        lines.append(f"识别日期：{'、'.join(dates)}")
    if money:
        lines.append(f"识别金额/股数：{'、'.join(money)}")
    if percentages:
        lines.append(f"识别比例：{'、'.join(percentages)}")
    if key_sentences:
        lines.append("正文要点：" + "；".join(key_sentences))
    else:
        lines.append("正文要点：未能从抽取文本中稳定识别关键句，建议打开官方 PDF 人工核验。")
    return "\n".join(lines)


def _is_periodic_report(title: str, announcement_type: str) -> bool:
    text = f"{announcement_type} {title}"
    return announcement_type == "定期报告" or any(
        keyword in text
        for keyword in ["年度报告", "半年度报告", "季度报告", "第一季度报告", "第三季度报告"]
    )


async def extract_pdf_from_url(url: str, title: str, announcement_type: str) -> PdfExtractionResult:
    settings = get_settings()
    timezone = ZoneInfo(settings.scheduler_timezone)
    extracted_at = datetime.now(timezone)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.sse.com.cn/",
    }

    try:
        async with httpx.AsyncClient(timeout=25, headers=headers, follow_redirects=True) as client:
            response = await _download_pdf_response(client, url)
        content_type = response.headers.get("content-type", "").lower()
        if not response.content.startswith(b"%PDF"):
            return PdfExtractionResult(
                status="not_pdf_response",
                extracted_at=extracted_at,
                error=f"URL 未返回标准 PDF 内容：content-type={content_type or 'unknown'}，body_prefix={response.content[:20]!r}",
            )

        reader = PdfReader(BytesIO(response.content), strict=False)
        page_count = len(reader.pages)
        is_periodic_report = _is_periodic_report(title, announcement_type)
        text_max_pages = (
            settings.periodic_report_pdf_extract_max_pages
            if is_periodic_report
            else settings.pdf_extract_max_pages
        )
        text_max_chars = (
            settings.periodic_report_pdf_text_max_chars
            if is_periodic_report
            else settings.pdf_text_max_chars
        )
        table_max_pages = (
            settings.periodic_report_pdf_table_max_pages
            if is_periodic_report
            else settings.pdf_table_max_pages
        )
        table_max_tables = (
            settings.periodic_report_pdf_table_max_tables
            if is_periodic_report
            else settings.pdf_table_max_tables
        )
        table_max_chars = (
            settings.periodic_report_pdf_table_max_chars
            if is_periodic_report
            else settings.pdf_table_max_chars
        )
        page_texts = []
        for page in reader.pages[: max(1, text_max_pages)]:
            page_texts.append(page.extract_text() or "")
        text = _clean_text("\n".join(page_texts))
        table_count, table_excerpt = _extract_pdf_tables(
            response.content,
            table_max_pages,
            table_max_tables,
            table_max_chars,
        )
        if not text:
            return PdfExtractionResult(
                status="empty_text",
                page_count=page_count,
                table_count=table_count,
                table_excerpt=table_excerpt,
                extracted_at=extracted_at,
                error="PDF 下载成功，但文本抽取为空；可能是扫描版或加密/图片型 PDF。",
            )

        text_excerpt = text[:text_max_chars]
        structured_summary = build_structured_summary(
            title,
            announcement_type,
            text_excerpt,
            page_count,
            len(text),
            table_count=table_count,
        )
        return PdfExtractionResult(
            status="success",
            text_excerpt=text_excerpt,
            text_chars=len(text),
            page_count=page_count,
            table_count=table_count,
            table_excerpt=table_excerpt,
            structured_summary=structured_summary,
            extracted_at=extracted_at,
        )
    except Exception as exc:
        return PdfExtractionResult(status="failed", extracted_at=extracted_at, error=str(exc))
