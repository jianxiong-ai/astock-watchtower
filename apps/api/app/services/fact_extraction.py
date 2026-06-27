import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Announcement, ExtractedFact


@dataclass
class FactCandidate:
    fact_type: str
    field_name: str
    field_value: str
    unit: str = ""
    numeric_value: Optional[float] = None
    source_text: str = ""
    confidence: str = "medium"
    extractor: str = "rule_dividend_v1"


def _normalize_number(value: str) -> Optional[float]:
    cleaned = value.replace(",", "").replace("，", "").strip()
    if cleaned in {"", "-", "--", "不适用"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    cleaned = cleaned.replace("%", "")
    try:
        number = float(cleaned)
        return -number if negative else number
    except ValueError:
        return None


def _normalize_amount_to_yuan(value: str, unit_text: str) -> Optional[float]:
    number = _normalize_number(value)
    if number is None:
        return None
    if "百万元" in unit_text:
        return number * 1_000_000
    if "亿" in unit_text:
        return number * 100_000_000
    if "万" in unit_text:
        return number * 10_000
    return number


def _chinese_date_to_iso(value: str) -> str:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value)
    if not match:
        return value.strip()
    year, month, day = (int(item) for item in match.groups())
    return date(year, month, day).isoformat()


def _source_window(text: str, start: int, end: int, margin: int = 80) -> str:
    return text[max(0, start - margin) : min(len(text), end + margin)].strip()


def extract_dividend_facts(announcement: Announcement) -> List[FactCandidate]:
    text = announcement.pdf_text_excerpt or announcement.structured_summary or announcement.title
    compact = re.sub(r"\s+", "", text)
    facts: List[FactCandidate] = []

    cash_field_patterns = [
        ("cash_dividend_per_10_shares", r"(?:本次|年末期)[^。；;]*?每10股派发现金(?:股利|红利)?人民币?([0-9,.，]+)元"),
        ("annual_cash_dividend_per_10_shares", r"(?:全年|2025年全年)[^。；;]*?每10股派发现金(?:股利|红利)?人民币?([0-9,.，]+)元"),
        ("interim_cash_dividend_per_10_shares", r"(?:中期|已按)[^。；;]*?每10股派发现金(?:股利|红利)?人民币?([0-9,.，]+)元"),
    ]
    extracted_cash_fields = set()
    for field_name, pattern in cash_field_patterns:
        match = re.search(pattern, compact)
        if match:
            amount = match.group(1)
            facts.append(
                FactCandidate(
                    fact_type="dividend",
                    field_name=field_name,
                    field_value=amount,
                    unit="CNY/10 shares",
                    numeric_value=_normalize_number(amount),
                    source_text=_source_window(compact, match.start(), match.end()),
                    confidence="high",
                )
            )
            extracted_cash_fields.add(field_name)

    if "cash_dividend_per_10_shares" not in extracted_cash_fields:
        fallback_patterns = [
            r"每10股派发现金(?:股利|红利)?人民币?([0-9,.，]+)元",
            r"每10股派(?:发)?(?:现金)?人民币?([0-9,.，]+)元",
            r"10股派(?:发)?(?:现金)?(?:股利|红利)?人民币?([0-9,.，]+)元",
        ]
        for pattern in fallback_patterns:
            match = re.search(pattern, compact)
            if match:
                amount = match.group(1)
                facts.append(
                    FactCandidate(
                        fact_type="dividend",
                        field_name="cash_dividend_per_10_shares",
                        field_value=amount,
                        unit="CNY/10 shares",
                        numeric_value=_normalize_number(amount),
                        source_text=_source_window(compact, match.start(), match.end()),
                        confidence="medium",
                    )
                )
                break

    date_patterns = {
        "record_date": r"股权登记日(?:为)?(?:：|:)?(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})",
        "ex_dividend_date": r"除权除息日(?:为)?(?:：|:)?(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})",
        "payment_date": r"(?:现金红利将于|红利发放日(?:为)?(?:：|:)?)(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})",
    }
    for field_name, pattern in date_patterns.items():
        match = re.search(pattern, compact)
        if match:
            raw_date = match.group(1)
            facts.append(
                FactCandidate(
                    fact_type="dividend",
                    field_name=field_name,
                    field_value=_chinese_date_to_iso(raw_date),
                    unit="date",
                    source_text=_source_window(compact, match.start(), match.end()),
                    confidence="high",
                )
            )

    share_match = re.search(r"(?:总股本|股本)([0-9,，]+)股", compact)
    if share_match:
        shares = share_match.group(1)
        facts.append(
            FactCandidate(
                fact_type="dividend",
                field_name="share_base",
                field_value=shares,
                unit="shares",
                numeric_value=_normalize_number(shares),
                source_text=_source_window(compact, share_match.start(), share_match.end()),
                confidence="medium",
            )
        )

    if "不送红股" in compact:
        facts.append(
            FactCandidate(
                fact_type="dividend",
                field_name="bonus_share_ratio",
                field_value="0",
                unit="shares",
                numeric_value=0,
                source_text="不送红股",
                confidence="high",
            )
        )
    if "不以公积金转增股本" in compact or "不进行资本公积金转增股本" in compact:
        facts.append(
            FactCandidate(
                fact_type="dividend",
                field_name="capitalization_ratio",
                field_value="0",
                unit="shares",
                numeric_value=0,
                source_text="不以公积金转增股本",
                confidence="high",
            )
        )

    return facts


def _append_fact(
    facts: List[FactCandidate],
    field_name: str,
    field_value: str,
    unit: str,
    source_text: str,
    numeric_value: Optional[float] = None,
    confidence: str = "medium",
) -> None:
    facts.append(
        FactCandidate(
            fact_type="earnings_forecast",
            field_name=field_name,
            field_value=field_value,
            unit=unit,
            numeric_value=numeric_value,
            source_text=source_text,
            confidence=confidence,
            extractor="rule_earnings_forecast_v1",
        )
    )


def _append_typed_fact(
    facts: List[FactCandidate],
    fact_type: str,
    field_name: str,
    field_value: str,
    unit: str,
    source_text: str,
    numeric_value: Optional[float] = None,
    confidence: str = "medium",
    extractor: str = "rule",
) -> None:
    facts.append(
        FactCandidate(
            fact_type=fact_type,
            field_name=field_name,
            field_value=field_value,
            unit=unit,
            numeric_value=numeric_value,
            source_text=source_text,
            confidence=confidence,
            extractor=extractor,
        )
    )


def _normalize_period(value: str) -> str:
    value = value.strip()
    if value.endswith("第一季度") or value.endswith("半年度") or value.endswith("前三季度") or value.endswith("年度"):
        return value
    if value.endswith("一季度"):
        return value[: -len("一季度")] + "第一季度"
    if value.endswith("中期") or value.endswith("半年"):
        return re.sub(r"(中期|半年)$", "半年度", value)
    if value.endswith("三季度"):
        return value[: -len("三季度")] + "前三季度"
    if value.endswith("全年"):
        return value[: -len("全年")] + "年度"
    return value


def _first_sentence_with_keywords(text: str, keywords: List[str]) -> str:
    pieces = re.split(r"(?<=[。；;])", text)
    for piece in pieces:
        compact_piece = re.sub(r"\s+", "", piece)
        if len(compact_piece) < 8:
            continue
        if any(keyword in compact_piece for keyword in keywords):
            return compact_piece[:220]
    return ""


def extract_earnings_forecast_facts(announcement: Announcement) -> List[FactCandidate]:
    text = announcement.pdf_text_excerpt or announcement.structured_summary or announcement.title
    compact = re.sub(r"\s+", "", text)
    facts: List[FactCandidate] = []

    period_match = re.search(
        r"(20\d{2}年(?:第一季度|一季度|半年度|中期|半年|前三季度|三季度|年度|全年|年))",
        compact,
    )
    if period_match:
        period = _normalize_period(period_match.group(1))
        _append_fact(
            facts,
            "report_period",
            period,
            "period",
            _source_window(compact, period_match.start(), period_match.end()),
            confidence="high",
        )

    direction_patterns = [
        ("turnaround", r"扭亏为盈"),
        ("loss", r"预计亏损|预亏|亏损"),
        ("increase", r"同比(?:增长|上升|增加)|预增"),
        ("decrease", r"同比(?:下降|减少|下滑)|预减"),
    ]
    for direction, pattern in direction_patterns:
        direction_match = re.search(pattern, compact)
        if direction_match:
            _append_fact(
                facts,
                "net_profit_change_direction",
                direction,
                "category",
                _source_window(compact, direction_match.start(), direction_match.end()),
                confidence="medium",
            )
            break

    profit_range_patterns = [
        r"归属于(?:上市公司)?股东的净利润[^。；;]{0,80}?(?:为|约为|预计为|预计盈利|盈利|预计亏损|亏损)?(?:人民币)?([+-]?[0-9][0-9,，.]*)(万|亿)?元(?:至|到|-|—|~)(?:人民币)?([+-]?[0-9][0-9,，.]*)(万|亿)?元",
        r"净利润[^。；;]{0,60}?(?:为|约为|预计为|预计盈利|盈利|预计亏损|亏损)?(?:人民币)?([+-]?[0-9][0-9,，.]*)(万|亿)?元(?:至|到|-|—|~)(?:人民币)?([+-]?[0-9][0-9,，.]*)(万|亿)?元",
    ]
    profit_range_match = None
    for pattern in profit_range_patterns:
        profit_range_match = re.search(pattern, compact)
        if profit_range_match:
            break
    if profit_range_match:
        min_value = profit_range_match.group(1)
        min_unit = profit_range_match.group(2) or profit_range_match.group(4) or ""
        max_value = profit_range_match.group(3)
        max_unit = profit_range_match.group(4) or min_unit
        source_text = _source_window(compact, profit_range_match.start(), profit_range_match.end())
        min_numeric = _normalize_amount_to_yuan(min_value, min_unit)
        max_numeric = _normalize_amount_to_yuan(max_value, max_unit)
        _append_fact(
            facts,
            "net_profit_min",
            min_value,
            "CNY" if min_numeric is not None else min_unit,
            source_text,
            numeric_value=min_numeric,
            confidence="high",
        )
        _append_fact(
            facts,
            "net_profit_max",
            max_value,
            "CNY" if max_numeric is not None else max_unit,
            source_text,
            numeric_value=max_numeric,
            confidence="high",
        )
    else:
        single_profit_match = re.search(
            r"归属于(?:上市公司)?股东的净利润[^。；;]{0,80}?(?:为|约为|预计为|预计盈利|盈利|预计亏损|亏损)(?:人民币)?([+-]?[0-9][0-9,，.]*)(万|亿)?元",
            compact,
        )
        if single_profit_match:
            value = single_profit_match.group(1)
            unit_text = single_profit_match.group(2) or ""
            numeric = _normalize_amount_to_yuan(value, unit_text)
            _append_fact(
                facts,
                "net_profit_estimate",
                value,
                "CNY" if numeric is not None else unit_text,
                _source_window(compact, single_profit_match.start(), single_profit_match.end()),
                numeric_value=numeric,
                confidence="medium",
            )

    yoy_match = re.search(
        r"同比(?P<direction>增长|上升|增加|下降|减少|下滑)[^。；;%]{0,30}?(?P<first>[+-]?[0-9]+(?:\.[0-9]+)?)%(?:至|到|-|—|~)(?P<second>[+-]?[0-9]+(?:\.[0-9]+)?)%",
        compact,
    )
    if yoy_match:
        direction_text = yoy_match.group("direction")
        first = yoy_match.group("first")
        second = yoy_match.group("second")
        multiplier = -1 if direction_text in {"下降", "减少", "下滑"} else 1
        first_number = _normalize_number(first)
        second_number = _normalize_number(second)
        first_signed = first_number * multiplier if first_number is not None else None
        second_signed = second_number * multiplier if second_number is not None else None
        if first_signed is not None and second_signed is not None:
            low_value = min(first_signed, second_signed)
            high_value = max(first_signed, second_signed)
        else:
            low_value = first_signed
            high_value = second_signed
        source_text = _source_window(compact, yoy_match.start(), yoy_match.end())
        _append_fact(
            facts,
            "yoy_change_min_pct",
            str(low_value if low_value is not None else first),
            "%",
            source_text,
            numeric_value=low_value,
            confidence="high",
        )
        _append_fact(
            facts,
            "yoy_change_max_pct",
            str(high_value if high_value is not None else second),
            "%",
            source_text,
            numeric_value=high_value,
            confidence="high",
        )

    report_date_match = re.search(
        r"(?:正式报告|定期报告|年报|季报|半年报)[^。；;]{0,30}?(?:披露|预约披露|公布|发布)(?:日期|日)?(?:为|：|:)?(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2})",
        compact,
    )
    if report_date_match:
        raw_date = report_date_match.group(1)
        _append_fact(
            facts,
            "official_report_date",
            _chinese_date_to_iso(raw_date),
            "date",
            _source_window(compact, report_date_match.start(), report_date_match.end()),
            confidence="medium",
        )

    reason = _first_sentence_with_keywords(text, ["主要原因", "主要系", "主要由于", "原因说明", "业绩变动原因"])
    if reason:
        _append_fact(
            facts,
            "forecast_reason",
            reason,
            "text",
            reason,
            confidence="medium",
        )

    return facts


def _amount_multiplier_from_text(text: str) -> float:
    if "人民币百万元" in text or "金额单位：百万元" in text or "单位：百万元" in text:
        return 1_000_000
    if "人民币万元" in text or "金额单位：万元" in text or "单位：万元" in text:
        return 10_000
    if "人民币亿元" in text or "金额单位：亿元" in text or "单位：亿元" in text:
        return 100_000_000
    return 1


def _normalize_report_period(title: str, text: str) -> str:
    title_source = title or ""
    source = f"{title_source}{text[:1000]}"
    year_match = re.search(r"(20\d{2})年", title_source) or re.search(r"(20\d{2})年", source)
    if not year_match:
        return ""
    year = year_match.group(1)
    if any(keyword in title_source for keyword in ["第一季度报告", "一季度报告", "第一季度"]):
        return f"{year}Q1"
    if any(keyword in title_source for keyword in ["半年度报告", "半年报", "半年度"]):
        return f"{year}H1"
    if any(keyword in title_source for keyword in ["第三季度报告", "三季度报告", "前三季度", "第三季度"]):
        return f"{year}Q3"
    if any(keyword in title_source for keyword in ["年度报告", "年报"]):
        return f"{year}A"
    if any(keyword in source for keyword in ["第一季度报告", "一季度报告", "第一季度"]):
        return f"{year}Q1"
    if any(keyword in source for keyword in ["半年度报告", "半年报", "半年度"]):
        return f"{year}H1"
    if any(keyword in source for keyword in ["第三季度报告", "三季度报告", "前三季度", "第三季度"]):
        return f"{year}Q3"
    if any(keyword in source for keyword in ["年度报告", "年报"]):
        return f"{year}A"
    return f"{year}"


def _parse_table_rows(table_text: str) -> List[List[str]]:
    rows = []
    for line in table_text.splitlines():
        line = line.strip()
        if not line or line.startswith("[page "):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def _row_matches(row_name: str, includes: List[str], excludes: Optional[List[str]] = None) -> bool:
    if not all(keyword in row_name for keyword in includes):
        return False
    if excludes and any(keyword in row_name for keyword in excludes):
        return False
    return True


def _field_unit_for_metric(row_name: str, amount_multiplier: float, field_name: str = "") -> str:
    if field_name in {
        "net_interest_margin",
        "npl_ratio",
        "provision_coverage_ratio",
        "core_tier1_capital_adequacy_ratio",
        "tier1_capital_adequacy_ratio",
        "capital_adequacy_ratio",
        "gross_margin",
        "asset_liability_ratio",
        "total_investment_yield",
        "net_investment_yield",
        "comprehensive_investment_yield",
        "core_solvency_adequacy_ratio",
        "comprehensive_solvency_adequacy_ratio",
    }:
        return "%"
    if "%" in row_name or "收益率" in row_name or "比例" in row_name:
        return "%"
    if "每股" in row_name or "元/股" in row_name:
        return "CNY/share"
    if amount_multiplier != 1:
        return "CNY"
    return "reported_unit"


def _cell_numeric_value(value: str) -> Optional[float]:
    first = str(value).split("/")[0]
    return _normalize_number(first)


def _select_metric_value(row: List[str], field_name: str) -> str:
    if len(row) < 2:
        return ""
    value = row[1]
    if field_name in {
        "net_interest_margin",
        "npl_ratio",
        "provision_coverage_ratio",
        "core_tier1_capital_adequacy_ratio",
        "tier1_capital_adequacy_ratio",
        "capital_adequacy_ratio",
        "core_solvency_adequacy_ratio",
        "comprehensive_solvency_adequacy_ratio",
    }:
        for candidate in row[1:]:
            text = str(candidate).strip()
            if not text or text in {"-", "--", "不适用"}:
                continue
            if any(marker in text for marker in ["≥", "≤", ">", "<", "注"]):
                continue
            if _cell_numeric_value(text) is not None:
                return text
    if _cell_numeric_value(value) is None:
        for candidate in row[1:]:
            text = str(candidate).strip()
            if not text or text in {"-", "--", "不适用"}:
                continue
            if _cell_numeric_value(text) is not None:
                return text
    return value


def _numeric_for_metric(value: str, unit: str, amount_multiplier: float) -> Optional[float]:
    number = _cell_numeric_value(value)
    if number is None:
        return None
    if unit == "CNY":
        if re.search(r"\d{1,3}(?:[,，]\d{3}){2,}", str(value)):
            return number
        return number * amount_multiplier
    return number


def _metric_fact_type(field_name: str) -> str:
    if field_name in {
        "original_premium_income",
        "first_year_premium",
        "first_year_regular_premium",
        "ten_year_plus_regular_premium",
        "renewal_premium",
        "surrender_rate",
        "persistency_commentary",
        "agent_productivity_commentary",
        "new_business_value",
        "new_business_value_growth_pct",
        "embedded_value",
        "embedded_value_growth_pct",
        "investment_assets",
        "core_capital",
        "actual_capital",
        "minimum_capital",
    }:
        return "insurance_metrics"
    if field_name in {
        "cathode_copper_output",
        "gold_output",
        "silver_output",
        "sulfuric_acid_output",
        "copper_processing_output",
        "own_concentrate_copper_output",
        "controlled_copper_resource",
        "controlled_gold_resource",
        "tc_spot_range",
        "tc_spot_low",
        "tc_spot_high",
        "global_visible_copper_inventory",
        "global_visible_copper_inventory_change",
        "own_mine_raw_material_cost",
        "own_mine_raw_material_cost_share",
        "domestic_purchase_cost_share",
        "overseas_purchase_cost_share",
        "total_raw_material_cost",
    }:
        return "nonferrous_metrics"
    if field_name in {
        "net_interest_margin",
        "npl_ratio",
        "provision_coverage_ratio",
        "core_tier1_capital_adequacy_ratio",
        "tier1_capital_adequacy_ratio",
        "capital_adequacy_ratio",
        "customer_deposits",
        "loans_and_advances",
    }:
        return "bank_metrics"
    if field_name in {
        "core_solvency_adequacy_ratio",
        "comprehensive_solvency_adequacy_ratio",
        "premium_income",
        "total_investment_yield",
        "net_investment_yield",
        "comprehensive_investment_yield",
    }:
        return "insurance_metrics"
    if field_name in {
        "inventory",
        "gross_margin",
        "contract_liabilities",
        "capex_cash_paid",
        "free_cash_flow",
        "monetary_funds",
        "short_term_borrowings",
        "total_liabilities",
        "asset_liability_ratio",
        "selling_expense",
        "rd_expense",
        "finance_expense",
    }:
        return "industry_financials"
    return "periodic_report_financials"


def _compact_pdf_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


_CN_NUMBER_PATTERN = r"-?(?:\d{1,3}(?:[,，]\d{3})+|\d{1,4})(?:\.\d{1,2})?"
_UNIT_GAP = r"(?:（[^）]{0,8}）|\([^)]{0,8}\)|[^0-9\-]{0,6})"


def _fact_field_names(facts: List[FactCandidate]) -> set[str]:
    return {fact.field_name for fact in facts}


def _append_once(
    facts: List[FactCandidate],
    field_name: str,
    field_value: str,
    unit: str,
    source_text: str,
    numeric_value: Optional[float] = None,
    confidence: str = "medium",
    fact_type: Optional[str] = None,
    extractor: str = "rule_periodic_report_v1",
) -> None:
    if field_name in _fact_field_names(facts):
        return
    _append_typed_fact(
        facts,
        fact_type or _metric_fact_type(field_name),
        field_name,
        field_value,
        unit,
        source_text,
        numeric_value=numeric_value,
        confidence=confidence,
        extractor=extractor,
    )


def _append_numeric_match(
    facts: List[FactCandidate],
    text: str,
    field_name: str,
    pattern: str,
    unit: str,
    confidence: str = "medium",
) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    value = match.group(1)
    _append_once(
        facts,
        field_name,
        value,
        unit,
        _source_window(text, match.start(), match.end()),
        numeric_value=_normalize_number(value),
        confidence=confidence,
        extractor="rule_nonferrous_report_v1",
    )


def _extract_nonferrous_text_facts(announcement: Announcement, facts: List[FactCandidate]) -> None:
    if announcement.symbol != "600362.SH":
        return
    text = _compact_pdf_text(f"{announcement.pdf_text_excerpt or ''}\n{announcement.pdf_table_excerpt or ''}")
    if not text:
        return

    own_marker = text.find("自产铜精矿含铜")
    production_text = text
    if own_marker >= 0:
        production_text = text[max(0, own_marker - 2500) : min(len(text), own_marker + 500)]

    product_patterns = [
        ("cathode_copper_output", rf"阴极铜{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "万吨"),
        ("gold_output", rf"黄金{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "吨"),
        ("silver_output", rf"白银{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "吨"),
        ("sulfuric_acid_output", rf"硫酸{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "万吨"),
        ("copper_processing_output", rf"铜加工产品{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "万吨"),
        ("own_concentrate_copper_output", rf"自产铜精矿含铜{_UNIT_GAP}({_CN_NUMBER_PATTERN})", "万吨"),
    ]
    for field_name, pattern, unit in product_patterns:
        _append_numeric_match(facts, production_text, field_name, pattern, unit, confidence="high")

    resource_patterns = [
        ("controlled_copper_resource", rf"权益金属资源量约铜({_CN_NUMBER_PATTERN})万吨", "万吨"),
        ("controlled_gold_resource", rf"权益金属资源量约铜{_CN_NUMBER_PATTERN}万吨、黄金({_CN_NUMBER_PATTERN})吨", "吨"),
    ]
    for field_name, pattern, unit in resource_patterns:
        _append_numeric_match(facts, text, field_name, pattern, unit, confidence="medium")

    tc_match = re.search(
        r"TC[^。；;]{0,80}?(-?\d{1,4}(?:\.\d+)?)(?:至|到|—|~)(-?\d{1,4}(?:\.\d+)?)美元/吨",
        text,
    )
    if tc_match:
        low = tc_match.group(1)
        high = tc_match.group(2)
        source_text = _source_window(text, tc_match.start(), tc_match.end())
        _append_once(
            facts,
            "tc_spot_range",
            f"{low}至{high}",
            "USD/t",
            source_text,
            confidence="medium",
            extractor="rule_nonferrous_report_v1",
        )
        _append_once(
            facts,
            "tc_spot_low",
            low,
            "USD/t",
            source_text,
            numeric_value=_normalize_number(low),
            confidence="medium",
            extractor="rule_nonferrous_report_v1",
        )
        _append_once(
            facts,
            "tc_spot_high",
            high,
            "USD/t",
            source_text,
            numeric_value=_normalize_number(high),
            confidence="medium",
            extractor="rule_nonferrous_report_v1",
        )

    _append_numeric_match(
        facts,
        text,
        "global_visible_copper_inventory",
        rf"全球显性库存(?:为)?({_CN_NUMBER_PATTERN})万吨",
        "万吨",
        confidence="medium",
    )
    _append_numeric_match(
        facts,
        text,
        "global_visible_copper_inventory_change",
        rf"库存[^。；;]{{0,30}}?增加({_CN_NUMBER_PATTERN})万吨",
        "万吨",
        confidence="medium",
    )

    for field_name, pattern in [
        ("operating_cash_flow", rf"经营活动产生的现金流量净额({_CN_NUMBER_PATTERN})"),
        ("capex_cash_paid", rf"购建固定资产、?无形资产和其他长期资产支付的现金({_CN_NUMBER_PATTERN})"),
    ]:
        match = re.search(pattern, text)
        if match:
            value = match.group(1)
            _append_once(
                facts,
                field_name,
                value,
                "CNY",
                _source_window(text, match.start(), match.end()),
                numeric_value=_normalize_number(value),
                confidence="high",
                fact_type=_metric_fact_type(field_name),
                extractor="rule_nonferrous_report_v1",
            )


def _extract_nonferrous_table_facts(announcement: Announcement, facts: List[FactCandidate], table_text: str) -> None:
    if announcement.symbol != "600362.SH" or not table_text:
        return
    for row in _parse_table_rows(table_text):
        row_name = row[0]
        if "自有矿山" in row_name and len(row) >= 3:
            value = row[1]
            share = row[2]
            _append_once(
                facts,
                "own_mine_raw_material_cost",
                value,
                "CNY",
                " | ".join(row),
                numeric_value=_normalize_amount_to_yuan(value, "万元"),
                confidence="medium",
                extractor="rule_nonferrous_report_v1",
            )
            _append_once(
                facts,
                "own_mine_raw_material_cost_share",
                share,
                "%",
                " | ".join(row),
                numeric_value=_normalize_number(share),
                confidence="medium",
                extractor="rule_nonferrous_report_v1",
            )
        if "国内采购" in row_name and len(row) >= 3:
            _append_once(
                facts,
                "domestic_purchase_cost_share",
                row[2],
                "%",
                " | ".join(row),
                numeric_value=_normalize_number(row[2]),
                confidence="medium",
                extractor="rule_nonferrous_report_v1",
            )
        if "境外采购" in row_name and len(row) >= 3:
            _append_once(
                facts,
                "overseas_purchase_cost_share",
                row[2],
                "%",
                " | ".join(row),
                numeric_value=_normalize_number(row[2]),
                confidence="medium",
                extractor="rule_nonferrous_report_v1",
            )
        if row_name == "合计" and len(row) >= 2 and "原材料" in table_text[max(0, table_text.find("合计") - 800) : table_text.find("合计") + 800]:
            _append_once(
                facts,
                "total_raw_material_cost",
                row[1],
                "CNY",
                " | ".join(row),
                numeric_value=_normalize_amount_to_yuan(row[1], "万元"),
                confidence="low",
                extractor="rule_nonferrous_report_v1",
            )


def _append_cny_yi_match(
    facts: List[FactCandidate],
    text: str,
    field_name: str,
    pattern: str,
    confidence: str = "medium",
) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    value = match.group(1)
    _append_once(
        facts,
        field_name,
        value,
        "CNY",
        _source_window(text, match.start(), match.end()),
        numeric_value=_normalize_amount_to_yuan(value, "亿元"),
        confidence=confidence,
        extractor="rule_insurance_report_v1",
    )


def _append_million_match(
    facts: List[FactCandidate],
    text: str,
    field_name: str,
    pattern: str,
    confidence: str = "medium",
) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    value = match.group(1)
    _append_once(
        facts,
        field_name,
        value,
        "CNY",
        _source_window(text, match.start(), match.end()),
        numeric_value=_normalize_amount_to_yuan(value, "百万元"),
        confidence=confidence,
        extractor="rule_insurance_report_v1",
    )


def _append_pct_match(
    facts: List[FactCandidate],
    text: str,
    field_name: str,
    pattern: str,
    confidence: str = "medium",
) -> None:
    match = re.search(pattern, text)
    if not match:
        return
    value = match.group(1)
    _append_once(
        facts,
        field_name,
        value,
        "%",
        _source_window(text, match.start(), match.end()),
        numeric_value=_normalize_number(value),
        confidence=confidence,
        extractor="rule_insurance_report_v1",
    )


def _extract_insurance_text_facts(announcement: Announcement, facts: List[FactCandidate]) -> None:
    if announcement.symbol != "601336.SH":
        return
    text = _compact_pdf_text(f"{announcement.pdf_text_excerpt or ''}\n{announcement.pdf_table_excerpt or ''}")
    if not text:
        return

    _append_cny_yi_match(facts, text, "original_premium_income", rf"原保险保费收入({_CN_NUMBER_PATTERN})亿元", confidence="high")
    _append_pct_match(facts, text, "original_premium_income_change_pct", rf"原保险保费收入{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_cny_yi_match(facts, text, "first_year_regular_premium", rf"长期险首年期交保费({_CN_NUMBER_PATTERN})亿元", confidence="high")
    _append_pct_match(facts, text, "first_year_regular_premium_change_pct", rf"长期险首年期交保费{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_cny_yi_match(facts, text, "ten_year_plus_regular_premium", rf"十年期及以上期交保费({_CN_NUMBER_PATTERN})亿元", confidence="high")
    _append_pct_match(facts, text, "ten_year_plus_regular_premium_change_pct", rf"十年期及以上期交保费{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_cny_yi_match(facts, text, "renewal_premium", rf"续期保费收入({_CN_NUMBER_PATTERN})亿元", confidence="medium")
    _append_pct_match(facts, text, "renewal_premium_change_pct", rf"续期保费收入{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="medium")
    _append_pct_match(facts, text, "surrender_rate", rf"退保率为({_CN_NUMBER_PATTERN})%", confidence="medium")

    _append_cny_yi_match(facts, text, "new_business_value", rf"新业务价值({_CN_NUMBER_PATTERN})亿元", confidence="high")
    _append_pct_match(facts, text, "new_business_value_growth_pct", rf"新业务价值{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_cny_yi_match(facts, text, "embedded_value", rf"内含价值({_CN_NUMBER_PATTERN})亿元", confidence="high")
    _append_pct_match(facts, text, "embedded_value_growth_pct", rf"内含价值{_CN_NUMBER_PATTERN}亿元[^。；;]{{0,30}}?同比增长({_CN_NUMBER_PATTERN})%", confidence="high")

    annual_nbv = re.search(rf"一年新业务价值.*?202320242025({_CN_NUMBER_PATTERN})[0-9.]+%({_CN_NUMBER_PATTERN})%", text)
    if annual_nbv:
        _append_once(
            facts,
            "new_business_value",
            annual_nbv.group(1),
            "CNY",
            _source_window(text, annual_nbv.start(), annual_nbv.end()),
            numeric_value=_normalize_amount_to_yuan(annual_nbv.group(1), "百万元"),
            confidence="medium",
            extractor="rule_insurance_report_v1",
        )
        _append_once(
            facts,
            "new_business_value_growth_pct",
            annual_nbv.group(2),
            "%",
            _source_window(text, annual_nbv.start(), annual_nbv.end()),
            numeric_value=_normalize_number(annual_nbv.group(2)),
            confidence="medium",
            extractor="rule_insurance_report_v1",
        )

    _append_cny_yi_match(facts, text, "investment_assets", rf"投资资产为({_CN_NUMBER_PATTERN})亿元", confidence="medium")
    _append_pct_match(facts, text, "total_investment_yield", rf"年化总投资收益率[^。；;]*?为({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_pct_match(facts, text, "comprehensive_investment_yield", rf"年化综合投资收益率[^。；;]*?为({_CN_NUMBER_PATTERN})%", confidence="high")
    _append_pct_match(facts, text, "total_investment_yield", rf"({_CN_NUMBER_PATTERN})%0\.8pt总投资收益率", confidence="medium")

    _append_million_match(facts, text, "core_capital", rf"核心资本({_CN_NUMBER_PATTERN})", confidence="medium")
    _append_million_match(facts, text, "actual_capital", rf"实际资本({_CN_NUMBER_PATTERN})", confidence="medium")
    _append_million_match(facts, text, "minimum_capital", rf"最低资本({_CN_NUMBER_PATTERN})", confidence="medium")

    persistency_match = re.search(r"13个月及25个月继续率同比提升", text)
    if persistency_match:
        _append_once(
            facts,
            "persistency_commentary",
            "13个月及25个月继续率同比提升",
            "text",
            _source_window(text, persistency_match.start(), persistency_match.end()),
            confidence="medium",
            fact_type="insurance_metrics",
            extractor="rule_insurance_report_v1",
        )
    productivity_match = re.search(r"绩优人力人均期交保费同比增长超25%", text)
    if productivity_match:
        _append_once(
            facts,
            "agent_productivity_commentary",
            "绩优人力人均期交保费同比增长超25%",
            "text",
            _source_window(text, productivity_match.start(), productivity_match.end()),
            confidence="medium",
            fact_type="insurance_metrics",
            extractor="rule_insurance_report_v1",
        )


def extract_periodic_report_facts(announcement: Announcement) -> List[FactCandidate]:
    table_text = getattr(announcement, "pdf_table_excerpt", "") or ""
    text = announcement.pdf_text_excerpt or announcement.structured_summary or announcement.title
    facts: List[FactCandidate] = []

    report_period = _normalize_report_period(announcement.title, text)
    if report_period:
        _append_typed_fact(
            facts,
            "periodic_report_financials",
            "report_period",
            report_period,
            "period",
            announcement.title,
            confidence="medium",
            extractor="rule_periodic_report_v1",
        )

    _extract_nonferrous_text_facts(announcement, facts)
    _extract_nonferrous_table_facts(announcement, facts, table_text)
    _extract_insurance_text_facts(announcement, facts)

    if not table_text:
        return facts

    amount_multiplier = _amount_multiplier_from_text(text)
    metric_rules = [
        ("total_assets", ["资产总额"], []),
        ("total_liabilities", ["负债总额"], []),
        ("asset_liability_ratio", ["资产负债率"], []),
        ("shareholder_equity", ["股东权益"], ["归属于", "每股"]),
        ("book_value_per_share", ["每股净资产"], []),
        ("monetary_funds", ["货币资金"], []),
        ("short_term_borrowings", ["短期借款"], []),
        ("revenue", ["营业收入"], []),
        ("gross_margin", ["毛利率"], []),
        ("attributable_net_profit", ["归属于", "股东", "净利润"], ["扣除"]),
        ("deducted_attributable_net_profit", ["扣除", "归属于", "股东", "净利润"], []),
        ("selling_expense", ["销售费用"], []),
        ("rd_expense", ["研发费用"], []),
        ("rd_expense", ["研究", "开发", "费用"], []),
        ("finance_expense", ["财务费用"], []),
        ("operating_cash_flow", ["经营活动产生的现金流量净额"], ["每股"]),
        ("operating_cash_flow_per_share", ["每股经营活动产生的现金流量净额"], []),
        ("basic_eps", ["基本", "每股收益"], ["扣除"]),
        ("weighted_roe", ["加权平均净资产收益率"], []),
        ("contract_liabilities", ["合同负债"], []),
        ("inventory", ["存货"], ["跌价", "周转", "增加"]),
        ("capex_cash_paid", ["购建固定资产", "支付的现金"], []),
        ("customer_deposits", ["吸收存款", "本金"], []),
        ("loans_and_advances", ["发放贷款", "垫款", "本金"], []),
        ("net_interest_margin", ["净息差"], []),
        ("npl_ratio", ["不良贷款率"], []),
        ("provision_coverage_ratio", ["拨备覆盖率"], []),
        ("core_tier1_capital_adequacy_ratio", ["核心一级资本充足率"], []),
        ("tier1_capital_adequacy_ratio", ["一级资本充足率"], ["核心"]),
        ("capital_adequacy_ratio", ["资本充足率"], ["一级", "核心"]),
        ("premium_income", ["保险", "收入"], ["投资", "服务"]),
        ("total_investment_yield", ["总投资收益率"], []),
        ("net_investment_yield", ["净投资收益率"], []),
        ("comprehensive_investment_yield", ["综合投资收益率"], []),
        ("core_solvency_adequacy_ratio", ["核心偿付能力充足率"], []),
        ("comprehensive_solvency_adequacy_ratio", ["综合偿付能力充足率"], []),
    ]
    seen = _fact_field_names(facts)
    numeric_by_field = {}
    source_by_field = {}
    for row in _parse_table_rows(table_text):
        row_name = row[0]
        for field_name, includes, excludes in metric_rules:
            if field_name in seen:
                continue
            if not _row_matches(row_name, includes, excludes):
                continue
            value = _select_metric_value(row, field_name)
            unit = _field_unit_for_metric(row_name, amount_multiplier, field_name)
            numeric = _numeric_for_metric(value, unit, amount_multiplier)
            if numeric is None:
                continue
            _append_typed_fact(
                facts,
                _metric_fact_type(field_name),
                field_name,
                value,
                unit,
                " | ".join(row),
                numeric_value=numeric,
                confidence="medium",
                extractor="rule_periodic_report_v1",
            )
            numeric_by_field[field_name] = numeric
            source_by_field[field_name] = " | ".join(row)
            if len(row) >= 4 and "%" in row[-1]:
                change_value = row[-1]
                _append_typed_fact(
                    facts,
                    _metric_fact_type(field_name),
                    f"{field_name}_change_pct",
                    change_value,
                    "%",
                    " | ".join(row),
                    numeric_value=_normalize_number(change_value),
                    confidence="medium",
                    extractor="rule_periodic_report_v1",
                )
            seen.add(field_name)
            break
    operating_cash_flow = numeric_by_field.get("operating_cash_flow")
    capex_cash_paid = numeric_by_field.get("capex_cash_paid")
    if operating_cash_flow is not None and capex_cash_paid is not None and "free_cash_flow" not in seen:
        free_cash_flow = operating_cash_flow - capex_cash_paid
        _append_typed_fact(
            facts,
            "industry_financials",
            "free_cash_flow",
            f"{free_cash_flow:.0f}",
            "CNY",
            f"computed from operating_cash_flow and capex_cash_paid；{source_by_field.get('operating_cash_flow', '')}；{source_by_field.get('capex_cash_paid', '')}",
            numeric_value=free_cash_flow,
            confidence="medium",
            extractor="rule_periodic_report_v1",
        )
    return facts


def extract_facts_for_announcement(announcement: Announcement) -> List[FactCandidate]:
    if announcement.announcement_type == "权益分派/分红":
        return extract_dividend_facts(announcement)
    if announcement.announcement_type == "业绩预告/快报":
        return extract_earnings_forecast_facts(announcement)
    if announcement.announcement_type == "定期报告":
        return extract_periodic_report_facts(announcement)
    return []


def save_extracted_facts(db: Session, announcement: Announcement) -> List[ExtractedFact]:
    db.execute(delete(ExtractedFact).where(ExtractedFact.announcement_id == announcement.id))
    candidates = extract_facts_for_announcement(announcement)
    facts: List[ExtractedFact] = []
    for candidate in candidates:
        fact = ExtractedFact(
            announcement_id=announcement.id,
            symbol=announcement.symbol,
            fact_type=candidate.fact_type,
            field_name=candidate.field_name,
            field_value=candidate.field_value,
            unit=candidate.unit,
            numeric_value=candidate.numeric_value,
            source_text=candidate.source_text,
            confidence=candidate.confidence,
            extractor=candidate.extractor,
        )
        db.add(fact)
        facts.append(fact)
    db.commit()
    for fact in facts:
        db.refresh(fact)
    return facts


def list_extracted_facts(db: Session, symbol: str = "", announcement_id: Optional[int] = None, limit: int = 200) -> List[ExtractedFact]:
    query = select(ExtractedFact).order_by(ExtractedFact.created_at.desc(), ExtractedFact.id.desc()).limit(limit)
    if announcement_id is not None:
        query = (
            select(ExtractedFact)
            .where(ExtractedFact.announcement_id == announcement_id)
            .order_by(ExtractedFact.id.asc())
            .limit(limit)
        )
    elif symbol:
        query = (
            select(ExtractedFact)
            .where(ExtractedFact.symbol == symbol)
            .order_by(ExtractedFact.created_at.desc(), ExtractedFact.id.desc())
            .limit(limit)
        )
    return list(db.scalars(query))
