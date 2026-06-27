from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.config import get_settings
from app.services.data_quality import missing_input, source_warning
from app.services.market_data import fetch_chinamoney_gov_yield, fetch_sina_fx_quote, fetch_sina_hk_stock_quote, fetch_sina_quotes
from app.services.symbols import normalize_symbol


ProviderResult = Dict[str, Any]
ProviderRow = Dict[str, Any]
CustomMetric = Dict[str, Any]


def _fmt_pct(value: object) -> str:
    if value is None:
        return "不可靠可得"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "不可靠可得"


def _fmt_number(value: object) -> str:
    if value is None:
        return "不可靠可得"
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "不可靠可得"


def _fmt_value(value: object, unit: object = "") -> str:
    text = _fmt_number(value)
    unit_text = str(unit or "").strip()
    return f"{text}{unit_text}" if unit_text else text


def _row(
    *,
    metric: str,
    status: str,
    latest_reading: str,
    as_of: str,
    source: str,
    relevance: str,
    next_evidence: str,
    source_url: str = "",
    provider: str = "",
    raw: Dict[str, Any] | None = None,
) -> ProviderRow:
    return {
        "metric": metric,
        "status": status,
        "latest_reading": latest_reading,
        "as_of": as_of,
        "source": source,
        "source_url": source_url,
        "relevance": relevance,
        "next_evidence": next_evidence,
        "provider": provider or source,
        "raw": raw or {},
    }


def _empty_result(industry: str) -> ProviderResult:
    return {
        "industry": industry,
        "status": "NotConfigured",
        "rows": [],
        "summary_lines": [],
        "missing_inputs": [],
        "warnings": [],
        "coverage": {"available": 0, "partial": 0, "missing": 0, "total": 0},
    }


def _finalize(industry: str, symbol: str, rows: List[ProviderRow], missing: List[Dict[str, Any]], warnings: List[Dict[str, Any]]) -> ProviderResult:
    available = [row for row in rows if row.get("status") == "Available"]
    partial = [row for row in rows if row.get("status") == "Partial"]
    missing_rows = [row for row in rows if row.get("status") == "Missing"]
    return {
        "industry": industry,
        "status": "Available" if available or partial else "Missing",
        "rows": rows,
        "summary_lines": [
            f"{row.get('metric')}：{row.get('latest_reading')}｜{row.get('as_of')}"
            for row in (available + partial)[:6]
        ],
        "missing_inputs": [*missing, *[_missing_from_row(row, symbol) for row in missing_rows]],
        "warnings": warnings,
        "coverage": {
            "available": len(available),
            "partial": len(partial),
            "missing": len(missing_rows),
            "total": len(rows),
        },
    }


def _missing_from_row(row: ProviderRow, symbol: str) -> Dict[str, Any]:
    return missing_input(
        str(row.get("metric") or "行业 provider"),
        str(row.get("source") or row.get("provider") or "configured industry provider"),
        str(row.get("relevance") or "限制行业证据判断。"),
        company=symbol,
        attempted_source=str(row.get("provider") or row.get("source") or ""),
        next_source=str(row.get("next_evidence") or row.get("source") or ""),
        source_url=str(row.get("source_url") or ""),
    )


def _find_sector_items(market_weather: Dict[str, Any], keywords: Iterable[str]) -> List[Dict[str, Any]]:
    sector_weather = market_weather.get("sector_weather") if isinstance(market_weather.get("sector_weather"), dict) else {}
    buckets = [
        sector_weather.get("sectors") or [],
        sector_weather.get("top_gainers") or [],
        sector_weather.get("top_losers") or [],
        sector_weather.get("top_inflows") or [],
        sector_weather.get("top_outflows") or [],
    ]
    result: List[Dict[str, Any]] = []
    seen = set()
    for bucket in buckets:
        for item in bucket:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not name or not any(keyword in name for keyword in keywords):
                continue
            key = item.get("code") or name
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _commodity_rows(market_weather: Dict[str, Any]) -> List[ProviderRow]:
    commodities = [item for item in (market_weather.get("commodities") or []) if isinstance(item, dict)]
    copper_items = [
        item
        for item in commodities
        if str(item.get("symbol") or "") in {"CAD", "HG=F"} or "铜" in str(item.get("name") or "").lower() or "copper" in str(item.get("name") or "").lower()
    ]
    if not copper_items:
        return []
    reading = "；".join(
        f"{item.get('name') or item.get('symbol')} {_fmt_number(item.get('current'))}，{_fmt_pct(item.get('change_pct'))}"
        for item in copper_items[:3]
    )
    latest_time = next((str(item.get("timestamp") or "") for item in copper_items if item.get("timestamp")), "")
    source = "；".join(sorted({str(item.get("source") or "secondary commodity quote") for item in copper_items}))
    return [
        _row(
            metric="铜价/商品价格 provider",
            status="Partial",
            latest_reading=f"{reading}；未含同一时间戳库存、现货升贴水和期限结构。",
            as_of=latest_time,
            source=source,
            relevance="铜价是铜链收入和情绪变量，但单独不能替代 TC/RC、库存、升贴水、产量和成本。",
            next_evidence="接入 SHFE/LME/COMEX 库存、现货升贴水、期限结构、进口盈亏和可靠 TC/RC。",
            provider=source,
            raw={"commodities": copper_items},
        )
    ]


async def _peer_quote_row(symbols: List[str], *, metric: str, relevance: str) -> ProviderRow | None:
    normalized = [normalize_symbol(symbol) for symbol in symbols]
    quotes = await fetch_sina_quotes(normalized)
    if not quotes:
        return None
    parts = []
    latest_time = ""
    for symbol in symbols:
        quote = quotes.get(normalize_symbol(symbol).symbol)
        if not quote:
            continue
        parts.append(f"{quote.get('name') or symbol} {_fmt_pct(quote.get('change_pct'))}")
        latest_time = latest_time or str(quote.get("timestamp") or "")
    if not parts:
        return None
    return _row(
        metric=metric,
        status="Available",
        latest_reading="；".join(parts[:6]),
        as_of=latest_time,
        source="Sina secondary quote",
        relevance=relevance,
        next_evidence="对照公司完成日涨跌幅、估值和公告事件，判断是个股问题还是行业/市场共同波动。",
        provider="Sina secondary quote",
        raw={"symbols": symbols},
    )


async def build_industry_provider_context(industry: str, symbol: str, market_weather: Dict[str, Any]) -> ProviderResult:
    if industry == "有色/矿业":
        return await _build_nonferrous_provider(industry, symbol, market_weather)
    if industry == "保险":
        return await _build_insurance_provider(industry, symbol, market_weather)
    return _empty_result(industry)


async def _build_nonferrous_provider(industry: str, symbol: str, market_weather: Dict[str, Any]) -> ProviderResult:
    rows: List[ProviderRow] = []
    missing: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    rows.extend(_commodity_rows(market_weather))
    custom_metrics = _load_custom_copper_chain_metrics()
    sector_items = _find_sector_items(market_weather, ["有色", "金属", "铜", "铝", "锌", "锂", "能源金属"])
    if sector_items:
        rows.append(
            _row(
                metric="有色/铜链板块温度 provider",
                status="Available",
                latest_reading="；".join(
                    f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}，主力净流入 {_fmt_number(item.get('main_net_inflow'))}"
                    for item in sector_items[:5]
                ),
                as_of=str(((market_weather.get("sector_weather") or {}) if isinstance(market_weather.get("sector_weather"), dict) else {}).get("timestamp") or ""),
                source="Eastmoney secondary sector board list",
                relevance="板块温度用于区分个股下跌是公司特有风险、铜链共振还是全市场风险偏好变化。",
                next_evidence="接入更细的申万/中信行业指数、北向/两融、主要铜矿和冶炼同行对比。",
                provider="Eastmoney secondary sector board list",
                raw={"sector_items": sector_items},
            )
        )
    else:
        warnings.append(
            source_warning(
                "有色/铜链板块温度 provider",
                "未在行业涨跌/资金流榜单中匹配到有色铜链板块，板块共振判断精度下降。",
                attempted_source="Eastmoney secondary sector board list",
                next_source="配置申万/中信有色指数或铜链自定义股票池",
            )
        )

    rows.append(_custom_tc_rc_row(custom_metrics))
    rows.append(_custom_physical_copper_row(custom_metrics))
    return _finalize(industry, symbol, rows, missing, warnings)


def _load_custom_copper_chain_metrics() -> Dict[str, CustomMetric]:
    path = Path(get_settings().industry_provider_data_dir) / "copper_chain.csv"
    if not path.exists():
        return {}
    rows: Dict[str, CustomMetric] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw in reader:
                metric = str(raw.get("metric") or "").strip()
                if not metric:
                    continue
                value = _float_or_none(raw.get("value"))
                if value is None:
                    continue
                item: CustomMetric = {
                    "metric": metric,
                    "as_of": str(raw.get("as_of") or "").strip(),
                    "value": value,
                    "unit": str(raw.get("unit") or "").strip(),
                    "source": str(raw.get("source") or "User supplied copper_chain.csv").strip(),
                    "source_url": str(raw.get("source_url") or "").strip(),
                    "note": str(raw.get("note") or "").strip(),
                    "file": str(path),
                }
                existing = rows.get(metric)
                if existing is None or str(item.get("as_of") or "") >= str(existing.get("as_of") or ""):
                    rows[metric] = item
    except Exception:
        return {}
    return rows


def _custom_tc_rc_row(metrics: Dict[str, CustomMetric]) -> ProviderRow:
    tc = metrics.get("tc_rc") or metrics.get("tc") or metrics.get("tcrc")
    rc = metrics.get("rc")
    if tc:
        parts = [f"TC/RC {_fmt_value(tc.get('value'), tc.get('unit'))}"]
        if rc:
            parts.append(f"RC {_fmt_value(rc.get('value'), rc.get('unit'))}")
        note = str(tc.get("note") or "")
        if note:
            parts.append(note)
        return _row(
            metric="TC/RC 外部报价 provider",
            status="Available",
            latest_reading="；".join(parts),
            as_of=str(tc.get("as_of") or ""),
            source=str(tc.get("source") or "User supplied copper_chain.csv"),
            source_url=str(tc.get("source_url") or ""),
            relevance="TC/RC 是外购矿冶炼利润核心变量；自定义数据源可用于补齐公开免费源缺口，但仍需核对授权和口径。",
            next_evidence="继续维护同一口径的 spot/benchmark TC/RC，并与公司采购结构、冶炼毛利和产量验证。",
            provider="CustomProvider copper_chain.csv",
            raw={"tc": tc, "rc": rc or {}},
        )
    return _row(
        metric="TC/RC 外部报价 provider",
        status="Missing",
        latest_reading="不可靠可得",
        as_of="",
        source="可靠现货/季度/长单 TC/RC provider 或 data/industry_providers/copper_chain.csv",
        relevance="TC/RC 是外购矿冶炼利润核心变量，缺失时不能判断冶炼利润是否继续压缩。",
        next_evidence="配置 Fastmarkets/Benchmark/公司披露/用户自带 TC-RC 数据源；或在 copper_chain.csv 填写 metric=tc_rc。",
        provider="industry provider v1.2",
    )


def _custom_physical_copper_row(metrics: Dict[str, CustomMetric]) -> ProviderRow:
    keys = ["lme_inventory", "shfe_inventory", "comex_inventory", "bonded_inventory", "shfe_spot_premium", "spot_premium", "curve_spread", "import_profit"]
    available = [metrics[key] for key in keys if key in metrics]
    if available:
        label_map = {
            "lme_inventory": "LME库存",
            "shfe_inventory": "SHFE库存",
            "comex_inventory": "COMEX库存",
            "bonded_inventory": "保税区库存",
            "shfe_spot_premium": "上海现货升贴水",
            "spot_premium": "现货升贴水",
            "curve_spread": "期限价差",
            "import_profit": "进口盈亏",
        }
        parts = [
            f"{label_map.get(str(item.get('metric')), str(item.get('metric')))} {_fmt_value(item.get('value'), item.get('unit'))}"
            for item in available
        ]
        latest = max(available, key=lambda item: str(item.get("as_of") or ""))
        sources = sorted({str(item.get("source") or "User supplied copper_chain.csv") for item in available})
        return _row(
            metric="SHFE/LME/COMEX 库存/升贴水 provider",
            status="Available" if len(available) >= 3 else "Partial",
            latest_reading="；".join(parts),
            as_of=str(latest.get("as_of") or ""),
            source="；".join(sources),
            source_url=str(latest.get("source_url") or ""),
            relevance="库存、升贴水和期限结构解释铜价与股价、TC/RC、进口盈亏之间的背离；自定义数据需保持时间戳和口径可比。",
            next_evidence="持续补齐 LME/SHFE/COMEX 库存、现货升贴水、期限结构和进口盈亏，尽量使用同一截止时间。",
            provider="CustomProvider copper_chain.csv",
            raw={"metrics": available},
        )
    return _row(
        metric="SHFE/LME/COMEX 库存/升贴水 provider",
        status="Missing",
        latest_reading="不可靠可得",
        as_of="",
        source="SHFE/LME/COMEX official/licensed provider 或 data/industry_providers/copper_chain.csv",
        relevance="库存、升贴水和期限结构解释铜价与股价、TC/RC、进口盈亏之间的背离。",
        next_evidence="在 copper_chain.csv 填写 lme_inventory、shfe_inventory、comex_inventory、shfe_spot_premium 等指标，或接入正式数据源。",
        provider="industry provider v1.2",
    )


async def _build_insurance_provider(industry: str, symbol: str, market_weather: Dict[str, Any]) -> ProviderResult:
    rows: List[ProviderRow] = []
    missing: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    peer_row = await _peer_quote_row(
        ["601628.SH", "601318.SH", "601601.SH", "601319.SH"],
        metric="保险同业表现 provider",
        relevance="同业表现帮助判断新华保险波动来自个股公告、保险板块、利率/权益市场，还是全市场风险偏好。",
    )
    if peer_row:
        rows.append(peer_row)
    else:
        warnings.append(
            source_warning(
                "保险同业表现 provider",
                "保险同业行情暂不可得，A股保险板块相对强弱判断受限。",
                attempted_source="Sina secondary quote",
                next_source="重试 Sina quote 或配置保险同业行情 provider",
            )
        )

    sector_items = _find_sector_items(market_weather, ["保险"])
    if sector_items:
        rows.append(
            _row(
                metric="保险板块温度 provider",
                status="Available",
                latest_reading="；".join(
                    f"{item.get('name')} {_fmt_pct(item.get('change_pct'))}，主力净流入 {_fmt_number(item.get('main_net_inflow'))}"
                    for item in sector_items[:3]
                ),
                as_of=str(((market_weather.get("sector_weather") or {}) if isinstance(market_weather.get("sector_weather"), dict) else {}).get("timestamp") or ""),
                source="Eastmoney secondary sector board list",
                relevance="保险板块资金和涨跌幅用于验证新华保险是否与行业共振或出现异常背离。",
                next_evidence="接入保险指数、A/H 溢价和更完整同业估值。",
                provider="Eastmoney secondary sector board list",
                raw={"sector_items": sector_items},
            )
        )
    else:
        warnings.append(
            source_warning(
                "保险板块温度 provider",
                "行业榜单中未匹配到保险板块，板块共振判断精度下降。",
                attempted_source="Eastmoney secondary sector board list",
                next_source="配置保险行业指数或同业股票池",
            )
        )

    rows.append(await _insurance_rate_row())
    rows.append(await _insurance_ah_premium_row(symbol))
    return _finalize(industry, symbol, rows, missing, warnings)


async def _insurance_rate_row() -> ProviderRow:
    try:
        data = await fetch_chinamoney_gov_yield()
        ten_year = data.get("ten_year_yield")
        one_year = data.get("one_year_yield")
        return _row(
            metric="中国10年国债收益率 provider",
            status="Available",
            latest_reading=f"10年期国债收益率 {_fmt_pct(ten_year)}；1年期 {_fmt_pct(one_year)}；曲线期限利差约 {_fmt_number((ten_year - one_year) if isinstance(ten_year, (int, float)) and isinstance(one_year, (int, float)) else None)} 个百分点",
            as_of=str(data.get("date") or data.get("timestamp") or ""),
            source=str(data.get("source") or "ChinaMoney official public government bond yield history"),
            source_url=str(data.get("source_url") or ""),
            relevance="长期利率影响保险负债折现、再投资压力、EV/估值和资产端收益预期。",
            next_evidence="继续跟踪10年国债收益率的日/周变化，并与保险股估值、投资收益率、OCI 和偿付能力交叉验证。",
            provider="ChinaMoney official public government bond yield history",
            raw=data,
        )
    except Exception as exc:
        return _row(
            metric="中国10年国债收益率 provider",
            status="Missing",
            latest_reading="不可靠可得",
            as_of="",
            source="ChinaMoney official public government bond yield history",
            relevance=f"长期利率影响保险负债折现、再投资压力、EV/估值和资产端收益预期；本次读取失败：{exc}",
            next_evidence="重试中国货币网政府债券利率历史数据，或配置中债/上清所/可靠行情 provider。",
            provider="industry provider v1.1",
            source_url="https://www.chinamoney.com.cn/chinese/sddsintigy/",
        )


def _hk_peer_code(symbol: str) -> str:
    return {
        "601336.SH": "01336",
        "601628.SH": "02628",
        "601318.SH": "02318",
        "601601.SH": "02601",
        "601319.SH": "01339",
    }.get(symbol, "")


async def _insurance_ah_premium_row(symbol: str) -> ProviderRow:
    hk_code = _hk_peer_code(symbol)
    if not hk_code:
        return _row(
            metric="A/H 溢价与 H 股价格 provider",
            status="Missing",
            latest_reading="不可靠可得",
            as_of="",
            source="A/H 同步行情与 FX provider",
            relevance="未配置该股票 H 股映射，无法计算 A/H 溢价。",
            next_evidence="补充该 A 股对应 H 股代码映射，并接入 HKD/CNY 汇率。",
            provider="industry provider v1.1",
        )
    try:
        normalized = normalize_symbol(symbol)
        a_quote_map = await fetch_sina_quotes([normalized])
        a_quote = a_quote_map.get(normalized.symbol) or {}
        hk_quote = await fetch_sina_hk_stock_quote(hk_code)
        fx_quote = await fetch_sina_fx_quote("fx_shkdcny")
        a_price = _float_or_none(a_quote.get("current"))
        h_price = _float_or_none(hk_quote.get("current"))
        hkd_cny = _float_or_none(fx_quote.get("current"))
        if a_price is None or h_price is None or hkd_cny is None or h_price <= 0 or hkd_cny <= 0:
            raise ValueError("A/H price or HKD/CNY FX missing")
        h_cny = h_price * hkd_cny
        premium_pct = (a_price / h_cny - 1) * 100 if h_cny else None
        a_time = str(a_quote.get("timestamp") or "")
        h_time = str(hk_quote.get("timestamp") or "")
        fx_time = str(fx_quote.get("timestamp") or "")
        same_day = _date_part(a_time) == _date_part(h_time) == _date_part(fx_time)
        status = "Available" if same_day else "Partial"
        return _row(
            metric="A/H 溢价与 H 股价格 provider",
            status=status,
            latest_reading=(
                f"A股 ¥{a_price:.2f} @ {a_time}；H股 HK${h_price:.2f} @ {h_time}；"
                f"HKD/CNY {hkd_cny:.4f} @ {fx_time}；H股折人民币约 ¥{h_cny:.2f}；"
                f"A/H 溢价约 {_fmt_pct(premium_pct)}"
                + ("。" if same_day else "；时间戳非完全同日/同刻，作为近似比较。")
            ),
            as_of=" / ".join(item for item in [a_time, h_time, fx_time] if item),
            source="Sina secondary A/H stock quote + Sina secondary FX quote",
            relevance="A/H 溢价帮助识别两地资金和估值差异；保险股需结合利率、权益市场和公司 EV/NBV 变化验证。",
            next_evidence="使用同一完成交易日的 A/H 收盘价与 HKD/CNY 汇率复核溢价变化，并对比历史区间。",
            provider="Sina secondary A/H stock quote + FX",
            raw={"a_quote": a_quote, "hk_quote": hk_quote, "fx_quote": fx_quote, "premium_pct": premium_pct},
        )
    except Exception as exc:
        return _row(
            metric="A/H 溢价与 H 股价格 provider",
            status="Missing",
            latest_reading="不可靠可得",
            as_of="",
            source="A/H 同步行情与 FX provider",
            relevance=f"A/H 溢价帮助识别两地资金和估值差异；本次读取失败：{exc}",
            next_evidence="重试 Sina A/H 行情和 HKD/CNY 汇率，或配置正式港股/汇率 provider。",
            provider="industry provider v1.1",
        )


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _date_part(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value.split(" ", 1)[0].replace("/", "-")


def merge_provider_rows(mapped_rows: List[ProviderRow], provider_rows: List[ProviderRow]) -> List[ProviderRow]:
    """Merge provider rows into filing-derived rows without hiding better evidence."""

    result = [dict(row) for row in mapped_rows]
    for provider_row in provider_rows:
        provider_status = str(provider_row.get("status") or "")
        provider_metric = str(provider_row.get("metric") or "")
        merged = False
        for index, existing in enumerate(result):
            existing_metric = str(existing.get("metric") or "")
            existing_status = str(existing.get("status") or "")
            if not _metrics_overlap(existing_metric, provider_metric):
                continue
            if existing_status == "Missing" and provider_status in {"Available", "Partial"}:
                result[index] = provider_row
                merged = True
                break
            if existing_status in {"Available", "Partial"} and provider_status == "Missing":
                merged = True
                break
        if not merged:
            result.append(provider_row)
    return result


def _metrics_overlap(existing_metric: str, provider_metric: str) -> bool:
    groups = [
        ["铜价", "库存", "升贴水", "商品价格", "SHFE", "LME", "COMEX"],
        ["TC/RC"],
        ["保险同业", "保险板块", "同业"],
        ["中国10年国债", "利率", "收益率"],
        ["A/H", "H 股"],
    ]
    for group in groups:
        if any(keyword in existing_metric for keyword in group) and any(keyword in provider_metric for keyword in group):
            return True
    return existing_metric == provider_metric
