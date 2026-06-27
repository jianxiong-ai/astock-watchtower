from typing import Any, Dict, List


def _to_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _fmt_money(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "不可靠可得"
    return f"¥{number:,.2f}"


def _fmt_large_money(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "不可靠可得"
    if abs(number) >= 100_000_000:
        return f"¥{number / 100_000_000:,.2f}亿"
    return f"¥{number:,.2f}"


def _fmt_pct(value: object) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "不可靠可得"
    return f"{number:.2f}%"


def _line(label: str, value: object, level: str = "info", source: str = "") -> Dict[str, Any]:
    return {"label": label, "value": value, "level": level, "source": source}


def _market_weather_items(market_weather: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = [_line("市场天气", f"{market_weather.get('classification')} @{market_weather.get('as_of')}")]
    breadth = market_weather.get("breadth") if isinstance(market_weather.get("breadth"), dict) else {}
    if breadth:
        items.extend(
            [
                _line(
                    "A股市场宽度",
                    (
                        f"上涨/下跌 {breadth.get('up', '不可靠可得')}/{breadth.get('down', '不可靠可得')}；"
                        f"上涨占比 {_fmt_pct(breadth.get('rising_ratio'))}"
                    ),
                    source=str(breadth.get("source") or ""),
                ),
                _line("涨跌停", f"{breadth.get('limit_up', '不可靠可得')} / {breadth.get('limit_down', '不可靠可得')}"),
                _line("全市场成交额", _fmt_large_money(breadth.get("total_amount"))),
            ]
        )
    sector_weather = market_weather.get("sector_weather") if isinstance(market_weather.get("sector_weather"), dict) else {}
    if sector_weather:
        top_gainers = list(sector_weather.get("top_gainers") or [])
        top_losers = list(sector_weather.get("top_losers") or [])
        items.extend(
            [
                _line(
                    "行业温度",
                    (
                        f"上涨/下跌 {sector_weather.get('up', '不可靠可得')}/{sector_weather.get('down', '不可靠可得')}；"
                        f"上涨占比 {_fmt_pct(sector_weather.get('rising_ratio'))}"
                    ),
                    source=str(sector_weather.get("source") or ""),
                ),
                _line("行业涨幅居前", "；".join(f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}" for item in top_gainers[:3]) or "不可靠可得"),
                _line("行业跌幅居前", "；".join(f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}" for item in top_losers[:3]) or "不可靠可得"),
            ]
        )
    return items


def build_report_sections(
    *,
    symbol: str,
    name: str,
    industry: str,
    decision: str,
    data_mode: str,
    snapshot: Dict[str, Any],
    market_weather: Dict[str, Any],
    valuation: Dict[str, Any],
    technicals: Dict[str, Any],
    sector_indicators: Dict[str, Any],
    financials: Dict[str, Any],
    events: List[Dict[str, Any]],
    stale_sources: List[Dict[str, Any]],
    missing_inputs: List[Dict[str, Any]],
    research_posture: Dict[str, Any],
) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []

    sections.append(
        {
            "key": "summary",
            "title": "结论摘要",
            "summary": f"{name}（{symbol}）｜{industry}｜{decision}｜{data_mode}",
            "items": [
                _line("研究姿态", research_posture.get("posture", "不可靠可得")),
                _line("依据", research_posture.get("rationale", "")),
                _line("下一证据", "、".join(str(item) for item in research_posture.get("next_evidence", [])[:4])),
            ],
        }
    )

    sections.append(
        {
            "key": "market_snapshot",
            "title": "市场快照",
            "summary": (
                f"价格 {_fmt_money(snapshot.get('price'))}；涨跌幅 {_fmt_pct(snapshot.get('change_pct'))}；"
                f"时间 {snapshot.get('timestamp') or '不可靠可得'}"
            ),
            "items": [
                _line("现价", _fmt_money(snapshot.get("price")), source=str(snapshot.get("source") or "")),
                _line("涨跌幅", _fmt_pct(snapshot.get("change_pct"))),
                _line("前收", _fmt_money(snapshot.get("previous_close"))),
                _line("最高/最低", f"{_fmt_money(snapshot.get('high'))} / {_fmt_money(snapshot.get('low'))}"),
                _line("成交额", _fmt_money(snapshot.get("amount"))),
                *_market_weather_items(market_weather),
            ],
        }
    )

    if valuation.get("status") == "Available":
        valuation_summary = (
            f"市值 {_fmt_large_money(valuation.get('market_cap'))}；PE {valuation.get('pe_dynamic') or '不可靠可得'}；"
            f"PB {valuation.get('pb') or '不可靠可得'}"
        )
        valuation_items = [
            _line("总市值", _fmt_large_money(valuation.get("market_cap")), source=str(valuation.get("source") or "")),
            _line("流通市值", _fmt_large_money(valuation.get("float_market_cap"))),
            _line("PE", valuation.get("pe_dynamic") or "不可靠可得"),
            _line("PB", valuation.get("pb") or "不可靠可得"),
            _line("换手率", _fmt_pct(valuation.get("turnover_pct"))),
        ]
    else:
        valuation_summary = str(valuation.get("warning") or "估值不可靠可得")
        valuation_items = [_line("估值状态", valuation_summary, level="warning")]

    if technicals.get("status") == "Available":
        ma = technicals.get("ma") or {}
        high_low = technicals.get("high_low") or {}
        signals = list(technicals.get("signals") or [])
        technical_summary = (
            f"MA5/20/60 {ma.get('ma5', '不可靠可得')}/{ma.get('ma20', '不可靠可得')}/{ma.get('ma60', '不可靠可得')}；"
            f"RSI14 {technicals.get('rsi14', '不可靠可得')}；信号 {'、'.join(str(item) for item in signals) or '无'}"
        )
        technical_items = [
            _line("MA5/10/20/60/120", f"{ma.get('ma5')} / {ma.get('ma10')} / {ma.get('ma20')} / {ma.get('ma60')} / {ma.get('ma120')}"),
            _line("RSI14", technicals.get("rsi14")),
            _line("20日高/低", f"{high_low.get('high_20')} / {high_low.get('low_20')}"),
            _line("60日高/低", f"{high_low.get('high_60')} / {high_low.get('low_60')}"),
            _line("近期高点回撤", _fmt_pct(technicals.get("recent_peak_drawdown_pct"))),
            _line("量比20日", technicals.get("volume_ratio_to_ma20") or "不可靠可得"),
            _line("技术信号", "、".join(str(item) for item in signals) or "无"),
        ]
    else:
        technical_summary = str(technicals.get("reason") or "技术指标不可靠可得")
        technical_items = [_line("技术状态", technical_summary, level="warning")]

    sections.append(
        {
            "key": "valuation_technical",
            "title": "估值与技术",
            "summary": f"{valuation_summary}｜{technical_summary}",
            "items": valuation_items + technical_items,
        }
    )

    mapped_summary = list(sector_indicators.get("mapped_summary") or [])
    sections.append(
        {
            "key": "sector_framework",
            "title": "行业骨架",
            "summary": "；".join(str(item) for item in mapped_summary[:5]) or str(sector_indicators.get("current_status") or "行业映射暂不可得"),
            "items": [
                _line("行业", industry),
                _line("核心指标模板", "、".join(str(item) for item in sector_indicators.get("core_metrics", [])[:8])),
                _line("覆盖率", sector_indicators.get("mapped_coverage") or {}),
            ],
            "table": sector_indicators.get("mapped_metrics") or [],
        }
    )

    evidence_lines = list(financials.get("evidence_lines") or [])
    sections.append(
        {
            "key": "official_evidence",
            "title": "官方公告与结构化事实",
            "summary": "；".join(str(item) for item in evidence_lines[:5]) or str(financials.get("note") or "暂无结构化事实"),
            "items": [_line("财报/公告事实", item) for item in evidence_lines[:8]],
            "events": events[:6],
        }
    )

    risk_items = []
    risk_items.extend(
        _line(
            str(item.get("metric")),
            f"{item.get('impact', '')}｜下一来源：{item.get('next_source') or item.get('preferred_source') or '不可靠可得'}",
            level="warning",
            source=str(item.get("attempted_source") or item.get("preferred_source") or ""),
        )
        for item in stale_sources[:5]
    )
    risk_items.extend(
        _line(
            str(item.get("metric")),
            f"{item.get('impact', '')}｜下一来源：{item.get('next_source') or item.get('preferred_source') or '不可靠可得'}",
            level="missing",
            source=str(item.get("attempted_source") or item.get("preferred_source") or ""),
        )
        for item in missing_inputs[:8]
    )
    sections.append(
        {
            "key": "data_quality",
            "title": "Stale Sources / Missing Inputs",
            "summary": f"Stale {len(stale_sources)} 项；Missing {len(missing_inputs)} 项",
            "items": risk_items,
        }
    )

    return sections
