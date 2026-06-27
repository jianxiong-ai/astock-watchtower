from typing import Any, Dict, Optional

from app.schemas import AnalyzeResponse, PositionOut


def _to_float(value: object) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _round_lot(quantity: int) -> int:
    if quantity <= 0:
        return 0
    return max(100, quantity // 100 * 100)


def _technical_signal_text(analysis: AnalyzeResponse) -> str:
    technicals = analysis.universal_indicators.get("technicals") or {}
    signals = technicals.get("signals") or []
    if not signals:
        return "暂无明确技术触发"
    return "、".join(str(item) for item in signals[:5])


def _fmt_optional_pct(value: Optional[float]) -> str:
    if value is None:
        return "不可靠可得"
    return f"{value:.2f}%"


def _fmt_optional_money(value: Optional[float]) -> str:
    if value is None:
        return "不可靠可得"
    return f"¥{value:,.2f}"


def _position_summary(position: PositionOut, latest_price: Optional[float], distance_to_cost: Optional[float]) -> str:
    return (
        f"{position.shares}股；成本¥{position.average_cost:,.4f}；"
        f"最新价{_fmt_optional_money(latest_price)}；"
        f"距成本{_fmt_optional_pct(distance_to_cost)}；"
        f"浮盈亏{_fmt_optional_money(position.unrealized_pnl)}"
        f"（{_fmt_optional_pct(position.unrealized_pnl_pct)}）"
    )


def _common_inputs(
    *,
    weather: str,
    technical_status: str,
    technical_signal: str,
    stale_count: int,
    missing_count: int,
    change_pct: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    valuation_status: str = "Missing",
) -> Dict[str, Any]:
    return {
        "market_weather": weather,
        "change_pct": change_pct,
        "volume_ratio_to_ma20": volume_ratio,
        "technical_status": technical_status,
        "technical_signal": technical_signal,
        "stale_count": stale_count,
        "missing_count": missing_count,
        "valuation_status": valuation_status,
    }


def build_position_action_advice(
    analysis: AnalyzeResponse,
    position: Optional[PositionOut],
    *,
    portfolio_market_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Build conservative, explainable position-aware action advice.

    The output is intentionally rule-based and auditable. It does not place trades
    and does not invent missing fundamentals.
    """

    snapshot = analysis.snapshot or {}
    technicals = analysis.universal_indicators.get("technicals") or {}
    valuation = analysis.universal_indicators.get("valuation") or {}
    market_weather = analysis.market_weather or {}
    weather = str(market_weather.get("classification") or "Unknown")
    change_pct = _to_float(snapshot.get("change_pct"))
    latest_price = _to_float(snapshot.get("price"))
    volume_ratio = _to_float(technicals.get("volume_ratio_to_ma20"))
    technical_status = str(technicals.get("status") or "Missing")
    technical_signal = _technical_signal_text(analysis)
    stale_count = len(analysis.stale_sources or [])
    missing_count = len(analysis.missing_inputs or [])
    data_gap_text = f"Missing {missing_count} 项、Stale {stale_count} 项"

    if not position or position.shares == 0:
        return {
            "posture": "等待确认",
            "severity": "watch",
            "urgency": "setup_required",
            "summary_line": "暂无持仓基线，只做研究监控；不生成买卖手数。",
            "position_summary": "暂无持仓或交易记录基线；仅输出研究监控建议。",
            "trigger_condition": "等待行情、公告、行业指标和可选持仓记录形成共同证据。",
            "invalidation_condition": "若补充交易记录后出现集中度过高、技术破位或基本面恶化，需要重新评估。",
            "rationale": "没有持仓基线时，成本、浮盈亏、仓位权重和分批手数都不可靠可得。",
            "main_risk": "无持仓数据会降低操作建议精度。",
            "next_decision_point": "上传/更新交易记录，或在重大公告、≥4%波动、技术突破/破位时复查。",
            "lot_quantity_range": "",
            "position_pct": None,
            "action_steps": [
                "先不做仓位动作；仅把行情、公告和行业证据纳入观察。",
                "如需要持仓建议，先上传或录入交易记录，让系统计算成本、浮盈亏和仓位权重。",
            ],
            "risk_controls": ["不根据缺失的成本/仓位信息倒推买卖建议。"],
            "decision_checklist": ["交易记录是否完整", "最新完成日价格和公告是否可得", "行业核心指标是否存在关键缺口"],
            "do_not": ["不因股票看似便宜就生成加仓建议。"],
            "inputs": _common_inputs(
                weather=weather,
                technical_status=technical_status,
                technical_signal=technical_signal,
                stale_count=stale_count,
                missing_count=missing_count,
            ),
        }

    market_value = position.market_value
    position_pct = None
    if portfolio_market_value and market_value is not None and portfolio_market_value > 0:
        position_pct = market_value / portfolio_market_value * 100

    distance_to_cost = None
    if latest_price is not None and position.average_cost:
        distance_to_cost = (latest_price - position.average_cost) / position.average_cost * 100

    severe_concentration = position_pct is not None and position_pct >= 45
    high_concentration = position_pct is not None and position_pct >= 30
    large_unrealized_loss = position.unrealized_pnl_pct is not None and position.unrealized_pnl_pct <= -12
    weak_market = weather == "Risk-off"
    abnormal_volume = volume_ratio is not None and volume_ratio >= 1.8
    large_move = change_pct is not None and abs(change_pct) >= 4
    data_quality_poor = stale_count + missing_count >= 6
    valuation_available = valuation.get("status") == "Available"

    trim_lot = _round_lot(max(100, int(position.shares * 0.1)))
    add_lot = _round_lot(max(100, int(position.shares * 0.1)))

    if severe_concentration and (weak_market or large_unrealized_loss or data_quality_poor):
        posture = "分批减仓"
        severity = "medium"
        urgency = "next_close_or_breakdown"
        trigger_condition = (
            "组合权重偏高，且出现市场风险偏冷、浮亏扩大或关键数据不足之一；"
            "若同时出现放量破位/基本面负面公告，优先执行。"
        )
        invalidation_condition = "若价格重新站回关键均线、市场天气转暖且官方数据未恶化，可暂停减仓。"
        rationale = "先控制单一标的对组合的拖累风险；成本价只作为压力位，不作为补仓理由。"
        main_risk = "减仓后若基本面迅速修复或板块反弹，可能降低反弹参与度。"
        next_decision_point = "下一交易日收盘、重大公告、或技术信号由破位转为修复时复查。"
        lot_quantity_range = f"{trim_lot}–{_round_lot(max(trim_lot, int(position.shares * 0.2)))}股"
        summary_line = f"分批减仓优先级较高；先用{lot_quantity_range}降低集中度，不做一次性清仓。"
        action_steps = [
            f"若下一完成交易日仍处于 Risk-off、放量破位或负面公告成立，先减 {lot_quantity_range}。",
            "若价格重新站回关键均线且市场天气转暖，暂停减仓并等待下一证据。",
            "减仓后更新交易记录，重新计算真实仓位和成本。",
        ]
        risk_controls = [
            "不因低于成本价而摊低成本。",
            "优先控制组合集中度和单票回撤，避免同日同时加大多个高相关仓位。",
            f"数据边界为 {data_gap_text}，缺口相关结论只作为风险提示，不替代事实。",
        ]
        decision_checklist = ["组合权重是否仍过高", "价格是否收回关键均线", "公告/财报是否出现负面证据", "市场天气是否从 Risk-off 修复"]
    elif weak_market or large_move or abnormal_volume or data_quality_poor:
        posture = "等待确认"
        severity = "watch"
        urgency = "wait_for_confirmation"
        trigger_condition = "等待波动、成交量、市场天气或缺失数据给出方向确认。"
        invalidation_condition = "若出现官方负面公告、放量跌破关键均线或组合权重继续升高，转为分批减仓评估。"
        rationale = "已有监控信号值得关注，但不足以支持净加仓；先避免在噪音里扩大风险。"
        main_risk = "等待确认可能错过早期反弹，也可能避免错误摊低成本。"
        next_decision_point = "下一次完成交易日数据、公告同步、或 Missing Inputs 补齐后复查。"
        lot_quantity_range = "今日不动作；如恶化可评估100股起分批调整"
        summary_line = "今日主姿态是等待确认；有信号但证据不够，不扩大仓位。"
        action_steps = [
            "今日不主动加仓；等待收盘、量能和公告给出确认。",
            "若下一完成交易日继续弱于市场/同业并放量，评估 100 股起的分批减仓。",
            "若价格修复且 Missing/Stale 缺口不恶化，再重新评估持有或条件式加仓。",
        ]
        risk_controls = [
            "把成本价当作心理压力位，不当作补仓理由。",
            "盘中波动只作提示，正式动作优先看完成日确认。",
            f"数据边界为 {data_gap_text}，缺口越多，动作越保守。",
        ]
        decision_checklist = ["完成日涨跌幅是否仍 ≥4%", "成交量是否异常", "市场天气是否 Risk-off", "官方公告是否有新增高/中重要事项"]
    elif high_concentration:
        posture = "持有"
        severity = "watch"
        urgency = "monitor_concentration"
        trigger_condition = "持仓可继续观察，但组合权重已偏高，不建议主动净加仓。"
        invalidation_condition = "若市场转 Risk-off、技术破位、或基本面证据转弱，则升级为分批减仓。"
        rationale = "目前没有强触发，但集中度本身限制容错率。"
        main_risk = "单一标的波动对组合净值影响较大。"
        next_decision_point = "等待下一次技术/公告/行业数据确认。"
        lot_quantity_range = "今日不动作"
        summary_line = "持有但不加仓；核心任务是监控集中度和下一证据。"
        action_steps = [
            "维持现有仓位，不主动净加仓。",
            "若组合权重继续升高或出现破位/负面公告，转入分批减仓评估。",
        ]
        risk_controls = ["单票权重偏高时，任何加仓都需要同时满足市场、技术、基本面三类确认。"]
        decision_checklist = ["仓位权重是否下降到舒适区", "技术信号是否转弱", "行业核心证据是否改善"]
    elif (
        not weak_market
        and not data_quality_poor
        and valuation_available
        and technical_status == "Available"
        and position.shares > 0
    ):
        posture = "条件式加仓"
        severity = "watch"
        urgency = "conditional_only"
        trigger_condition = "仅在市场天气不偏冷、技术确认向上且无新增负面公告时考虑。"
        invalidation_condition = "若跌破近期关键支撑、出现负面公告或 Missing Inputs 增多，则取消加仓。"
        rationale = "行情、估值和技术数据均可得时，允许小额、条件式而非摊低式加仓。"
        main_risk = "规则未覆盖完整基本面和行业景气，需防止把短期反弹误判为趋势。"
        next_decision_point = "下一完成交易日收盘价、量能和官方公告更新。"
        lot_quantity_range = f"{add_lot}股"
        summary_line = f"只允许小额条件式加仓；满足确认后最多 {lot_quantity_range}，不是因为亏损而摊平。"
        action_steps = [
            "只有在市场天气不偏冷、价格/量能确认向上且无新增负面公告时，才考虑小额加仓。",
            f"单次加仓上限 {lot_quantity_range}；执行后必须重新计算组合权重。",
            "若任一确认条件失效，取消加仓。",
        ]
        risk_controls = ["不同时对多个高相关股票加仓。", "不把短线反弹自动视为基本面修复。"]
        decision_checklist = ["市场天气是否非 Risk-off", "估值和技术数据是否可靠", "是否无新增负面公告", "加仓后组合权重是否仍可接受"]
    else:
        posture = "持有"
        severity = "watch"
        urgency = "routine_watch"
        trigger_condition = "没有出现必须调整仓位的强触发。"
        invalidation_condition = "若新增负面公告、市场转弱、放量跌破关键技术位或数据质量恶化，重新评估。"
        rationale = "当前证据不足以支持主动交易；持有不是永久持有，而是等下一证据。"
        main_risk = "如果关键基本面数据滞后，持有判断可能反应偏慢。"
        next_decision_point = "下一交易日收盘、公告同步或行业专属指标更新。"
        lot_quantity_range = "今日不动作"
        summary_line = "持有观察；今天不是交易信号，而是等待下一条能改变判断的证据。"
        action_steps = [
            "维持仓位，不主动交易。",
            "继续跟踪下一完成交易日价格/量能、官方公告和行业核心指标。",
        ]
        risk_controls = ["若 Missing/Stale 增多或市场转弱，操作建议自动趋向保守。"]
        decision_checklist = ["是否出现新公告", "是否触发 ≥4% 波动或放量", "行业核心指标是否更新"]

    return {
        "posture": posture,
        "severity": severity,
        "urgency": urgency,
        "summary_line": summary_line,
        "position_summary": _position_summary(position, latest_price, distance_to_cost),
        "position_pct": round(position_pct, 2) if position_pct is not None else None,
        "trigger_condition": trigger_condition,
        "invalidation_condition": invalidation_condition,
        "rationale": rationale,
        "main_risk": main_risk,
        "next_decision_point": next_decision_point,
        "lot_quantity_range": lot_quantity_range,
        "action_steps": action_steps,
        "risk_controls": risk_controls,
        "decision_checklist": decision_checklist,
        "do_not": [
            "不自动执行交易。",
            "不因低于成本价而机械摊低成本。",
            "不使用 Missing/Stale 字段编造替代值。",
        ],
        "inputs": _common_inputs(
            weather=weather,
            change_pct=change_pct,
            volume_ratio=volume_ratio,
            technical_status=technical_status,
            technical_signal=technical_signal,
            stale_count=stale_count,
            missing_count=missing_count,
            valuation_status=str(valuation.get("status") or "Missing"),
        ),
    }
