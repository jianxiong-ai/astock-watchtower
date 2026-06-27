from dataclasses import dataclass
from typing import Dict, Optional

import httpx


KNOWN_NAMES: Dict[str, str] = {
    "贵州茅台": "600519.SH",
    "江西铜业": "600362.SH",
    "新华保险": "601336.SH",
    "中信证券": "600030.SH",
    "招商银行": "600036.SH",
    "平安银行": "000001.SZ",
    "万科A": "000002.SZ",
    "万科Ａ": "000002.SZ",
    "宁德时代": "300750.SZ",
    "京东方A": "000725.SZ",
    "京东方Ａ": "000725.SZ",
    "恒瑞医药": "600276.SH",
    "长江电力": "600900.SH",
}


@dataclass(frozen=True)
class NormalizedSymbol:
    symbol: str
    exchange: str
    sina_code: str


def normalize_symbol(raw: str) -> NormalizedSymbol:
    value = raw.strip().upper()
    value = KNOWN_NAMES.get(value, value)
    value = value.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")

    if value.startswith("SH") and len(value) == 8:
        code = value[2:]
        exchange = "SH"
    elif value.startswith("SZ") and len(value) == 8:
        code = value[2:]
        exchange = "SZ"
    elif value.startswith("BJ") and len(value) == 8:
        code = value[2:]
        exchange = "BJ"
    elif value.endswith(".SH"):
        code = value[:6]
        exchange = "SH"
    elif value.endswith(".SZ"):
        code = value[:6]
        exchange = "SZ"
    elif value.endswith(".BJ"):
        code = value[:6]
        exchange = "BJ"
    elif value.startswith("6"):
        code = value[:6]
        exchange = "SH"
    elif value.startswith(("0", "3")):
        code = value[:6]
        exchange = "SZ"
    elif value.startswith(("4", "8")):
        code = value[:6]
        exchange = "BJ"
    else:
        raise ValueError(f"无法识别 A 股代码或公司名：{raw}")

    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"无法识别 A 股代码或公司名：{raw}")

    sina_prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}[exchange]
    return NormalizedSymbol(symbol=f"{code}.{exchange}", exchange=exchange, sina_code=f"{sina_prefix}{code}")


def _normalize_known_name_key(raw: str) -> str:
    return raw.strip().replace("Ａ", "A").replace("ａ", "A")


def _symbol_from_eastmoney_suggest_item(item: Dict[str, object]) -> Optional[str]:
    """Convert an Eastmoney search suggestion row to standard A-share symbol.

    The suggest endpoint is only used as an input convenience provider. It is not
    treated as official company identity data, so callers should still label the
    final analysis sources separately.
    """

    if str(item.get("Classify") or "") != "AStock":
        return None

    code = str(item.get("Code") or item.get("UnifiedCode") or "").strip()
    quote_id = str(item.get("QuoteID") or "").strip()
    market = quote_id.split(".", 1)[0] if "." in quote_id else str(item.get("MktNum") or "").strip()
    security_type_name = str(item.get("SecurityTypeName") or "")

    exchange = ""
    if market == "1" or security_type_name.startswith("沪") or code.startswith("6"):
        exchange = "SH"
    elif market == "0" or security_type_name.startswith("深") or code.startswith(("0", "3")):
        exchange = "SZ"
    elif market in {"8", "2"} or security_type_name.startswith("北") or code.startswith(("4", "8")):
        exchange = "BJ"

    if len(code) != 6 or not code.isdigit() or not exchange:
        return None
    return f"{code}.{exchange}"


async def resolve_symbol_query(raw: str) -> NormalizedSymbol:
    """Resolve either an A-share code or a Chinese company name.

    Fast path is deterministic local parsing. If that fails, use Eastmoney's
    search suggest endpoint as a best-effort secondary name lookup so the UI can
    accept common Chinese stock names, not only ticker codes.
    """

    known_key = _normalize_known_name_key(raw)
    if known_key in KNOWN_NAMES:
        return normalize_symbol(KNOWN_NAMES[known_key])

    try:
        return normalize_symbol(raw)
    except ValueError as original_error:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            "input": raw.strip(),
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
        }
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
        try:
            async with httpx.AsyncClient(timeout=8, headers=headers, trust_env=False) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
            payload = response.json()
            rows = ((payload.get("QuotationCodeTable") or {}).get("Data") or [])
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = _symbol_from_eastmoney_suggest_item(row)
                if symbol:
                    return normalize_symbol(symbol)
        except Exception as exc:
            raise ValueError(f"无法识别 A 股代码或公司名：{raw}；中文名搜索源暂不可用：{exc}") from original_error

        raise original_error
