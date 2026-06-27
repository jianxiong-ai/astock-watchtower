from typing import Any, Dict


def missing_input(
    metric: str,
    preferred_source: str,
    impact: str,
    *,
    company: str = "",
    last_known_date: str = "",
    attempted_source: str = "",
    next_source: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    return {
        "status": "Missing",
        "metric": metric,
        "company": company,
        "last_known_date": last_known_date,
        "attempted_source": attempted_source or preferred_source,
        "preferred_source": preferred_source,
        "impact": impact,
        "next_source": next_source or preferred_source,
        "source_url": source_url,
    }


def stale_source(
    metric: str,
    last_known_date: str,
    impact: str,
    *,
    company: str = "",
    attempted_source: str = "",
    preferred_source: str = "",
    next_source: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    return {
        "status": "Stale",
        "metric": metric,
        "company": company,
        "last_known_date": last_known_date,
        "attempted_source": attempted_source,
        "preferred_source": preferred_source or attempted_source,
        "impact": impact,
        "next_source": next_source or preferred_source or attempted_source,
        "source_url": source_url,
    }


def source_warning(
    metric: str,
    impact: str,
    *,
    company: str = "",
    last_known_date: str = "",
    attempted_source: str = "",
    preferred_source: str = "",
    next_source: str = "",
    source_url: str = "",
) -> Dict[str, Any]:
    return {
        "status": "Warning",
        "metric": metric,
        "company": company,
        "last_known_date": last_known_date,
        "attempted_source": attempted_source,
        "preferred_source": preferred_source or attempted_source,
        "impact": impact,
        "next_source": next_source or preferred_source or attempted_source,
        "source_url": source_url,
    }


def data_quality_line(item: Dict[str, Any]) -> str:
    pieces = [
        str(item.get("metric") or "未知指标"),
        str(item.get("status") or ""),
        str(item.get("last_known_date") or ""),
        str(item.get("impact") or ""),
    ]
    next_source = item.get("next_source") or item.get("preferred_source")
    if next_source:
        pieces.append(f"下一来源：{next_source}")
    return "｜".join(piece for piece in pieces if piece)
