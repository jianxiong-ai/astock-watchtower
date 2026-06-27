from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import httpx

from app.services.symbols import NormalizedSymbol


class MarketDataError(RuntimeError):
    pass


@dataclass
class DailyBar:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float
    amount: float
    change_pct: float


def _safe_float(value: object) -> Optional[float]:
    if value in {None, "-", ""}:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _eastmoney_secid(symbol: NormalizedSymbol) -> str:
    prefix = "1" if symbol.exchange == "SH" else "0"
    code = symbol.symbol.split(".", 1)[0]
    return f"{prefix}.{code}"


def _tencent_code(symbol: NormalizedSymbol) -> str:
    code = symbol.symbol.split(".", 1)[0]
    prefix = "sh" if symbol.exchange == "SH" else "sz"
    return f"{prefix}{code}"


def _parse_sina_line(code: str, payload: str) -> Optional[Dict[str, object]]:
    marker = f"var hq_str_{code}=\""
    if marker not in payload:
        return None
    raw = payload.split(marker, 1)[1].split("\";", 1)[0]
    fields = raw.split(",")
    if len(fields) < 32 or not fields[0]:
        return None

    previous_close = float(fields[2] or 0)
    current = float(fields[3] or 0)
    change_pct = ((current - previous_close) / previous_close * 100) if previous_close else 0.0
    timestamp = f"{fields[30]} {fields[31]}".strip()
    return {
        "name": fields[0],
        "open": float(fields[1] or 0),
        "previous_close": previous_close,
        "current": current,
        "high": float(fields[4] or 0),
        "low": float(fields[5] or 0),
        "bid": float(fields[6] or 0),
        "ask": float(fields[7] or 0),
        "volume_shares": int(float(fields[8] or 0)),
        "amount": float(fields[9] or 0),
        "timestamp": timestamp,
        "change_pct": change_pct,
        "source": "Sina secondary quote",
    }


def _extract_sina_raw(code: str, payload: str) -> str:
    marker = f"var hq_str_{code}=\""
    if marker not in payload:
        return ""
    return payload.split(marker, 1)[1].split("\";", 1)[0]


def _parse_sina_hk_index(code: str, payload: str) -> Optional[Dict[str, object]]:
    raw = _extract_sina_raw(code, payload)
    if not raw:
        return None
    fields = raw.split(",")
    if len(fields) < 18:
        return None
    current = _safe_float(fields[6])
    change_pct = _safe_float(fields[8])
    return {
        "symbol": fields[0] or code,
        "name": fields[1] or code,
        "current": current,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "timestamp": f"{fields[17]} {fields[18]}".strip() if len(fields) > 18 else fields[17],
        "source": "Sina secondary HK index",
    }


def _parse_sina_us_index(code: str, payload: str) -> Optional[Dict[str, object]]:
    raw = _extract_sina_raw(code, payload)
    if not raw:
        return None
    fields = raw.split(",")
    if len(fields) < 4:
        return None
    current = _safe_float(fields[1])
    change_pct = _safe_float(fields[2])
    return {
        "symbol": code.replace("gb_", ""),
        "name": fields[0] or code,
        "current": current,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "timestamp": fields[3],
        "source": "Sina secondary US index",
    }


def _parse_sina_global_future(code: str, payload: str) -> Optional[Dict[str, object]]:
    raw = _extract_sina_raw(code, payload)
    if not raw:
        return None
    fields = raw.split(",")
    if len(fields) < 15:
        return None
    current = _safe_float(fields[0])
    previous = _safe_float(fields[7]) or _safe_float(fields[8])
    change_pct = ((current - previous) / previous * 100) if current is not None and previous else None
    return {
        "symbol": code.replace("hf_", ""),
        "name": fields[13] or code,
        "current": current,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "timestamp": f"{fields[12]} {fields[6]}",
        "source": "Sina secondary global futures",
    }


def _parse_eastmoney_scaled(value: object, scale: float = 100.0) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    return number / scale


async def fetch_eastmoney_quote(symbol: NormalizedSymbol) -> Dict[str, object]:
    """Best-effort secondary quote/valuation provider.

    Eastmoney's quote API is not official exchange data. It is used only to enrich
    valuation fields; callers should treat failures as Missing Inputs.
    """

    fields = ",".join(
        [
            "f43",  # latest price * 100
            "f44",  # high * 100
            "f45",  # low * 100
            "f46",  # open * 100
            "f47",  # volume
            "f48",  # amount
            "f57",  # code
            "f58",  # name
            "f60",  # previous close * 100
            "f116",  # total market cap
            "f117",  # free float market cap
            "f162",  # PE dynamic * 100
            "f167",  # PB * 100
            "f168",  # turnover * 100
            "f170",  # change pct * 100
        ]
    )
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={_eastmoney_secid(symbol)}&fields={fields}"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    async with httpx.AsyncClient(timeout=10, headers=headers, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    if not data:
        raise MarketDataError(f"Eastmoney quote empty: {symbol.symbol}")
    return {
        "name": data.get("f58"),
        "price": _parse_eastmoney_scaled(data.get("f43")),
        "open": _parse_eastmoney_scaled(data.get("f46")),
        "high": _parse_eastmoney_scaled(data.get("f44")),
        "low": _parse_eastmoney_scaled(data.get("f45")),
        "previous_close": _parse_eastmoney_scaled(data.get("f60")),
        "change_pct": _parse_eastmoney_scaled(data.get("f170")),
        "volume": _safe_float(data.get("f47")),
        "amount": _safe_float(data.get("f48")),
        "market_cap": _safe_float(data.get("f116")),
        "float_market_cap": _safe_float(data.get("f117")),
        "pe_dynamic": _parse_eastmoney_scaled(data.get("f162")),
        "pb": _parse_eastmoney_scaled(data.get("f167")),
        "turnover_pct": _parse_eastmoney_scaled(data.get("f168")),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "source": "Eastmoney secondary quote/valuation",
    }


async def fetch_eastmoney_daily_bars(symbol: NormalizedSymbol, limit: int = 160) -> List[DailyBar]:
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={_eastmoney_secid(symbol)}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&beg=0&end=20500101&lmt={max(1, min(limit, 300))}"
    )
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
    async with httpx.AsyncClient(timeout=12, headers=headers, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    klines = data.get("klines") or []
    bars: List[DailyBar] = []
    for line in klines:
        fields = str(line).split(",")
        if len(fields) < 11:
            continue
        try:
            bars.append(
                DailyBar(
                    date=fields[0],
                    open=float(fields[1]),
                    close=float(fields[2]),
                    high=float(fields[3]),
                    low=float(fields[4]),
                    volume=float(fields[5]),
                    amount=float(fields[6]),
                    change_pct=float(fields[8]),
                )
            )
        except ValueError:
            continue
    return bars


async def fetch_tencent_quote(symbol: NormalizedSymbol) -> Dict[str, object]:
    code = _tencent_code(symbol)
    url = f"https://qt.gtimg.cn/q={code}"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
    text = response.text
    if "=\"" not in text:
        raise MarketDataError(f"Tencent quote malformed: {symbol.symbol}")
    raw = text.split("=\"", 1)[1].rsplit("\";", 1)[0]
    fields = raw.split("~")
    if len(fields) < 50:
        raise MarketDataError(f"Tencent quote short fields: {symbol.symbol}")
    market_cap_100m = _safe_float(fields[45])
    float_market_cap_100m = _safe_float(fields[44])
    return {
        "name": fields[1],
        "price": _safe_float(fields[3]),
        "previous_close": _safe_float(fields[4]),
        "high": _safe_float(fields[33]),
        "low": _safe_float(fields[34]),
        "change_pct": _safe_float(fields[32]),
        "volume": (_safe_float(fields[36]) or 0) * 100,
        "amount": (_safe_float(fields[37]) or 0) * 10_000,
        "market_cap": market_cap_100m * 100_000_000 if market_cap_100m is not None else None,
        "float_market_cap": float_market_cap_100m * 100_000_000 if float_market_cap_100m is not None else None,
        "pe_dynamic": _safe_float(fields[39]),
        "pb": _safe_float(fields[46]),
        "turnover_pct": _safe_float(fields[38]),
        "timestamp": fields[30],
        "source": "Tencent secondary quote/valuation",
    }


async def fetch_tencent_daily_bars(symbol: NormalizedSymbol, limit: int = 160) -> List[DailyBar]:
    code = _tencent_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{max(1, min(limit, 300))},qfq"
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    async with httpx.AsyncClient(timeout=12, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
    payload = response.json()
    data = ((payload.get("data") or {}).get(code) or {})
    rows = data.get("qfqday") or data.get("day") or []
    bars: List[DailyBar] = []
    for row in rows:
        if len(row) < 6:
            continue
        try:
            open_price = float(row[1])
            close = float(row[2])
            high = float(row[3])
            low = float(row[4])
            volume_lots = float(row[5])
            previous = bars[-1].close if bars else open_price
            change_pct = (close / previous - 1) * 100 if previous else 0.0
            bars.append(
                DailyBar(
                    date=str(row[0]),
                    open=open_price,
                    close=close,
                    high=high,
                    low=low,
                    volume=volume_lots * 100,
                    amount=0.0,
                    change_pct=change_pct,
                )
            )
        except ValueError:
            continue
    return bars


async def fetch_secondary_quote_valuation(symbol: NormalizedSymbol) -> Dict[str, object]:
    errors = []
    for provider in [fetch_eastmoney_quote, fetch_tencent_quote]:
        try:
            return await provider(symbol)
        except Exception as exc:
            errors.append(str(exc))
    raise MarketDataError("；".join(errors))


async def fetch_secondary_daily_bars(symbol: NormalizedSymbol, limit: int = 160) -> List[DailyBar]:
    errors = []
    for provider in [fetch_eastmoney_daily_bars, fetch_tencent_daily_bars]:
        try:
            bars = await provider(symbol, limit=limit)
            if bars:
                return bars
        except Exception as exc:
            errors.append(str(exc))
    raise MarketDataError("；".join(errors))


async def fetch_sina_quotes(symbols: Iterable[NormalizedSymbol]) -> Dict[str, Dict[str, object]]:
    symbols = list(symbols)
    if not symbols:
        return {}
    code_map = {item.sina_code: item for item in symbols}
    url = "https://hq.sinajs.cn/list=" + ",".join(code_map.keys())
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
    async with httpx.AsyncClient(timeout=10, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
    text = response.content.decode("gbk", errors="replace")
    result: Dict[str, Dict[str, object]] = {}
    for sina_code, normalized in code_map.items():
        parsed = _parse_sina_line(sina_code, text)
        if parsed:
            result[normalized.symbol] = parsed
    return result


async def fetch_sina_market_context() -> Dict[str, List[Dict[str, object]]]:
    codes = [
        "rt_hkHSI",
        "rt_hkHSCEI",
        "gb_$dji",
        "gb_ixic",
        "gb_inx",
        "hf_CAD",
        "hf_GC",
    ]
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
    async with httpx.AsyncClient(timeout=10, headers=headers, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
    text = response.content.decode("gbk", errors="replace")
    hk_indices = [
        item
        for code in ["rt_hkHSI", "rt_hkHSCEI"]
        if (item := _parse_sina_hk_index(code, text))
    ]
    us_indices = [
        item
        for code in ["gb_$dji", "gb_ixic", "gb_inx"]
        if (item := _parse_sina_us_index(code, text))
    ]
    commodities = [
        item
        for code in ["hf_CAD", "hf_GC"]
        if (item := _parse_sina_global_future(code, text))
    ]
    return {"hk_indices": hk_indices, "us_indices": us_indices, "commodities": commodities}


async def fetch_yahoo_copper_future() -> Optional[Dict[str, object]]:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/HG=F?range=5d&interval=1d"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=10, headers=headers, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
    result = ((response.json().get("chart") or {}).get("result") or [None])[0]
    if not result:
        return None
    meta = result.get("meta") or {}
    price = _safe_float(meta.get("regularMarketPrice"))
    previous = _safe_float(meta.get("chartPreviousClose"))
    change_pct = ((price - previous) / previous * 100) if price is not None and previous else None
    timestamp = meta.get("regularMarketTime")
    timestamp_text = datetime.fromtimestamp(timestamp).isoformat(timespec="seconds") if isinstance(timestamp, (int, float)) else ""
    return {
        "symbol": "HG=F",
        "name": meta.get("shortName") or "COMEX Copper",
        "current": price,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "timestamp": timestamp_text,
        "source": "Yahoo Finance secondary futures",
    }


async def fetch_market_weather() -> Dict[str, object]:
    from app.services.symbols import normalize_symbol

    # 000001.SH 上证指数, 000300.SH 沪深300, 399006.SZ 创业板指
    index_symbols = [normalize_symbol("000001.SH"), normalize_symbol("000300.SH"), normalize_symbol("399006.SZ")]
    quotes = await fetch_sina_quotes(index_symbols)
    items: List[Dict[str, object]] = []
    for symbol, quote in quotes.items():
        items.append(
            {
                "symbol": symbol,
                "name": quote.get("name"),
                "current": quote.get("current"),
                "change_pct": round(float(quote.get("change_pct", 0.0)), 2),
                "timestamp": quote.get("timestamp"),
                "source": quote.get("source"),
            }
        )
    context: Dict[str, List[Dict[str, object]]] = {"hk_indices": [], "us_indices": [], "commodities": []}
    context_warnings: List[str] = []
    try:
        context = await fetch_sina_market_context()
    except Exception as exc:
        context_warnings.append(f"Sina 港股/美股/商品上下文读取失败：{exc}")
    try:
        copper = await fetch_yahoo_copper_future()
        if copper:
            context.setdefault("commodities", []).append(copper)
    except Exception as exc:
        context_warnings.append(f"Yahoo COMEX 铜读取失败：{exc}")

    index_changes = [float(item["change_pct"]) for item in items if item.get("change_pct") is not None]
    hk_changes = [float(item["change_pct"]) for item in context.get("hk_indices", []) if item.get("change_pct") is not None]
    us_changes = [float(item["change_pct"]) for item in context.get("us_indices", []) if item.get("change_pct") is not None]
    copper_changes = [
        float(item["change_pct"])
        for item in context.get("commodities", [])
        if item.get("symbol") in {"CAD", "HG=F"} and item.get("change_pct") is not None
    ]
    avg_change = sum(index_changes) / len(index_changes) if index_changes else 0.0
    risk_score = 0
    if avg_change <= -1.5:
        risk_score -= 2
    elif avg_change >= 1.0:
        risk_score += 1
    if hk_changes and sum(hk_changes) / len(hk_changes) <= -1.0:
        risk_score -= 1
    if us_changes and sum(us_changes) / len(us_changes) <= -0.8:
        risk_score -= 1
    if copper_changes and sum(copper_changes) / len(copper_changes) >= 1.0:
        risk_score += 1
    elif copper_changes and sum(copper_changes) / len(copper_changes) <= -1.0:
        risk_score -= 1

    if risk_score <= -2:
        classification = "Risk-off"
    elif risk_score >= 2:
        classification = "Risk-on"
    else:
        classification = "Neutral"
    return {
        "classification": classification,
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "indices": items,
        "hk_indices": context.get("hk_indices", []),
        "us_indices": context.get("us_indices", []),
        "commodities": context.get("commodities", []),
        "risk_score": risk_score,
        "limitations": [
            "A股市场宽度、行业资金流、北向/两融尚未稳定接入，需作为 Missing Inputs 处理。",
            *context_warnings,
        ],
    }
