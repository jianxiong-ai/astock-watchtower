from datetime import datetime, time
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Announcement, ExtractedFact
from app.schemas import AnalyzeResponse
from app.services.announcements import fetch_official_announcements, sync_official_announcements
from app.services.data_quality import missing_input, stale_source, source_warning
from app.services.industry_providers import build_industry_provider_context, merge_provider_rows
from app.services.indicators import compute_technical_indicators, infer_industry, sector_indicator_template
from app.services.market_data import DailyBar, fetch_market_weather, fetch_secondary_daily_bars, fetch_secondary_quote_valuation, fetch_sina_quotes
from app.services.report_builder import build_report_sections
from app.services.sector_mapping import build_sector_indicator_mapping
from app.services.symbols import resolve_symbol_query


FIELD_LABELS = {
    "report_period": "报告期",
    "cash_dividend_per_10_shares": "每10股现金分红",
    "annual_cash_dividend_per_10_shares": "全年每10股现金分红",
    "interim_cash_dividend_per_10_shares": "中期每10股现金分红",
    "record_date": "股权登记日",
    "ex_dividend_date": "除权除息日",
    "payment_date": "派息日",
    "share_base": "分红股本基数",
    "bonus_share_ratio": "送股比例",
    "capitalization_ratio": "转增比例",
    "net_profit_change_direction": "净利润变动方向",
    "net_profit_min": "归母净利润下限",
    "net_profit_max": "归母净利润上限",
    "net_profit_estimate": "归母净利润预估",
    "yoy_change_min_pct": "同比变化下限",
    "yoy_change_max_pct": "同比变化上限",
    "forecast_reason": "业绩变动原因",
    "official_report_date": "正式报告披露日",
    "total_assets": "资产总额",
    "shareholder_equity": "股东权益",
    "book_value_per_share": "每股净资产",
    "revenue": "营业收入",
    "gross_margin": "毛利率",
    "attributable_net_profit": "归母净利润",
    "deducted_attributable_net_profit": "扣非归母净利润",
    "operating_cash_flow": "经营现金流",
    "operating_cash_flow_per_share": "每股经营现金流",
    "basic_eps": "基本EPS",
    "weighted_roe": "加权ROE",
    "contract_liabilities": "合同负债",
    "inventory": "存货",
    "monetary_funds": "货币资金",
    "short_term_borrowings": "短期借款",
    "total_liabilities": "负债总额",
    "asset_liability_ratio": "资产负债率",
    "selling_expense": "销售费用",
    "rd_expense": "研发费用",
    "finance_expense": "财务费用",
    "capex_cash_paid": "资本开支现金流出",
    "free_cash_flow": "自由现金流",
    "customer_deposits": "吸收存款本金",
    "loans_and_advances": "发放贷款及垫款本金",
    "net_interest_margin": "净息差",
    "npl_ratio": "不良贷款率",
    "provision_coverage_ratio": "拨备覆盖率",
    "core_tier1_capital_adequacy_ratio": "核心一级资本充足率",
    "tier1_capital_adequacy_ratio": "一级资本充足率",
    "capital_adequacy_ratio": "资本充足率",
    "premium_income": "保险业务收入/保费",
    "original_premium_income": "原保险保费收入",
    "first_year_premium": "长期险首年保费",
    "first_year_regular_premium": "长期险首年期交保费",
    "ten_year_plus_regular_premium": "十年期及以上期交保费",
    "renewal_premium": "续期保费",
    "surrender_rate": "退保率",
    "persistency_commentary": "继续率说明",
    "agent_productivity_commentary": "代理人/绩优人力产能说明",
    "new_business_value": "新业务价值",
    "new_business_value_growth_pct": "新业务价值增长率",
    "embedded_value": "内含价值",
    "embedded_value_growth_pct": "内含价值增长率",
    "investment_assets": "投资资产",
    "total_investment_yield": "总投资收益率",
    "net_investment_yield": "净投资收益率",
    "comprehensive_investment_yield": "综合投资收益率",
    "core_capital": "核心资本",
    "actual_capital": "实际资本",
    "minimum_capital": "最低资本",
    "core_solvency_adequacy_ratio": "核心偿付能力充足率",
    "comprehensive_solvency_adequacy_ratio": "综合偿付能力充足率",
    "cathode_copper_output": "阴极铜产量",
    "gold_output": "黄金产量",
    "silver_output": "白银产量",
    "sulfuric_acid_output": "硫酸产量",
    "copper_processing_output": "铜加工产品产量",
    "own_concentrate_copper_output": "自产铜精矿含铜",
    "controlled_copper_resource": "权益铜资源量",
    "controlled_gold_resource": "权益黄金资源量",
    "tc_spot_range": "TC现货区间",
    "tc_spot_low": "TC现货低值",
    "tc_spot_high": "TC现货高值",
    "global_visible_copper_inventory": "全球显性铜库存",
    "global_visible_copper_inventory_change": "全球显性铜库存变化",
    "own_mine_raw_material_cost": "自有矿山原材料成本",
    "own_mine_raw_material_cost_share": "自有矿山原材料成本占比",
    "domestic_purchase_cost_share": "国内采购成本占比",
    "overseas_purchase_cost_share": "境外采购成本占比",
    "total_raw_material_cost": "原材料总成本",
}


def _completed_session_bars(bars: List[DailyBar], *, include_intraday: bool) -> List[DailyBar]:
    """Return bars that are safe to treat as completed daily sessions.

    Some secondary daily-kline providers expose the current trading day before
    the closing auction is fully settled. For completed-session reports, drop
    today's bar until after 15:05 Beijing time.
    """

    if include_intraday or not bars:
        return bars
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now.date().isoformat()
    if bars[-1].date == today and now.time() < time(15, 5):
        return bars[:-1] or bars
    return bars


def _snapshot_from_completed_bar(
    *,
    bar: DailyBar,
    previous_bar: Optional[DailyBar],
    source: str,
) -> Dict[str, object]:
    previous_close = previous_bar.close if previous_bar else None
    return {
        "quote_type": "completed_session",
        "price": bar.close,
        "previous_close": previous_close,
        "change_pct": round(bar.change_pct, 2),
        "high": bar.high,
        "low": bar.low,
        "volume_shares": bar.volume,
        "amount": bar.amount,
        "timestamp": f"{bar.date} 15:00:00",
        "session_date": bar.date,
        "source": source,
    }


def _format_fact_value(fact: ExtractedFact) -> str:
    if fact.numeric_value is None:
        return str(fact.field_value)
    if fact.unit == "CNY":
        return f"¥{fact.numeric_value:,.0f}"
    if fact.unit == "%":
        return f"{fact.numeric_value:.2f}%"
    if fact.unit == "CNY/share":
        return f"¥{fact.numeric_value:.2f}/股"
    return str(fact.field_value)


def _fact_to_dict(fact: ExtractedFact, announcement: Announcement) -> Dict[str, object]:
    label = FIELD_LABELS.get(fact.field_name)
    if label is None and fact.field_name.endswith("_change_pct"):
        base_name = fact.field_name[: -len("_change_pct")]
        label = f"{FIELD_LABELS.get(base_name, base_name)}变化率"
    if label is None:
        label = fact.field_name
    return {
        "announcement_id": fact.announcement_id,
        "announcement_title": announcement.title,
        "announcement_type": announcement.announcement_type,
        "published_at": announcement.published_at.isoformat(timespec="seconds"),
        "source_url": announcement.source_url,
        "fact_type": fact.fact_type,
        "field_name": fact.field_name,
        "label": label,
        "value": _format_fact_value(fact),
        "raw_value": fact.field_value,
        "unit": fact.unit,
        "numeric_value": fact.numeric_value,
        "confidence": fact.confidence,
        "source_text": fact.source_text,
    }


def _summarize_extracted_facts(db: Optional[Session], symbol: str) -> Dict[str, object]:
    if db is None:
        return {
            "status": "Missing",
            "reason": "未提供数据库会话，无法读取已入库结构化事实。",
            "recent_facts": [],
            "latest_fact_date": "",
            "coverage": {},
        }

    announcements = list(
        db.scalars(
            select(Announcement)
            .where(Announcement.symbol == symbol)
            .order_by(Announcement.published_at.desc(), Announcement.id.desc())
            .limit(60)
        )
    )
    if not announcements:
        return {
            "status": "Missing",
            "reason": "尚未入库官方公告，无法生成财报/分红/业绩预告结构化证据。",
            "recent_facts": [],
            "latest_fact_date": "",
            "coverage": {},
        }

    by_id = {item.id: item for item in announcements}
    facts = list(
        db.scalars(
            select(ExtractedFact)
            .where(ExtractedFact.announcement_id.in_(list(by_id.keys())))
            .order_by(ExtractedFact.created_at.desc(), ExtractedFact.id.asc())
            .limit(250)
        )
    )
    recent_facts = [_fact_to_dict(fact, by_id[fact.announcement_id]) for fact in facts if fact.announcement_id in by_id]
    fact_types = {str(item["fact_type"]) for item in recent_facts}
    latest_fact_date = str(max(item["published_at"] for item in recent_facts)) if recent_facts else ""
    coverage = {
        "periodic_report_financials": "available" if "periodic_report_financials" in fact_types else "missing",
        "industry_financials": "available" if "industry_financials" in fact_types else "missing",
        "bank_metrics": "available" if "bank_metrics" in fact_types else "missing",
        "insurance_metrics": "available" if "insurance_metrics" in fact_types else "missing",
        "earnings_forecast": "available" if "earnings_forecast" in fact_types else "missing",
        "dividend": "available" if "dividend" in fact_types else "missing",
    }
    return {
        "status": "Available" if recent_facts else "Missing",
        "reason": "已读取官方公告 PDF 抽取后的结构化事实。" if recent_facts else "公告已入库，但近期公告未抽出可用结构化事实。",
        "recent_facts": recent_facts[:200],
        "latest_fact_date": latest_fact_date,
        "coverage": coverage,
    }


def _fact_lines(fact_summary: Dict[str, object], limit: int = 8) -> List[str]:
    facts = fact_summary.get("recent_facts") or []
    lines = []
    priority = [
        ("periodic_report_financials", 5),
        ("industry_financials", 4),
        ("bank_metrics", 4),
        ("insurance_metrics", 4),
        ("earnings_forecast", 3),
        ("dividend", 3),
    ]
    for fact_type, per_type_limit in priority:
        for item in [fact for fact in facts if fact.get("fact_type") == fact_type][:per_type_limit]:  # type: ignore[union-attr]
            lines.append(
                f"{item.get('label')}={item.get('value')}｜{item.get('announcement_title')}｜{item.get('published_at')}"
            )
            if len(lines) >= limit:
                return lines
    for item in facts:  # type: ignore[assignment]
        line = f"{item.get('label')}={item.get('value')}｜{item.get('announcement_title')}｜{item.get('published_at')}"
        if line not in lines:
            lines.append(line)
        if len(lines) >= limit:
            break
    return lines


async def _load_announcements(
    db: Optional[Session],
    symbol: str,
    *,
    sync_announcements: bool,
) -> tuple[List[Announcement], str, List[Dict[str, str]]]:
    missing_inputs: List[Dict[str, str]] = []
    warning = ""
    try:
        if db is not None and sync_announcements:
            result = await sync_official_announcements(
                db,
                symbol,
                days=get_settings().analysis_announcement_lookback_days,
            )
            return result.announcements, result.warning, missing_inputs
        if db is not None:
            announcements = list(
                db.scalars(
                    select(Announcement)
                    .where(Announcement.symbol == symbol)
                    .order_by(Announcement.published_at.desc(), Announcement.id.desc())
                    .limit(30)
                )
            )
            return announcements, warning, missing_inputs
        items = await fetch_official_announcements(symbol, days=30)
        return list(items), warning, missing_inputs
    except Exception as exc:
        missing_inputs.append(
            missing_input(
                "官方公告",
                "SSE/SZSE official announcement provider",
                f"未能读取最近官方公告：{exc}",
                company=symbol,
                attempted_source="官方公告同步/本地公告表",
                next_source="恢复上交所/深交所公告接口后重新同步",
            )
        )
        return [], warning, missing_inputs


async def analyze_ashare(
    query: str,
    include_intraday: bool = True,
    db: Optional[Session] = None,
    sync_announcements: bool = True,
) -> AnalyzeResponse:
    normalized = await resolve_symbol_query(query)
    data_mode = "intraday_reference" if include_intraday else "completed_session"
    quotes = await fetch_sina_quotes([normalized])
    quote = quotes.get(normalized.symbol)
    if not quote:
        raise ValueError(f"未能读取行情：{normalized.symbol}")
    valuation: Dict[str, object] = {
        "status": "Missing",
        "source": "Eastmoney secondary quote/valuation",
        "market_cap": None,
        "float_market_cap": None,
        "pe_dynamic": None,
        "pb": None,
        "turnover_pct": None,
        "timestamp": "",
        "warning": "",
    }
    technicals: Dict[str, object] = {
        "status": "Missing",
        "reason": "历史 K 线尚未读取",
        "source": "Eastmoney secondary historical kline",
    }
    try:
        em_quote = await fetch_secondary_quote_valuation(normalized)
        valuation.update(
            {
                "status": "Available",
                "source": em_quote.get("source"),
                "market_cap": em_quote.get("market_cap"),
                "float_market_cap": em_quote.get("float_market_cap"),
                "pe_dynamic": em_quote.get("pe_dynamic"),
                "pb": em_quote.get("pb"),
                "turnover_pct": em_quote.get("turnover_pct"),
                "timestamp": em_quote.get("timestamp"),
            }
        )
    except Exception as exc:
        valuation["warning"] = f"估值源暂不可用：{exc}"
    completed_bars: List[DailyBar] = []
    try:
        bars = await fetch_secondary_daily_bars(normalized, limit=160)
        completed_bars = _completed_session_bars(bars, include_intraday=include_intraday)
        technicals = compute_technical_indicators(completed_bars)
    except Exception as exc:
        technicals = {
            "status": "Missing",
            "reason": f"历史 K 线源暂不可用：{exc}",
            "source": "Eastmoney secondary historical kline",
        }

    name = str(quote.get("name") or normalized.symbol)
    industry = infer_industry(name, normalized.symbol)
    market_weather = await fetch_market_weather()
    sector_template = sector_indicator_template(industry)
    announcements, announcement_warning, announcement_missing_inputs = await _load_announcements(
        db,
        normalized.symbol,
        sync_announcements=sync_announcements,
    )
    announcement_events = [
        {
            "title": item.title,
            "type": item.announcement_type,
            "importance": item.importance,
            "published_at": item.published_at.isoformat(timespec="seconds"),
            "source": item.source,
            "url": item.source_url,
            "summary": item.event_summary,
            "structured_summary": item.structured_summary,
            "pdf_extract_status": item.pdf_extract_status,
            "pdf_page_count": item.pdf_page_count,
            "pdf_text_chars": item.pdf_text_chars,
            "pdf_table_count": getattr(item, "pdf_table_count", 0),
            "why_matters": item.why_matters,
            "affected_layers": item.affected_layers,
            "next_evidence": item.next_evidence,
        }
        for item in announcements[:8]
    ]
    if announcement_warning:
        announcement_missing_inputs.append(
            source_warning(
                "官方公告源部分警告",
                announcement_warning,
                company=normalized.symbol,
                attempted_source="SSE/SZSE official announcement provider",
                preferred_source="SSE/SZSE official announcement provider",
                next_source="稍后重试官方公告同步并核对本地公告表",
            )
        )

    fact_summary = _summarize_extracted_facts(db, normalized.symbol)
    fact_lines = _fact_lines(fact_summary)
    sector_mapping = build_sector_indicator_mapping(industry, fact_summary)
    industry_provider_context = await build_industry_provider_context(industry, normalized.symbol, market_weather)
    mapped_metrics = merge_provider_rows(
        list(sector_mapping.get("rows") or []),
        list(industry_provider_context.get("rows") or []),
    )
    if not include_intraday and completed_bars:
        latest_bar = completed_bars[-1]
        previous_bar = completed_bars[-2] if len(completed_bars) >= 2 else None
        snapshot: Dict[str, object] = _snapshot_from_completed_bar(
            bar=latest_bar,
            previous_bar=previous_bar,
            source=str(technicals.get("source") or "Eastmoney secondary historical kline"),
        )
    else:
        snapshot = {
            "quote_type": "intraday_or_latest",
            "price": quote.get("current"),
            "previous_close": quote.get("previous_close"),
            "change_pct": round(float(quote.get("change_pct", 0.0)), 2),
            "high": quote.get("high"),
            "low": quote.get("low"),
            "volume_shares": quote.get("volume_shares"),
            "amount": quote.get("amount"),
            "timestamp": quote.get("timestamp"),
            "source": quote.get("source"),
        }
    snapshot.update(
        {
            "market_cap": valuation.get("market_cap"),
            "pe_dynamic": valuation.get("pe_dynamic"),
            "pb": valuation.get("pb"),
        }
    )

    has_financial_facts = bool(fact_summary.get("recent_facts"))
    change_pct = float(snapshot.get("change_pct") or 0.0)
    decision = "NOTIFY" if abs(change_pct) >= 4 or market_weather["classification"] == "Risk-off" else "DONT_NOTIFY"
    technical_signals = list(technicals.get("signals") or []) if isinstance(technicals, dict) else []
    if technical_signals:
        decision = "NOTIFY"
    posture = "等待确认" if market_weather["classification"] == "Risk-off" else "条件式关注"

    stale_sources = [
        stale_source(
            "行业特有非公告数据",
            "",
            "部分行业价格、资金流、北向/两融等外部数据仍未接入。",
            company=normalized.symbol,
            attempted_source="industry provider v1",
            preferred_source="后续 AkShare/Tushare/用户自定义 provider",
            next_source="配置行业价格、资金流或用户自带数据源",
        )
    ]
    provider_warnings = list(industry_provider_context.get("warnings") or [])
    if industry_provider_context.get("status") in {"Available", "Partial"} or industry_provider_context.get("rows"):
        stale_sources = []
    stale_sources.extend(provider_warnings)
    if valuation.get("status") != "Available":
        stale_sources.append(
            stale_source(
                "估值数据",
                str(valuation.get("timestamp") or ""),
                str(valuation.get("warning") or "PE/PB/市值不可得，估值判断受限。"),
                company=normalized.symbol,
                attempted_source=str(valuation.get("source") or "Eastmoney/Tencent secondary quote/valuation"),
                preferred_source="可靠行情估值 provider",
                next_source="重试 Eastmoney/Tencent 或配置正式行情估值源",
            )
        )
    if technicals.get("status") != "Available":
        stale_sources.append(
            stale_source(
                "日线技术指标",
                str(technicals.get("as_of") or ""),
                str(technicals.get("reason") or "历史 K 线不可得，技术判断受限。"),
                company=normalized.symbol,
                attempted_source=str(technicals.get("source") or "Eastmoney/Tencent secondary historical kline"),
                preferred_source="可靠历史 K 线 provider",
                next_source="重试历史 K 线源或配置正式行情源",
            )
        )
    if not has_financial_facts:
        stale_sources.append(
            stale_source(
                "官方公告结构化事实",
                str(fact_summary.get("latest_fact_date") or ""),
                "尚未抽到财报/分红/业绩预告字段，基本面证据只能停留在公告标题层。",
                company=normalized.symbol,
                attempted_source="本地公告 PDF 正文/表格抽取",
                preferred_source="官方公告 PDF 与结构化财报表格",
                next_source="刷新公告并检查 PDF 抽取质量页面",
            )
        )

    universal_indicators = {
        "valuation": valuation,
        "technicals": technicals,
        "events": {
            "status": "Available" if announcement_events else "Missing",
            "recent_count": len(announcement_events),
            "warning": announcement_warning,
        },
        "financials": {
            "status": fact_summary["status"],
            "latest_fact_date": fact_summary["latest_fact_date"],
            "coverage": fact_summary["coverage"],
            "recent_facts": fact_summary["recent_facts"],
            "evidence_lines": fact_lines,
            "note": fact_summary["reason"],
        },
    }
    sector_indicators = {
        "industry": industry,
        "core_metrics": sector_template["core_metrics"],
        "mapped_metrics": mapped_metrics,
        "mapped_summary": [
            *list(sector_mapping.get("summary_lines") or []),
            *list(industry_provider_context.get("summary_lines") or []),
        ][:8],
        "mapped_coverage": {
            "filing": sector_mapping["coverage"],
            "provider": industry_provider_context.get("coverage") or {},
            "total": {
                "available": len([row for row in mapped_metrics if row.get("status") == "Available"]),
                "partial": len([row for row in mapped_metrics if row.get("status") == "Partial"]),
                "missing": len([row for row in mapped_metrics if row.get("status") == "Missing"]),
                "total": len(mapped_metrics),
            },
        },
        "industry_provider": industry_provider_context,
        "current_status": (
            "已接入官方公告结构化事实和行业 provider v1；行业专属 KPI 仍需继续扩展。"
            if has_financial_facts and industry_provider_context.get("rows")
            else "已接入行业 provider v1；尚未抽到可用官方财报/分红/业绩预告事实。"
            if industry_provider_context.get("rows")
            else "行业模板已配置；尚未抽到可用官方财报/分红/业绩预告事实。"
        ),
        "official_fact_evidence": fact_lines,
    }
    missing_inputs = [
        missing_input(
            metric,
            "Official filings or configured provider",
            "限制行业特有判断和操作建议精度。",
            company=normalized.symbol,
            attempted_source="行业模板检查",
            next_source="官方定期报告、公告或后续配置的行业 provider",
        )
        for metric in sector_template["missing_inputs"]
    ] + list(sector_mapping.get("missing_inputs") or []) + list(industry_provider_context.get("missing_inputs") or []) + announcement_missing_inputs
    research_posture = {
        "position_basis": "无持仓基线/仅研究监控建议",
        "posture": posture,
        "rationale": (
            "MVP 使用行情、估值、技术指标、市场天气、官方公告与已抽取结构化事实；未接入完整行业外部数据时，不给具体手数建议。"
            if has_financial_facts
            else "MVP 使用行情、估值、技术指标与市场天气；官方公告结构化事实不足时，不给具体手数建议。"
        ),
        "next_evidence": [
            "核对最新定期报告结构化字段",
            "核对估值/技术信号是否持续",
            "接入行业特有 KPI",
        ],
    }
    report_sections = build_report_sections(
        symbol=normalized.symbol,
        name=name,
        industry=industry,
        decision=decision,
        data_mode=data_mode,
        snapshot=snapshot,
        market_weather=market_weather,
        valuation=valuation,
        technicals=technicals,
        sector_indicators=sector_indicators,
        financials=universal_indicators["financials"],
        events=announcement_events,
        stale_sources=stale_sources,
        missing_inputs=missing_inputs,
        research_posture=research_posture,
    )

    return AnalyzeResponse(
        symbol=normalized.symbol,
        name=name,
        exchange=normalized.exchange,
        industry=industry,
        data_mode=data_mode,
        decision=decision,
        market_weather=market_weather,
        snapshot=snapshot,
        universal_indicators=universal_indicators,
        sector_indicators=sector_indicators,
        events=announcement_events,
        stale_sources=stale_sources,
        missing_inputs=missing_inputs,
        research_posture=research_posture,
        report_sections=report_sections,
        sources=[
            {"label": "Sina quote", "type": "secondary", "url": "https://finance.sina.com.cn"},
            {"label": "Eastmoney quote/kline", "type": "secondary", "url": "https://quote.eastmoney.com"},
            {"label": "SSE announcements", "type": "official", "url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/"},
            {"label": "SZSE announcements", "type": "official", "url": "https://www.szse.cn/disclosure/listed/notice/index.html"},
        ],
    )
