from app.schemas import AnalyzeResponse, PositionOut
from app.services.action_advice import build_position_action_advice


def _analysis(
    *,
    weather: str = "Neutral",
    change_pct: float = 0.0,
    volume_ratio: float = 1.0,
    stale_count: int = 0,
    missing_count: int = 0,
) -> AnalyzeResponse:
    return AnalyzeResponse(
        symbol="600519.SH",
        name="贵州茅台",
        exchange="SH",
        industry="白酒",
        data_mode="test",
        decision="DONT_NOTIFY",
        market_weather={"classification": weather, "as_of": "2026-06-26T15:00:00+08:00"},
        snapshot={"price": 80.0, "change_pct": change_pct, "timestamp": "2026-06-26T15:00:00+08:00"},
        universal_indicators={
            "valuation": {"status": "Available"},
            "technicals": {"status": "Available", "volume_ratio_to_ma20": volume_ratio, "signals": []},
        },
        sector_indicators={},
        events=[],
        stale_sources=[{"metric": f"stale-{index}"} for index in range(stale_count)],
        missing_inputs=[{"metric": f"missing-{index}"} for index in range(missing_count)],
        research_posture={},
        report_sections=[],
        sources=[],
    )


def _position() -> PositionOut:
    return PositionOut(
        symbol="600519.SH",
        shares=1000,
        average_cost=100.0,
        cost_basis=100000.0,
        realized_pnl=0.0,
        total_buy_amount=100000.0,
        total_sell_amount=0.0,
        total_fees=0.0,
        latest_price=80.0,
        latest_price_time="2026-06-26T15:00:00+08:00",
        market_value=80000.0,
        unrealized_pnl=-20000.0,
        unrealized_pnl_pct=-20.0,
        total_pnl=-20000.0,
        source="test",
    )


def test_action_advice_recommends_staged_trim_for_concentrated_risk_off_loss():
    advice = build_position_action_advice(
        _analysis(weather="Risk-off"),
        _position(),
        portfolio_market_value=160000.0,
    )

    assert advice["posture"] == "分批减仓"
    assert advice["severity"] == "medium"
    assert advice["position_pct"] == 50.0
    assert "100" in advice["lot_quantity_range"]
    assert advice["summary_line"]
    assert advice["action_steps"]
    assert advice["risk_controls"]
    assert "摊低成本" in "；".join(advice["do_not"])


def test_action_advice_waits_when_no_position_baseline():
    advice = build_position_action_advice(_analysis(), None)

    assert advice["posture"] == "等待确认"
    assert advice["position_pct"] is None
    assert "暂无持仓" in advice["position_summary"]
    assert advice["urgency"] == "setup_required"
    assert advice["action_steps"]
