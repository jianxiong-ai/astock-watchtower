from __future__ import annotations

from typing import Any


def _clean_line(line: str) -> str:
    return line.strip().lstrip("-• ").strip()


def summarize_push_message(message: str) -> dict[str, Any]:
    """Extract a compact preview from the human-readable push report.

    The report text is the durable source stored in push_logs. This helper keeps
    old logs compatible and avoids a database migration while letting the UI show
    the same "morning brief" contract used in Feishu pushes.
    """

    lines = [_clean_line(line) for line in (message or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return {
            "title": "",
            "conclusion": "",
            "market_line": "",
            "top_three": [],
            "action_line": "",
            "data_boundary": "",
            "has_morning_brief": False,
        }

    title = lines[0]
    has_morning_marker = any(line == "晨会摘要" for line in lines)
    conclusion = next((line for line in lines if line.startswith("结论：")), "")
    market_line = next((line for line in lines if line.startswith("市场温度：")), "")
    action_line = next((line for line in lines if line.startswith("操作纪律：")), "")
    data_boundary = next((line for line in lines if line.startswith("数据边界：")), "")

    top_three: list[str] = []
    in_top_three = False
    for line in lines:
        if line.startswith("今日只看 3 件事"):
            in_top_three = True
            continue
        if in_top_three and (line.startswith("操作纪律：") or line.startswith("详细证据层")):
            break
        if in_top_three:
            normalized = line
            if len(normalized) > 2 and normalized[0].isdigit() and normalized[1] in {".", "、"}:
                normalized = normalized[2:].strip()
            if normalized:
                top_three.append(normalized)
        if len(top_three) >= 3:
            break

    if not conclusion:
        conclusion = next((line for line in lines if "｜" in line and "NOTIFY" in line), "")
    if not top_three:
        top_three = [
            line
            for line in lines
            if line.startswith(("触发：", "价格：", "技术：", "公告：", "市场：", "持仓纪律：", "数据："))
        ][:3]

    return {
        "title": title,
        "conclusion": conclusion,
        "market_line": market_line,
        "top_three": top_three,
        "action_line": action_line,
        "data_boundary": data_boundary,
        "has_morning_brief": bool(has_morning_marker and (conclusion or top_three or action_line or data_boundary)),
    }
