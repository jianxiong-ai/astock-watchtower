from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models import Announcement
from app.schemas import AnalyzeResponse, PositionOut
from app.services.action_advice import build_position_action_advice


def _to_float(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fmt_money(value: object) -> str:
    number = _to_float(value)
    if number is None:
        return "不可靠可得"
    return f"¥{number:,.2f}"


def _fmt_pct(value: object) -> str:
    number = _to_float(value)
    if number is None:
        return "不可靠可得"
    return f"{number:.2f}%"


def _fmt_ratio(value: object) -> str:
    number = _to_float(value)
    if number is None:
        return "不可靠可得"
    return f"{number:.2f}x"


def _fmt_optional_money(value: Optional[float]) -> str:
    if value is None:
        return "不可靠可得"
    return f"¥{value:,.2f}"


def _fmt_optional_pct(value: Optional[float]) -> str:
    if value is None:
        return "不可靠可得"
    return f"{value:.2f}%"


def _fmt_large_money(value: object) -> str:
    number = _to_float(value)
    if number is None:
        return "不可靠可得"
    if abs(number) >= 100_000_000:
        return f"¥{number / 100_000_000:,.2f}亿"
    return f"¥{number:,.2f}"


def _data_mode_label(data_mode: str) -> str:
    if data_mode == "completed_session":
        return "最新已完成交易日"
    if data_mode == "intraday_reference":
        return "盘中/实时参考"
    return data_mode or "不可靠可得"


def _generated_at() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _section(analysis: AnalyzeResponse, key: str) -> dict[str, Any]:
    for section in analysis.report_sections or []:
        if section.get("key") == key:
            return dict(section)
    return {}


def _safe_list(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _clean_sentence(value: object) -> str:
    return str(value or "").strip().rstrip("。；; ")


def build_trigger_summary(
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    force_notify: bool = False,
    new_announcements: Optional[list[Announcement]] = None,
    announcement_warning: str = "",
) -> tuple[bool, str]:
    snapshot = analysis.snapshot
    change_pct = float(snapshot.get("change_pct") or 0)
    market_weather = analysis.market_weather.get("classification", "Unknown")
    reasons = []

    if abs(change_pct) >= 4:
        reasons.append(f"股价单日变动 {change_pct:.2f}%")
    if market_weather == "Risk-off":
        reasons.append("市场天气 Risk-off")
    if position and position.warnings:
        reasons.append("持仓数据存在警告")
    if new_announcements:
        high_count = sum(1 for item in new_announcements if item.importance == "high")
        medium_count = sum(1 for item in new_announcements if item.importance == "medium")
        if high_count:
            reasons.append(f"新增 high 官方公告 {high_count} 条")
        elif medium_count:
            reasons.append(f"新增 medium 官方公告 {medium_count} 条")
        else:
            reasons.append(f"新增官方公告 {len(new_announcements)} 条")
    if announcement_warning:
        reasons.append("官方公告源警告")
    if force_notify and not reasons:
        reasons.append("手动生成当前分析推送")

    return bool(reasons), "；".join(reasons)


def _trigger_rows(
    *,
    analysis: AnalyzeResponse,
    trigger_summary: str,
    new_announcements: Optional[list[Announcement]],
    announcement_warning: str,
) -> list[str]:
    rows: list[str] = []
    snapshot = analysis.snapshot or {}
    technicals = analysis.universal_indicators.get("technicals") or {}
    change_pct = _to_float(snapshot.get("change_pct")) or 0.0
    weather = str((analysis.market_weather or {}).get("classification") or "Unknown")
    signals = _safe_list(technicals.get("signals"))

    if trigger_summary and trigger_summary != "无触发":
        rows.append(f"- high：{trigger_summary}。")
    if abs(change_pct) >= 4:
        rows.append(
            f"- high：{analysis.name} 单日涨跌幅达到 {_fmt_pct(change_pct)}；"
            f"收盘/价格 {_fmt_money(snapshot.get('price'))}，时间 {snapshot.get('timestamp') or '不可靠可得'}。"
        )
    if weather == "Risk-off":
        rows.append("- medium：市场温度 Risk-off，仓位建议默认偏向控制集中度、保留现金。")
    for signal in signals[:3]:
        rows.append(f"- watch：技术信号：{signal}。")
    if new_announcements:
        high_count = sum(1 for item in new_announcements if item.importance == "high")
        medium_count = sum(1 for item in new_announcements if item.importance == "medium")
        severity = "high" if high_count else "medium" if medium_count else "watch"
        rows.append(f"- {severity}：新增官方公告 {len(new_announcements)} 条，需核对事件层影响。")
    if announcement_warning:
        rows.append(f"- watch：公告源警告：{announcement_warning}")
    if not rows:
        rows.append("- watch：本次未触发强阈值；仅保留完成日监控快照和下一证据。")
    return rows


def _market_breadth_summary(analysis: AnalyzeResponse) -> str:
    weather = analysis.market_weather or {}
    breadth = weather.get("breadth") if isinstance(weather.get("breadth"), dict) else {}
    sector_weather = weather.get("sector_weather") if isinstance(weather.get("sector_weather"), dict) else {}
    parts = [f"市场 {weather.get('classification') or 'Unknown'}"]
    if breadth:
        parts.append(
            f"A股上涨/下跌 {breadth.get('up', '不可靠可得')}/{breadth.get('down', '不可靠可得')}，"
            f"上涨占比 {_fmt_pct(breadth.get('rising_ratio'))}"
        )
    if sector_weather:
        parts.append(
            f"行业上涨/下跌 {sector_weather.get('up', '不可靠可得')}/{sector_weather.get('down', '不可靠可得')}"
        )
    return "；".join(parts)


def _top_three_items(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    trigger_summary: str,
    new_announcements: Optional[list[Announcement]],
    announcement_warning: str,
    portfolio_market_value: Optional[float],
) -> list[str]:
    snapshot = analysis.snapshot or {}
    technicals = analysis.universal_indicators.get("technicals") or {}
    change_pct = _to_float(snapshot.get("change_pct")) or 0.0
    signals = [str(item) for item in _safe_list(technicals.get("signals")) if item]
    advice = build_position_action_advice(analysis, position, portfolio_market_value=portfolio_market_value)
    items: list[str] = []

    if trigger_summary and trigger_summary != "无触发":
        items.append(f"触发：{trigger_summary}")
    if abs(change_pct) >= 4:
        items.append(
            f"价格：{analysis.name} 完成日涨跌幅 {_fmt_pct(change_pct)}，价格 {_fmt_money(snapshot.get('price'))}，"
            f"时间 {snapshot.get('timestamp') or '不可靠可得'}"
        )
    if signals:
        items.append(f"技术：{'；'.join(signals[:2])}")
    if new_announcements:
        important = [item for item in new_announcements if item.importance in {"high", "medium"}]
        first = (important or new_announcements)[0]
        items.append(f"公告：新增 {len(new_announcements)} 条，重点看 {first.importance.upper()}｜{first.title}")
    if str((analysis.market_weather or {}).get("classification") or "") == "Risk-off":
        items.append(f"市场：{_market_breadth_summary(analysis)}，操作默认偏向控制集中度和保留现金")
    if advice.get("posture"):
        items.append(
            f"持仓纪律：主姿态 {advice.get('posture')}；建议手数 {advice.get('lot_quantity_range') or '不适用'}；"
            f"下一决策点 {advice.get('next_decision_point')}"
        )
    if announcement_warning:
        items.append(f"数据：公告源警告，需复核官方公告同步；{announcement_warning}")
    if analysis.missing_inputs or analysis.stale_sources:
        items.append(f"数据边界：Missing {len(analysis.missing_inputs)} 项，Stale {len(analysis.stale_sources)} 项，只影响缺口相关结论")

    fallback_items = [
        f"市场：{_market_breadth_summary(analysis)}",
        f"个股：完成日价格 {_fmt_money(snapshot.get('price'))}，涨跌幅 {_fmt_pct(snapshot.get('change_pct'))}",
        "证据：继续核对官方公告、行业骨架和下一完成交易日技术状态",
    ]
    for item in fallback_items:
        if item not in items:
            items.append(item)
    return items[:3]


def _morning_brief_lines(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    trigger_summary: str,
    new_announcements: Optional[list[Announcement]],
    announcement_warning: str,
    portfolio_market_value: Optional[float],
) -> list[str]:
    advice = build_position_action_advice(analysis, position, portfolio_market_value=portfolio_market_value)
    snapshot = analysis.snapshot or {}
    posture = advice.get("posture") or "等待确认"
    severity = advice.get("severity") or "watch"
    lines = [
        "晨会摘要",
        (
            f"结论：{analysis.name}（{analysis.symbol}）｜{analysis.decision}｜{posture}（{severity}）｜"
            f"{_data_mode_label(analysis.data_mode)} {_fmt_money(snapshot.get('price'))}，"
            f"涨跌幅 {_fmt_pct(snapshot.get('change_pct'))}。"
        ),
        f"市场温度：{_market_breadth_summary(analysis)}。",
        "今日只看 3 件事：",
    ]
    for index, item in enumerate(
        _top_three_items(
            analysis=analysis,
            position=position,
            trigger_summary=trigger_summary,
            new_announcements=new_announcements,
            announcement_warning=announcement_warning,
            portfolio_market_value=portfolio_market_value,
        ),
        start=1,
    ):
        lines.append(f"{index}. {item}")
    lines.extend(
        [
            (
                f"操作纪律：{posture}；触发条件：{_clean_sentence(advice.get('trigger_condition'))}；"
                f"失效条件：{_clean_sentence(advice.get('invalidation_condition'))}。"
            ),
            f"数据边界：Missing {len(analysis.missing_inputs)} 项，Stale {len(analysis.stale_sources)} 项；缺口不补值、不替代估算。",
        ]
    )
    return lines


def _market_weather_lines(analysis: AnalyzeResponse) -> list[str]:
    weather = analysis.market_weather or {}
    lines = [
        f"市场温度：{weather.get('classification') or 'Unknown'}；风险分 {weather.get('risk_score', '不可靠可得')}；时间 {weather.get('as_of') or '不可靠可得'}。"
    ]
    indices = _safe_list(weather.get("indices"))
    if indices:
        lines.append("A股主要指数：")
        for item in indices[:4]:
            lines.append(
                f"- {item.get('name') or item.get('symbol')} {item.get('current') or '不可靠可得'}，"
                f"{_fmt_pct(item.get('change_pct'))}；{item.get('timestamp') or '不可靠可得'}"
            )
    breadth = weather.get("breadth") if isinstance(weather.get("breadth"), dict) else {}
    if breadth:
        lines.append(
            "A股市场宽度："
            f"上涨/下跌 {breadth.get('up', '不可靠可得')}/{breadth.get('down', '不可靠可得')}，"
            f"平盘 {breadth.get('flat', '不可靠可得')}，"
            f"涨跌停 {breadth.get('limit_up', '不可靠可得')}/{breadth.get('limit_down', '不可靠可得')}，"
            f"上涨占比 {_fmt_pct(breadth.get('rising_ratio'))}，"
            f"成交额 {_fmt_large_money(breadth.get('total_amount'))}；{breadth.get('timestamp') or '不可靠可得'}"
        )
    sector_weather = weather.get("sector_weather") if isinstance(weather.get("sector_weather"), dict) else {}
    if sector_weather:
        lines.append(
            "行业温度："
            f"上涨/下跌 {sector_weather.get('up', '不可靠可得')}/{sector_weather.get('down', '不可靠可得')}，"
            f"上涨占比 {_fmt_pct(sector_weather.get('rising_ratio'))}；{sector_weather.get('timestamp') or '不可靠可得'}"
        )
        top_gainers = _safe_list(sector_weather.get("top_gainers"))
        top_losers = _safe_list(sector_weather.get("top_losers"))
        top_inflows = _safe_list(sector_weather.get("top_inflows"))
        top_outflows = _safe_list(sector_weather.get("top_outflows"))
        if top_gainers:
            lines.append("行业涨幅居前：" + "；".join(f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}" for item in top_gainers[:3]))
        if top_losers:
            lines.append("行业跌幅居前：" + "；".join(f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}" for item in top_losers[:3]))
        if top_inflows:
            lines.append("行业资金流入居前：" + "；".join(f"{item.get('name')} {_fmt_large_money(item.get('main_net_inflow'))}" for item in top_inflows[:3]))
        if top_outflows:
            lines.append("行业资金流出居前：" + "；".join(f"{item.get('name')} {_fmt_large_money(item.get('main_net_inflow'))}" for item in top_outflows[:3]))
    hk_indices = _safe_list(weather.get("hk_indices"))
    if hk_indices:
        lines.append("港股/中资风险偏好：")
        for item in hk_indices[:3]:
            lines.append(
                f"- {item.get('name') or item.get('symbol')} {item.get('current') or '不可靠可得'}，"
                f"{_fmt_pct(item.get('change_pct'))}；{item.get('timestamp') or '不可靠可得'}"
            )
    us_indices = _safe_list(weather.get("us_indices"))
    if us_indices:
        lines.append("外围美股：")
        for item in us_indices[:3]:
            lines.append(
                f"- {item.get('name') or item.get('symbol')} {item.get('current') or '不可靠可得'}，"
                f"{_fmt_pct(item.get('change_pct'))}；{item.get('timestamp') or '不可靠可得'}"
            )
    commodities = _safe_list(weather.get("commodities"))
    if commodities:
        lines.append("商品/铜链：")
        for item in commodities[:4]:
            lines.append(
                f"- {item.get('name') or item.get('symbol')} {item.get('current') or '不可靠可得'}，"
                f"{_fmt_pct(item.get('change_pct'))}；{item.get('timestamp') or '不可靠可得'}；{item.get('source') or '不可靠可得'}"
            )
    limitations = _safe_list(weather.get("limitations"))
    limitations = [item for item in limitations if item]
    if limitations:
        lines.append(f"市场天气缺口：{'；'.join(str(item) for item in limitations[:2])}")
    return lines


def _market_snapshot_lines(analysis: AnalyzeResponse) -> list[str]:
    snapshot = analysis.snapshot or {}
    valuation = analysis.universal_indicators.get("valuation") or {}
    technicals = analysis.universal_indicators.get("technicals") or {}
    ma = technicals.get("ma") or {}
    high_low = technicals.get("high_low") or {}
    lines = [
        (
            f"完成日/价格口径：{_data_mode_label(analysis.data_mode)}；"
            f"{snapshot.get('timestamp') or '不可靠可得'}；来源 {snapshot.get('source') or '不可靠可得'}。"
        ),
        (
            f"价格 {_fmt_money(snapshot.get('price'))}，涨跌幅 {_fmt_pct(snapshot.get('change_pct'))}，"
            f"前收 {_fmt_money(snapshot.get('previous_close'))}，高/低 "
            f"{_fmt_money(snapshot.get('high'))}/{_fmt_money(snapshot.get('low'))}，"
            f"成交额 {_fmt_money(snapshot.get('amount'))}。"
        ),
        (
            f"市值 {_fmt_large_money(valuation.get('market_cap'))}，流通市值 {_fmt_large_money(valuation.get('float_market_cap'))}，"
            f"P/E {valuation.get('pe_dynamic') or '不可靠可得'}，P/B {valuation.get('pb') or '不可靠可得'}，"
            f"换手率 {_fmt_pct(valuation.get('turnover_pct'))}。"
        ),
        (
            f"MA5/10/20/60/120：{ma.get('ma5', '不可靠可得')} / {ma.get('ma10', '不可靠可得')} / "
            f"{ma.get('ma20', '不可靠可得')} / {ma.get('ma60', '不可靠可得')} / {ma.get('ma120', '不可靠可得')}；"
            f"RSI14 {technicals.get('rsi14', '不可靠可得')}。"
        ),
        (
            f"20日高/低 {high_low.get('high_20', '不可靠可得')}/{high_low.get('low_20', '不可靠可得')}；"
            f"60日高/低 {high_low.get('high_60', '不可靠可得')}/{high_low.get('low_60', '不可靠可得')}；"
            f"回撤 {_fmt_pct(technicals.get('recent_peak_drawdown_pct'))}；"
            f"成交量/20日均量 {_fmt_ratio(technicals.get('volume_ratio_to_ma20'))}。"
        ),
    ]
    signals = _safe_list(technicals.get("signals"))
    lines.append("技术状态：" + ("；".join(str(item) for item in signals[:5]) if signals else "未触发主要技术阈值。"))
    return lines


def _find_metric(rows: list[dict[str, Any]], keywords: list[str]) -> Optional[dict[str, Any]]:
    for row in rows:
        metric = str(row.get("metric") or "")
        if any(keyword in metric for keyword in keywords):
            return row
    return None


def _missing_core_row(metric: str, next_evidence: str, relevance: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "status": "Missing",
        "latest_reading": "不可靠可得",
        "as_of": "",
        "source": "",
        "relevance": relevance,
        "next_evidence": next_evidence,
    }


def _event_fallback_row(
    analysis: AnalyzeResponse,
    *,
    metric: str,
    keywords: list[str],
    status: str,
    reading: str,
    relevance: str,
    next_evidence: str,
) -> Optional[dict[str, Any]]:
    events = [event for event in _safe_list(analysis.events) if isinstance(event, dict)]
    for event in events:
        haystack = " ".join(
            str(event.get(key) or "")
            for key in ["title", "type", "summary", "structured_summary", "affected_layers", "next_evidence"]
        )
        if any(keyword in haystack for keyword in keywords):
            return {
                "metric": metric,
                "status": status,
                "latest_reading": reading,
                "as_of": str(event.get("published_at") or ""),
                "source": str(event.get("title") or ""),
                "source_url": str(event.get("url") or ""),
                "relevance": relevance,
                "next_evidence": next_evidence,
            }
    return None


def _merge_rows(metric: str, rows: list[Optional[dict[str, Any]]], fallback: dict[str, Any]) -> dict[str, Any]:
    available = [row for row in rows if row]
    if not available:
        return fallback
    status = "Available" if any(row.get("status") == "Available" for row in available) else str(available[0].get("status") or "Partial")
    reading = "；".join(str(row.get("latest_reading") or "不可靠可得") for row in available[:3])
    as_of = "；".join(str(row.get("as_of") or "") for row in available[:3] if row.get("as_of"))
    relevance = "；".join(str(row.get("relevance") or "") for row in available[:2] if row.get("relevance"))
    next_evidence = "；".join(str(row.get("next_evidence") or "") for row in available[:2] if row.get("next_evidence"))
    return {
        "metric": metric,
        "status": status,
        "latest_reading": reading or "不可靠可得",
        "as_of": as_of,
        "source": str(available[0].get("source") or ""),
        "source_url": str(available[0].get("source_url") or ""),
        "relevance": relevance,
        "next_evidence": next_evidence,
    }


def _core_rows(analysis: AnalyzeResponse) -> list[dict[str, Any]]:
    rows = [dict(row) for row in _safe_list((analysis.sector_indicators or {}).get("mapped_metrics")) if isinstance(row, dict)]
    industry = analysis.industry

    if industry == "有色/矿业":
        periodic_keywords = ["年度报告", "季度报告", "半年度报告", "定期报告", "现金流/资本开支", "成本/毛利", "产量/资源自给"]
        return [
            _merge_rows(
                "1. 自有矿/资源自给率",
                [
                    _find_metric(rows, ["自有矿", "资源自给", "产量"]),
                    _event_fallback_row(
                        analysis,
                        metric="1. 自有矿/资源自给率",
                        keywords=["产量/资源自给", "年度报告", "季度报告", "定期报告"],
                        status="Stable-on-latest-disclosure",
                        reading="已有官方定期报告/经营披露线索，但自有矿产量、品位、回收率、资源自给率尚未结构化抽取。",
                        relevance="资源端决定利润弹性和抗周期能力；不能因字段未抽取而把整组视为没有披露。",
                        next_evidence="打开最新年报/Q1 报告经营数据章节，抽取矿产铜、铜精矿、自给率、品位和产量指引。",
                    ),
                ],
                _missing_core_row("1. 自有矿/资源自给率", "定期报告经营数据、项目公告", "缺少资源端利润弹性和抗周期能力判断。"),
            ),
            _merge_rows(
                "2. 冶炼经济与 TC/RC",
                [_find_metric(rows, ["TC/RC"])],
                _missing_core_row("2. 冶炼经济与 TC/RC", "可靠行业数据源或公司披露", "缺少冶炼利润核心变量。"),
            ),
            _merge_rows(
                "3. 副产品贡献",
                [
                    _find_metric(rows, ["副产品", "金", "银", "硫酸"]),
                    _event_fallback_row(
                        analysis,
                        metric="3. 副产品贡献",
                        keywords=periodic_keywords,
                        status="Stale",
                        reading="官方定期报告可能包含金、银、硫酸等副产品数据，但当前未结构化抽取贡献口径。",
                        relevance="副产品可能对冲 TC/RC 或铜加工利润波动，缺字段时只能作为解释层待验证。",
                        next_evidence="抽取定期报告分产品收入/毛利、产销量，并接入可靠金银/硫酸价格源。",
                    ),
                ],
                _missing_core_row("3. 副产品贡献", "定期报告分产品数据、可靠商品价格源", "无法判断副产品是否对冲铜/冶炼波动。"),
            ),
            _merge_rows(
                "4. 物理铜/库存/升贴水",
                [_find_metric(rows, ["铜价", "库存", "升贴水"])],
                _missing_core_row("4. 物理铜/库存/升贴水", "SHFE/LME/COMEX 与可靠现货数据源", "无法解释铜价、股价与利润弹性的背离。"),
            ),
            _merge_rows(
                "5. 单位成本/能源成本",
                [
                    _find_metric(rows, ["单位成本", "能源成本", "成本", "毛利率"]),
                    _event_fallback_row(
                        analysis,
                        metric="5. 单位成本/能源成本",
                        keywords=["成本/毛利", "年度报告", "季度报告", "定期报告"],
                        status="Stale",
                        reading="已有官方定期报告/成本毛利披露线索，但单位现金成本、能源成本和采购成本尚未结构化抽取。",
                        relevance="成本曲线决定铜价变化能否转化为利润弹性。",
                        next_evidence="抽取定期报告成本、毛利率、能源/采购成本说明和经营数据。",
                    ),
                ],
                _missing_core_row("5. 单位成本/能源成本", "定期报告成本披露、经营数据", "缺少成本曲线与利润弹性验证。"),
            ),
            _merge_rows(
                "6. 现金流/资本开支",
                [
                    _find_metric(rows, ["经营现金流"]),
                    _find_metric(rows, ["资本开支", "Capex"]),
                    _find_metric(rows, ["自由现金流"]),
                    _find_metric(rows, ["存货"]),
                    _event_fallback_row(
                        analysis,
                        metric="6. 现金流/资本开支",
                        keywords=["现金流/资本开支", "年度报告", "季度报告", "定期报告"],
                        status="Stable-on-latest-disclosure",
                        reading="已有官方定期报告披露线索，但 OCF、capex、FCF、存货、短债等字段尚未结构化抽取。",
                        relevance="现金流和资本开支是验证利润含金量、营运资本吸收和项目回报的主轴。",
                        next_evidence="抽取现金流量表、资产负债表和重大项目公告，补齐 OCF、capex、FCF、存货、应收、短债。",
                    ),
                ],
                _missing_core_row("6. 现金流/资本开支", "现金流量表和重大项目公告", "不能完整判断现金转化、营运资本和项目回报。"),
            ),
        ]

    if industry == "保险":
        return [
            _merge_rows("1. 新业务价值", [_find_metric(rows, ["NBV", "新单"])], _missing_core_row("1. 新业务价值", "年报/半年报内含价值章节", "不能把保费增长等同于价值增长。")),
            _merge_rows("2. 渠道与保单质量", [_find_metric(rows, ["保费", "新单保费"])], _missing_core_row("2. 渠道与保单质量", "月度保费公告、定期报告渠道数据", "缺少渠道产能、继续率和退保质量判断。")),
            _merge_rows("3. 内含价值与利润释放", [_find_metric(rows, ["EV", "CSM", "保险服务"])], _missing_core_row("3. 内含价值与利润释放", "年报/半年报 EV 与 IFRS17 附注", "缺少价值存量和利润释放质量验证。")),
            _merge_rows("4. 投资表现与 ALM", [_find_metric(rows, ["投资收益率", "OCI", "久期"])], _missing_core_row("4. 投资表现与 ALM", "定期报告投资分析章节", "无法判断利率/权益市场对利润与偿付能力的影响。")),
            _merge_rows("5. 资本/偿付能力/流动性", [_find_metric(rows, ["偿付能力"])], _missing_core_row("5. 资本/偿付能力/流动性", "偿付能力季度报告/监管披露", "资本安全边际和分红约束无法判断。")),
            _merge_rows("6. 股东盈利与分红", [_find_metric(rows, ["股东盈利", "分红", "每股盈利", "ROE"])], _missing_core_row("6. 股东盈利与分红", "定期报告利润表、分红公告", "无法验证价值增长是否转化为股东回报。")),
        ]

    preferred = rows[:6]
    while len(preferred) < 6:
        preferred.append(_missing_core_row(f"{len(preferred) + 1}. 行业核心指标", "官方定期报告或行业专属 provider", "该核心指标尚未配置或抽取。"))
    return preferred


def _core_framework_lines(analysis: AnalyzeResponse) -> list[str]:
    lines = ["六组核心骨架："]
    for row in _core_rows(analysis):
        status = row.get("status") or "Missing"
        as_of = row.get("as_of") or "不可靠可得"
        reading = row.get("latest_reading") or "不可靠可得"
        relevance = row.get("relevance") or "限制判断精度。"
        next_evidence = row.get("next_evidence") or "等待下一来源。"
        lines.append(
            f"{row.get('metric')}：{status}。读数/状态：{reading}；截至 {as_of}；"
            f"重要性：{relevance}；下一证据：{next_evidence}"
        )
    return lines


def _events_lines(
    *,
    analysis: AnalyzeResponse,
    new_announcements: Optional[list[Announcement]],
    announcement_warning: str,
) -> list[str]:
    lines = []
    if new_announcements:
        lines.append("本次新增官方公告：")
        for item in new_announcements[:5]:
            summary = item.structured_summary or item.event_summary or "摘要不可得，需打开官方 PDF 核验。"
            lines.append(
                f"- {item.importance.upper()}｜{item.announcement_type}｜{item.title}｜"
                f"{item.published_at.isoformat(timespec='seconds')}｜{item.source_url}\n"
                f"  摘要：{summary}\n"
                f"  为什么重要：{item.why_matters or '需判断是否改变监控假设。'}\n"
                f"  下一证据：{item.next_evidence or '打开官方 PDF 核验正文。'}"
            )
    else:
        lines.append("本次扫描未发现新增官方公告。")
        event_section = _section(analysis, "official_evidence")
        events = _safe_list(event_section.get("events"))
        if events:
            lines.append("最近已入库公告/事件：")
            for event in events[:3]:
                lines.append(
                    f"- {event.get('importance', 'watch').upper()}｜{event.get('type') or ''}｜"
                    f"{event.get('title') or ''}｜{event.get('published_at') or '不可靠可得'}"
                )
    if announcement_warning:
        lines.append(f"公告源警告：{announcement_warning}")
    return lines


def _quality_lines(analysis: AnalyzeResponse) -> list[str]:
    lines = []
    if analysis.stale_sources:
        lines.append("Stale Sources：")
        for item in analysis.stale_sources[:6]:
            lines.append(
                f"- {item.get('company') or analysis.symbol}｜{item.get('metric') or '未命名指标'}｜"
                f"最后日期 {item.get('last_known_date') or '不可靠可得'}｜"
                f"尝试来源 {item.get('attempted_source') or item.get('preferred_source') or '不可靠可得'}｜"
                f"影响：{item.get('impact') or '限制判断精度'}｜"
                f"下一来源：{item.get('next_source') or item.get('preferred_source') or '不可靠可得'}"
            )
    else:
        lines.append("Stale Sources：暂无。")

    if analysis.missing_inputs:
        lines.append("Missing Inputs：")
        for item in analysis.missing_inputs[:8]:
            lines.append(
                f"- {item.get('company') or analysis.symbol}｜{item.get('metric') or '未命名指标'}｜"
                f"首选来源 {item.get('preferred_source') or item.get('next_source') or '不可靠可得'}｜"
                f"尝试来源 {item.get('attempted_source') or '不可靠可得'}｜"
                f"影响：{item.get('impact') or '限制判断精度'}"
            )
    else:
        lines.append("Missing Inputs：暂无。")
    return lines


def _validation_lines(analysis: AnalyzeResponse) -> list[str]:
    industry = analysis.industry
    if industry == "有色/矿业":
        return [
            "验证链：铜价/现货/TC/RC → 产量/成本/毛利率 → 利润 → 经营现金流/自由现金流 → 股价。",
            "当前能得出的结论：可判断完成日股价、估值和技术状态；可列出官方公告与已抽取财报事实。",
            "当前不能得出的结论：若 TC/RC、现货升贴水、自有矿产量、单位成本或副产品贡献缺失，不能把铜价单独当成利润代理。",
        ]
    if industry == "保险":
        return [
            "验证链：利率/权益市场 → 投资收益/OCI → EV/CSM/利润 → 偿付能力 → 分红能力；保费 → NBV/NBV Margin → 新业务 CSM。",
            "当前能得出的结论：可判断完成日价格、估值、技术、市场天气和官方公告。",
            "当前不能得出的结论：若 NBV、EV、CSM、投资收益率和偿付能力缺失，不能把保费或股价变化直接等同为价值改善。",
        ]
    return [
        "验证链：行情/估值/技术 → 官方公告/结构化财报事实 → 行业专属指标 → 持仓建议。",
        "当前能得出的结论：可基于已完成交易日数据做监控提示。",
        "当前不能得出的结论：缺失的行业专属数据不会被替代估算。",
    ]


def _position_lines(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    portfolio_market_value: Optional[float],
) -> list[str]:
    advice = build_position_action_advice(analysis, position, portfolio_market_value=portfolio_market_value)
    if not position:
        return [
            "暂无交易记录/持仓基线。",
            f"主姿态：{advice.get('posture')}（{advice.get('severity', 'watch')}）。",
            f"说明：{advice.get('rationale')}",
            f"下一决策点：{advice.get('next_decision_point')}",
        ]

    position_pct = advice.get("position_pct")
    distance_to_cost = None
    if position.latest_price is not None and position.average_cost:
        distance_to_cost = (position.latest_price - position.average_cost) / position.average_cost * 100
    return [
        (
            f"持仓：{position.shares} 股；平均成本 {_fmt_optional_money(position.average_cost)}；"
            f"最新完成日价格 {_fmt_optional_money(position.latest_price)} @{position.latest_price_time or '不可靠可得'}；"
            f"距成本 {_fmt_optional_pct(distance_to_cost)}；市值 {_fmt_optional_money(position.market_value)}。"
        ),
        (
            f"浮盈亏 {_fmt_optional_money(position.unrealized_pnl)}（{_fmt_optional_pct(position.unrealized_pnl_pct)}）；"
            f"已实现 {_fmt_optional_money(position.realized_pnl)}；合计 {_fmt_optional_money(position.total_pnl)}；"
            f"组合权重 {_fmt_pct(position_pct) if position_pct is not None else '不可靠可得'}。"
        ),
        f"主姿态：{advice.get('posture')}（{advice.get('severity')}）；建议手数：{advice.get('lot_quantity_range') or '不适用'}。",
        f"触发条件：{advice.get('trigger_condition')}",
        f"失效条件：{advice.get('invalidation_condition')}",
        f"理由：{advice.get('rationale')}",
        f"主要风险：{advice.get('main_risk')}",
        f"下一决策点：{advice.get('next_decision_point')}",
    ]


def _next_watch_lines(analysis: AnalyzeResponse) -> list[str]:
    rows = _core_rows(analysis)
    next_items = []
    for row in rows:
        next_evidence = str(row.get("next_evidence") or "")
        if next_evidence and next_evidence not in next_items:
            next_items.append(next_evidence)
    if analysis.missing_inputs:
        for item in analysis.missing_inputs[:2]:
            source = str(item.get("next_source") or item.get("preferred_source") or "")
            if source and source not in next_items:
                next_items.append(source)
    defaults = [
        "下一完成交易日收盘价、成交量和技术状态。",
        "最新官方公告/定期报告结构化事实。",
        "市场天气与行业专属指标是否补齐或恶化。",
    ]
    for item in defaults:
        if item not in next_items:
            next_items.append(item)
    return [f"{index}. {item}" for index, item in enumerate(next_items[:6], start=1)]


def _contract_lines(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    trigger_summary: str,
    calendar_source: str,
    calendar_warning: str,
    new_announcements: Optional[list[Announcement]],
    announcement_warning: str,
    portfolio_market_value: Optional[float],
) -> list[str]:
    generated_at = _generated_at()
    lines = [
        f"【A股订阅与分析】{analysis.name}（{analysis.symbol}）",
        "",
        f"数据模式：{_data_mode_label(analysis.data_mode)}。研究生成时间：{generated_at}（Asia/Shanghai）。",
        f"交易日历：{calendar_source}{'；' + calendar_warning if calendar_warning else ''}",
        f"价格/技术截止：{analysis.snapshot.get('timestamp') or '不可靠可得'}；来源：{analysis.snapshot.get('source') or '不可靠可得'}。",
        "",
        *_morning_brief_lines(
            analysis=analysis,
            position=position,
            trigger_summary=trigger_summary,
            new_announcements=new_announcements,
            announcement_warning=announcement_warning,
            portfolio_market_value=portfolio_market_value,
        ),
        "",
        "详细证据层",
        "",
        "1. 交易日与市场温度",
        *_market_weather_lines(analysis),
        "",
        "2. 触发总览",
        *_trigger_rows(
            analysis=analysis,
            trigger_summary=trigger_summary,
            new_announcements=new_announcements,
            announcement_warning=announcement_warning,
        ),
        "",
        f"{analysis.name}（{analysis.symbol}）",
        "",
        "A. 市场快照",
        *_market_snapshot_lines(analysis),
        "",
        "B. 六组核心骨架",
        *_core_framework_lines(analysis),
        "",
        "C. 解释与验证链",
        *_validation_lines(analysis),
        "",
        "D. 公告与事件",
        *_events_lines(analysis=analysis, new_announcements=new_announcements, announcement_warning=announcement_warning),
        "",
        "F. 持仓与操作建议",
        *_position_lines(analysis=analysis, position=position, portfolio_market_value=portfolio_market_value),
        "",
        "G. 下一观察点",
        *_next_watch_lines(analysis),
        "",
        "免责声明：本消息为自托管研究提醒，不构成投资建议，不执行交易。",
    ]
    return lines


def _markdown(text: str) -> dict:
    return {"tag": "markdown", "content": text}


def _hr() -> dict:
    return {"tag": "hr"}


def _chunk_lines(lines: list[str], max_chars: int = 2600) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def build_feishu_report_card(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    trigger_summary: str,
    calendar_source: str,
    calendar_warning: str,
    new_announcements: Optional[list[Announcement]] = None,
    announcement_warning: str = "",
    portfolio_market_value: Optional[float] = None,
) -> dict:
    color = "blue"
    if analysis.decision == "NOTIFY":
        color = "orange"
    if analysis.missing_inputs or analysis.stale_sources:
        color = "red" if analysis.decision == "NOTIFY" else "yellow"

    lines = _contract_lines(
        analysis=analysis,
        position=position,
        trigger_summary=trigger_summary,
        calendar_source=calendar_source,
        calendar_warning=calendar_warning,
        new_announcements=new_announcements,
        announcement_warning=announcement_warning,
        portfolio_market_value=portfolio_market_value,
    )
    elements: list[dict] = []
    for chunk_index, chunk in enumerate(_chunk_lines(lines), start=1):
        if chunk_index > 1:
            elements.append(_hr())
        elements.append(_markdown(chunk))

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"A股订阅与分析｜{analysis.name}（{analysis.symbol}）"},
            "template": color,
        },
        "elements": elements,
    }


def render_subscription_message(
    *,
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    trigger_summary: str,
    calendar_source: str,
    calendar_warning: str,
    new_announcements: Optional[list[Announcement]] = None,
    announcement_warning: str = "",
    portfolio_market_value: Optional[float] = None,
) -> str:
    return "\n".join(
        _contract_lines(
            analysis=analysis,
            position=position,
            trigger_summary=trigger_summary,
            calendar_source=calendar_source,
            calendar_warning=calendar_warning,
            new_announcements=new_announcements,
            announcement_warning=announcement_warning,
            portfolio_market_value=portfolio_market_value,
        )
    )
