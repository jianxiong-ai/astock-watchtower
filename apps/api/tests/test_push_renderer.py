from app.schemas import AnalyzeResponse, PositionOut
from app.services.push_renderer import build_feishu_report_card, render_subscription_message


def _analysis() -> AnalyzeResponse:
    return AnalyzeResponse(
        symbol="600362.SH",
        name="江西铜业",
        exchange="SH",
        industry="有色/矿业",
        data_mode="completed_session",
        decision="NOTIFY",
        market_weather={
            "classification": "Risk-off",
            "as_of": "2026-06-26T15:30:00+08:00",
            "indices": [
                {
                    "symbol": "000001.SH",
                    "name": "上证指数",
                    "current": 4048.54,
                    "change_pct": -1.74,
                    "timestamp": "2026-06-26 15:00:00",
                }
            ],
            "breadth": {
                "up": 1000,
                "down": 4112,
                "flat": 20,
                "limit_up": 12,
                "limit_down": 35,
                "rising_ratio": 19.5,
                "total_amount": 1_790_000_000_000,
                "timestamp": "2026-06-26T15:30:00+08:00",
                "source": "Eastmoney secondary A-share quote list",
            },
            "sector_weather": {
                "up": 80,
                "down": 380,
                "rising_ratio": 17.4,
                "timestamp": "2026-06-26T15:30:00+08:00",
                "source": "Eastmoney secondary sector board list",
                "top_gainers": [{"name": "有机硅", "change_pct": 4.72, "main_net_inflow": 194_891_264}],
                "top_losers": [{"name": "保险", "change_pct": -4.11, "main_net_inflow": -800_000_000}],
                "top_inflows": [{"name": "硅料硅片", "change_pct": 4.28, "main_net_inflow": 1_352_000_000}],
                "top_outflows": [{"name": "保险", "change_pct": -4.11, "main_net_inflow": -800_000_000}],
            },
            "limitations": ["北向/两融尚未稳定接入。"],
        },
        snapshot={
            "price": 45.43,
            "previous_close": 47.33,
            "change_pct": -4.01,
            "high": 46.08,
            "low": 42.20,
            "amount": 3351968787,
            "timestamp": "2026-06-25 15:00:00",
            "source": "Eastmoney secondary historical kline",
        },
        universal_indicators={
            "valuation": {
                "status": "Available",
                "market_cap": 150_900_000_000,
                "float_market_cap": 89_790_000_000,
                "pe_dynamic": 18.9,
                "pb": 1.79,
                "turnover_pct": 3.7,
            },
            "technicals": {
                "status": "Available",
                "ma": {"ma5": 50.06, "ma10": 47.58, "ma20": 45.73, "ma60": 45.67, "ma120": 50.16},
                "rsi14": 49.05,
                "high_low": {"high_20": 55.17, "low_20": 39.59, "high_60": 55.17, "low_60": 39.59},
                "recent_peak_drawdown_pct": -17.64,
                "volume_ratio_to_ma20": 1.32,
                "signals": ["单日涨跌幅达到 -4.01%"],
            },
        },
        sector_indicators={
            "mapped_metrics": [
                {
                    "metric": "TC/RC",
                    "status": "Missing",
                    "latest_reading": "不可靠可得",
                    "as_of": "",
                    "relevance": "缺少冶炼利润核心变量。",
                    "next_evidence": "可靠行业数据源或公司披露",
                }
            ]
        },
        events=[
            {
                "title": "江西铜业股份有限公司2026年第一季度报告",
                "type": "定期报告",
                "published_at": "2026-04-28T08:41:18+08:00",
                "affected_layers": "现金流/资本开支、成本/毛利、产量/资源自给",
                "url": "https://www.sse.com.cn/example.pdf",
            }
        ],
        stale_sources=[{"metric": "行业特有非公告数据", "impact": "限制行业判断", "attempted_source": "MVP provider"}],
        missing_inputs=[{"metric": "TC/RC", "impact": "无法判断冶炼利润", "preferred_source": "可靠行业数据源"}],
        research_posture={},
        report_sections=[],
        sources=[],
    )


def _position() -> PositionOut:
    return PositionOut(
        symbol="600362.SH",
        shares=1800,
        average_cost=50.055,
        cost_basis=90099.0,
        realized_pnl=5438.05,
        total_buy_amount=100000.0,
        total_sell_amount=0.0,
        total_fees=100.0,
        latest_price=45.43,
        latest_price_time="2026-06-25 15:00:00",
        market_value=81774.0,
        unrealized_pnl=-8325.0,
        unrealized_pnl_pct=-9.24,
        total_pnl=-2886.95,
        source="Eastmoney secondary historical kline",
    )


def test_subscription_message_uses_research_brief_contract():
    message = render_subscription_message(
        analysis=_analysis(),
        position=_position(),
        trigger_summary="股价单日变动 -4.01%；市场天气 Risk-off",
        calendar_source="上交所交易日历：交易日",
        calendar_warning="",
        portfolio_market_value=200000.0,
    )

    assert "晨会摘要" in message
    assert "今日只看 3 件事" in message
    assert "操作纪律" in message
    assert "详细证据层" in message
    assert "1. 交易日与市场温度" in message
    assert "A股市场宽度" in message
    assert "行业温度" in message
    assert "2. 触发总览" in message
    assert "A. 市场快照" in message
    assert "B. 六组核心骨架" in message
    assert "C. 解释与验证链" in message
    assert "F. 持仓与操作建议" in message
    assert "最新已完成交易日" in message
    assert "2026-06-25 15:00:00" in message
    assert "Stable-on-latest-disclosure" in message
    assert "已有官方定期报告" in message


def test_feishu_card_uses_same_contract_content():
    card = build_feishu_report_card(
        analysis=_analysis(),
        position=_position(),
        trigger_summary="股价单日变动 -4.01%；市场天气 Risk-off",
        calendar_source="上交所交易日历：交易日",
        calendar_warning="",
        portfolio_market_value=200000.0,
    )

    content = "\n".join(element.get("content", "") for element in card["elements"] if element.get("tag") == "markdown")
    assert "晨会摘要" in content
    assert "今日只看 3 件事" in content
    assert "B. 六组核心骨架" in content
    assert card["header"]["template"] == "red"
