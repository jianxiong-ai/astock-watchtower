from typing import Dict, List, Optional

from app.services.market_data import DailyBar


SYMBOL_INDUSTRY: Dict[str, str] = {
    "600519.SH": "白酒",
    "600362.SH": "有色/矿业",
    "601336.SH": "保险",
    "600030.SH": "券商",
    "000001.SZ": "银行",
    "000002.SZ": "地产",
    "000725.SZ": "半导体/电子",
    "300750.SZ": "新能源/电池",
    "002594.SZ": "新能源/电池",
    "000333.SZ": "家电/消费制造",
    "000651.SZ": "家电/消费制造",
    "600276.SH": "医药",
    "600900.SH": "公用/能源",
}


def infer_industry(name: str, symbol: str) -> str:
    if symbol in SYMBOL_INDUSTRY:
        return SYMBOL_INDUSTRY[symbol]
    if "茅台" in name or "酒" in name:
        return "白酒"
    if "银行" in name:
        return "银行"
    if "保险" in name:
        return "保险"
    if "铜" in name or "铝" in name or "矿" in name:
        return "有色/矿业"
    if "证券" in name or "券商" in name:
        return "券商"
    if "地产" in name or "置业" in name or "房地产" in name:
        return "地产"
    if "半导体" in name or "芯片" in name or "电子" in name or "光电" in name:
        return "半导体/电子"
    if "电池" in name or "锂" in name or "光伏" in name or "新能源" in name or "宁德" in name or "比亚迪" in name:
        return "新能源/电池"
    if "美的" in name or "格力" in name or "海尔" in name or "家电" in name or "电器" in name:
        return "家电/消费制造"
    if "药" in name or "医" in name or "生物" in name:
        return "医药"
    if "电力" in name or "能源" in name or "水电" in name or "燃气" in name or "煤" in name:
        return "公用/能源"
    return "通用"


def sector_indicator_template(industry: str) -> Dict[str, object]:
    templates = {
        "白酒": {
            "core_metrics": ["收入增长", "归母净利润增长", "毛利率", "合同负债", "产品结构", "渠道结构", "经销商变化", "批价/终端价", "现金分红"],
            "missing_inputs": ["实时批价/终端价", "渠道库存", "同一时间戳行业指数资金流"],
        },
        "保险": {
            "core_metrics": ["保费", "NBV", "EV", "CSM", "投资收益率", "偿付能力", "分红能力"],
            "missing_inputs": ["CSM 变动", "久期缺口", "OCI/权益敞口", "代理人数量和活动率"],
        },
        "有色/矿业": {
            "core_metrics": ["商品价格", "库存", "TC/RC", "自有矿产量", "单位成本", "capex", "自由现金流"],
            "missing_inputs": ["同一时间戳现货升贴水", "TC/RC", "单位现金成本"],
        },
        "银行": {
            "core_metrics": ["净息差", "存贷增长", "不良率", "拨备覆盖", "资本充足", "分红率"],
            "missing_inputs": ["最新净息差", "资产质量季度明细"],
        },
        "券商": {
            "core_metrics": ["市场成交额", "两融余额", "投行业务", "财富管理", "自营收益", "资本充足"],
            "missing_inputs": ["业务分部最新数据", "自营持仓风险"],
        },
        "地产": {
            "core_metrics": ["合同销售", "结转收入", "毛利率", "存货/土储", "短债现金覆盖", "交付", "资产负债率"],
            "missing_inputs": ["月度合同销售", "土储与项目交付表", "有息债务到期结构"],
        },
        "半导体/电子": {
            "core_metrics": ["订单/出货", "库存", "毛利率", "产能利用率", "capex", "研发投入", "客户/产品结构"],
            "missing_inputs": ["订单/出货量", "产能利用率", "客户/产品结构"],
        },
        "新能源/电池": {
            "core_metrics": ["出货/装机", "单价", "毛利率", "产能利用率", "库存", "capex", "研发投入", "客户/产品结构", "现金流"],
            "missing_inputs": ["动力/储能电池出货或装机", "电池单价与原材料价格", "产能利用率", "客户结构"],
        },
        "家电/消费制造": {
            "core_metrics": ["收入增长", "毛利率", "内外销结构", "渠道库存", "原材料成本", "费用率", "现金流", "分红"],
            "missing_inputs": ["内外销和品类结构", "渠道库存/终端动销", "原材料成本和汇率影响"],
        },
        "医药": {
            "core_metrics": ["收入/核心产品", "毛利率", "研发投入", "管线进度", "审批/医保/集采", "销售费用", "现金流"],
            "missing_inputs": ["管线和审批进度", "医保/集采影响", "核心产品销量"],
        },
        "公用/能源": {
            "core_metrics": ["电价/气价/煤价", "发电量/利用小时", "装机", "燃料成本", "capex", "自由现金流", "分红"],
            "missing_inputs": ["电价/气价/煤价", "发电量/利用小时", "项目投产和补贴回收"],
        },
        "通用": {
            "core_metrics": ["收入", "利润", "毛利率", "现金流", "资产负债率", "分红", "公告事件"],
            "missing_inputs": ["行业专属 KPI 尚未配置"],
        },
    }
    return templates.get(industry, templates["通用"])


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)


def _ma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains = []
    losses = []
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    for change in changes[-period:]:
        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_technical_indicators(bars: List[DailyBar]) -> Dict[str, object]:
    if not bars:
        return {
            "status": "Missing",
            "reason": "历史 K 线不可得",
            "source": "Eastmoney secondary historical kline",
        }
    closes = [bar.close for bar in bars]
    highs = [bar.high for bar in bars]
    lows = [bar.low for bar in bars]
    volumes = [bar.volume for bar in bars]
    latest = bars[-1]
    ma = {f"ma{window}": _round(_ma(closes, window)) for window in [5, 10, 20, 60, 120]}
    high_20 = max(highs[-20:]) if len(highs) >= 20 else None
    low_20 = min(lows[-20:]) if len(lows) >= 20 else None
    high_60 = max(highs[-60:]) if len(highs) >= 60 else None
    low_60 = min(lows[-60:]) if len(lows) >= 60 else None
    peak_60 = max(closes[-60:]) if len(closes) >= 60 else max(closes)
    drawdown = (latest.close / peak_60 - 1) * 100 if peak_60 else None
    volume_ma20 = _ma(volumes, 20)
    volume_ratio = latest.volume / volume_ma20 if volume_ma20 else None

    signals = []
    if abs(latest.change_pct) >= 4:
        signals.append(f"单日涨跌幅达到 {latest.change_pct:.2f}%")
    if volume_ratio is not None and volume_ratio >= 1.5:
        signals.append(f"成交量为20日均量 {volume_ratio:.2f} 倍")
    if high_20 is not None and latest.close >= high_20:
        signals.append("收盘价触及/突破20日高点")
    if low_20 is not None and latest.close <= low_20:
        signals.append("收盘价触及/跌破20日低点")
    rsi14 = _rsi(closes, 14)
    if rsi14 is not None and rsi14 >= 70:
        signals.append(f"RSI14 {rsi14:.2f}，偏强/过热")
    elif rsi14 is not None and rsi14 <= 30:
        signals.append(f"RSI14 {rsi14:.2f}，偏弱/超卖")

    return {
        "status": "Available",
        "as_of": latest.date,
        "close": latest.close,
        "change_pct": _round(latest.change_pct),
        "ma": ma,
        "rsi14": _round(rsi14),
        "high_low": {
            "high_20": _round(high_20),
            "low_20": _round(low_20),
            "high_60": _round(high_60),
            "low_60": _round(low_60),
        },
        "recent_peak_drawdown_pct": _round(drawdown),
        "volume": latest.volume,
        "volume_ma20": _round(volume_ma20),
        "volume_ratio_to_ma20": _round(volume_ratio),
        "signals": signals,
        "source": "Eastmoney secondary historical kline",
    }
