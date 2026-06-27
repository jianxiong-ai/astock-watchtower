from app.services.push_log_summary import summarize_push_message


def test_summarize_push_message_extracts_morning_brief():
    message = """【A股订阅与分析】江西铜业（600362.SH）

晨会摘要
结论：江西铜业（600362.SH）｜NOTIFY｜等待确认（watch）｜最新已完成交易日 ¥42.39，涨跌幅 -6.69%。
市场温度：市场 Risk-off；A股上涨/下跌 897/4440，上涨占比 16.75%。
今日只看 3 件事：
1. 触发：股价单日变动 -6.69%
2. 技术：单日涨跌幅达到 -6.69%
3. 数据边界：Missing 8 项，Stale 1 项，只影响缺口相关结论
操作纪律：等待确认；触发条件：收盘确认；失效条件：放量收回。
数据边界：Missing 8 项，Stale 1 项；缺口不补值、不替代估算。

详细证据层
1. 交易日与市场温度
"""

    brief = summarize_push_message(message)

    assert brief["has_morning_brief"] is True
    assert brief["conclusion"].startswith("结论：江西铜业")
    assert brief["market_line"].startswith("市场温度：市场 Risk-off")
    assert brief["top_three"] == [
        "触发：股价单日变动 -6.69%",
        "技术：单日涨跌幅达到 -6.69%",
        "数据边界：Missing 8 项，Stale 1 项，只影响缺口相关结论",
    ]
    assert brief["action_line"].startswith("操作纪律：等待确认")
    assert brief["data_boundary"].startswith("数据边界：Missing 8 项")


def test_summarize_push_message_handles_empty_legacy_log():
    brief = summarize_push_message("")

    assert brief["has_morning_brief"] is False
    assert brief["top_three"] == []


def test_summarize_push_message_does_not_mislabel_old_market_section():
    message = """【A股订阅与分析】江西铜业（600362.SH）

交易日与市场温度
市场温度：Risk-off；风险分 -7；时间 2026-06-27T07:13:57。

触发总览
- high：手动发送分析推送。
"""

    brief = summarize_push_message(message)

    assert brief["market_line"].startswith("市场温度：Risk-off")
    assert brief["has_morning_brief"] is False
