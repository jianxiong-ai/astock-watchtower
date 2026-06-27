from typing import Dict, List, Optional

from app.services.data_quality import missing_input


FactDict = Dict[str, object]


def _facts_by_field(facts: List[FactDict]) -> Dict[str, FactDict]:
    result: Dict[str, FactDict] = {}
    for fact in facts:
        field_name = str(fact.get("field_name") or "")
        if not field_name:
            continue
        existing = result.get(field_name)
        if existing is None:
            result[field_name] = fact
            continue
        existing_title = str(existing.get("announcement_title") or "")
        title = str(fact.get("announcement_title") or "")
        if "摘要" in existing_title and "摘要" not in title:
            result[field_name] = fact
            continue
        existing_confidence = str(existing.get("confidence") or "")
        confidence = str(fact.get("confidence") or "")
        confidence_rank = {"low": 1, "medium": 2, "high": 3}
        if confidence_rank.get(confidence, 0) > confidence_rank.get(existing_confidence, 0):
            result[field_name] = fact
    return result


def _fmt_fact(fact: Optional[FactDict]) -> str:
    if not fact:
        return "不可靠可得"
    return str(fact.get("value") or fact.get("raw_value") or "不可靠可得")


def _source_of(*facts: Optional[FactDict]) -> Dict[str, str]:
    for fact in facts:
        if fact:
            return {
                "announcement_title": str(fact.get("announcement_title") or ""),
                "published_at": str(fact.get("published_at") or ""),
                "source_url": str(fact.get("source_url") or ""),
            }
    return {"announcement_title": "", "published_at": "", "source_url": ""}


def _available_row(metric: str, reading: str, relevance: str, *facts: Optional[FactDict]) -> Dict[str, object]:
    source = _source_of(*facts)
    return {
        "metric": metric,
        "status": "Available",
        "latest_reading": reading,
        "as_of": source["published_at"],
        "source": source["announcement_title"],
        "source_url": source["source_url"],
        "relevance": relevance,
        "next_evidence": "等待下一份定期报告/业绩预告或公司公告更新。",
    }


def _partial_row(metric: str, reading: str, relevance: str, missing: str, *facts: Optional[FactDict]) -> Dict[str, object]:
    source = _source_of(*facts)
    return {
        "metric": metric,
        "status": "Partial",
        "latest_reading": reading,
        "as_of": source["published_at"],
        "source": source["announcement_title"],
        "source_url": source["source_url"],
        "relevance": relevance,
        "next_evidence": missing,
    }


def _missing_row(metric: str, preferred_source: str, impact: str) -> Dict[str, object]:
    return {
        "metric": metric,
        "status": "Missing",
        "latest_reading": "不可靠可得",
        "as_of": "",
        "source": "",
        "source_url": "",
        "relevance": impact,
        "next_evidence": preferred_source,
    }


def _row_if_present(
    fields: Dict[str, FactDict],
    metric: str,
    primary: str,
    relevance: str,
    change_field: str = "",
) -> Optional[Dict[str, object]]:
    primary_fact = fields.get(primary)
    if not primary_fact:
        return None
    change_fact = fields.get(change_field) if change_field else None
    reading = _fmt_fact(primary_fact)
    if change_fact:
        reading += f"；变化 {_fmt_fact(change_fact)}"
    return _available_row(metric, reading, relevance, primary_fact, change_fact)


def _append_common_financial_rows(rows: List[Dict[str, object]], fields: Dict[str, FactDict]) -> None:
    common_rules = [
        ("收入", "revenue", "收入是多数行业的经营规模起点，需要结合价格、销量和结构解释。", "revenue_change_pct"),
        ("归母净利润", "attributable_net_profit", "利润直接影响估值和分红能力，但需结合现金流和非经常性因素验证。", "attributable_net_profit_change_pct"),
        ("扣非归母净利润", "deducted_attributable_net_profit", "扣非利润用于观察主营盈利质量。", "deducted_attributable_net_profit_change_pct"),
        ("经营现金流", "operating_cash_flow", "经营现金流用于验证利润含金量和营运资本压力。", "operating_cash_flow_change_pct"),
        ("EPS", "basic_eps", "EPS 是每股盈利和估值比较的基础。", "basic_eps_change_pct"),
        ("ROE", "weighted_roe", "ROE 观察资本回报水平和盈利效率。", "weighted_roe_change_pct"),
        ("每股净资产", "book_value_per_share", "每股净资产是银行、保险和资产型公司的估值锚之一。", "book_value_per_share_change_pct"),
        ("现金分红", "cash_dividend_per_10_shares", "现金分红影响股东回报和除权除息安排。"),
    ]
    for metric, primary, relevance, *rest in common_rules:
        row = _row_if_present(fields, metric, primary, relevance, rest[0] if rest else "")
        if row:
            rows.append(row)


def _missing_inputs_from_rows(rows: List[Dict[str, object]]) -> List[Dict[str, str]]:
    result = []
    for row in rows:
        if row.get("status") == "Missing":
            result.append(
                missing_input(
                    str(row.get("metric") or ""),
                    str(row.get("next_evidence") or "官方公告/定期报告结构化解析"),
                    str(row.get("relevance") or "限制行业骨架判断。"),
                    attempted_source=str(row.get("source") or "官方公告结构化事实"),
                    source_url=str(row.get("source_url") or ""),
                    last_known_date=str(row.get("as_of") or ""),
                )
            )
    return result


def _build_baijiu_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    revenue = _row_if_present(fields, "收入增长", "revenue", "白酒收入需进一步拆分为销量、吨价、产品结构和渠道节奏。", "revenue_change_pct")
    profit = _row_if_present(fields, "归母净利润增长", "attributable_net_profit", "白酒利润变化需结合毛利率、费用率和产品结构判断质量。", "attributable_net_profit_change_pct")
    cashflow = _row_if_present(fields, "现金流质量", "operating_cash_flow", "白酒利润通常应有较好现金转化，现金流背离需要解释。", "operating_cash_flow_change_pct")
    margin = _row_if_present(fields, "毛利率", "gross_margin", "毛利率直接反映产品结构、提价和成本压力。", "gross_margin_change_pct")
    contract_liabilities = _row_if_present(fields, "合同负债", "contract_liabilities", "合同负债是观察渠道回款、发货节奏和收入蓄水池的重要指标。", "contract_liabilities_change_pct")
    dividend = _row_if_present(fields, "现金分红", "cash_dividend_per_10_shares", "分红是成熟白酒公司的股东回报核心证据。")
    for row in [revenue, profit, margin, cashflow, contract_liabilities, dividend]:
        if row:
            rows.append(row)
    if not margin:
        rows.append(_missing_row("毛利率/费用率", "定期报告利润表附注与财务指标表", "缺少盈利能力拆分，无法判断利润增长质量。"))
    if not contract_liabilities:
        rows.append(_missing_row("合同负债", "定期报告资产负债表/附注", "限制对渠道打款、发货节奏和未来收入蓄水池的判断。"))
    rows.extend(
        [
            _missing_row("产品结构/渠道结构/经销商", "年报/半年报经营情况章节", "无法验证高端酒占比、直营/批发和经销商质量变化。"),
            _missing_row("批价/终端价", "可靠行业价格数据源", "缺少渠道价格温度，不能判断报表增长与终端动销是否匹配。"),
        ]
    )
    return rows


def _build_insurance_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    nbv = fields.get("new_business_value")
    nbv_growth = fields.get("new_business_value_growth_pct")
    first_regular = fields.get("first_year_regular_premium")
    ten_year = fields.get("ten_year_plus_regular_premium")
    if nbv:
        parts = [f"NBV {_fmt_fact(nbv)}"]
        if nbv_growth:
            parts.append(f"同比 {_fmt_fact(nbv_growth)}")
        if first_regular:
            parts.append(f"首年期交 {_fmt_fact(first_regular)}")
        if ten_year:
            parts.append(f"十年期及以上期交 {_fmt_fact(ten_year)}")
        rows.append(
            _available_row(
                "NBV/新业务价值",
                "；".join(parts),
                "NBV 是保险价值创造核心，需要与保费规模、缴费结构和价值率一起验证。",
                nbv,
                nbv_growth,
                first_regular,
                ten_year,
            )
        )
    else:
        rows.append(_missing_row("NBV/NBV Margin", "年报/半年报内含价值章节", "NBV 是保险价值创造核心；缺失时不能把保费增长等同于价值增长。"))

    premium = fields.get("original_premium_income") or fields.get("premium_income")
    premium_change = fields.get("original_premium_income_change_pct") or fields.get("premium_income_change_pct")
    renewal = fields.get("renewal_premium")
    surrender = fields.get("surrender_rate")
    persistency = fields.get("persistency_commentary")
    productivity = fields.get("agent_productivity_commentary")
    if any([premium, first_regular, renewal, surrender, persistency, productivity]):
        parts = []
        if premium:
            text = f"原保费 {_fmt_fact(premium)}"
            if premium_change:
                text += f"；同比 {_fmt_fact(premium_change)}"
            parts.append(text)
        if first_regular:
            parts.append(f"首年期交 {_fmt_fact(first_regular)}")
        if renewal:
            parts.append(f"续期 {_fmt_fact(renewal)}")
        if surrender:
            parts.append(f"退保率 {_fmt_fact(surrender)}")
        if persistency:
            parts.append(_fmt_fact(persistency))
        if productivity:
            parts.append(_fmt_fact(productivity))
        rows.append(
            _partial_row(
                "渠道/保费/保单质量",
                "；".join(parts),
                "保费规模必须与新单价值、缴费结构、退保率、继续率和渠道产能交叉验证。",
                "下一步需要代理人数量、活动率、13/25月继续率具体数值、银保网点和渠道集中度。",
                premium,
                first_regular,
                renewal,
                surrender,
                persistency,
                productivity,
            )
        )
    else:
        rows.append(_missing_row("保费/新单保费", "月度保费收入公告、定期报告", "缺少保费规模与新单趋势，无法判断业务增长方向。"))

    ev = fields.get("embedded_value")
    ev_growth = fields.get("embedded_value_growth_pct")
    csm = fields.get("contractual_service_margin")
    insurance_service = fields.get("insurance_service_result")
    if any([ev, ev_growth, csm, insurance_service]):
        parts = []
        if ev:
            parts.append(f"EV {_fmt_fact(ev)}")
        if ev_growth:
            parts.append(f"EV同比 {_fmt_fact(ev_growth)}")
        if csm:
            parts.append(f"CSM {_fmt_fact(csm)}")
        if insurance_service:
            parts.append(f"保险服务结果 {_fmt_fact(insurance_service)}")
        rows.append(
            _partial_row(
                "EV/CSM/利润释放",
                "；".join(parts),
                "EV 是价值存量锚，CSM 和保险服务结果用于验证价值释放质量。",
                "下一步需要 CSM 余额/新增/释放、保险服务结果、经验偏差和假设变动。",
                ev,
                ev_growth,
                csm,
                insurance_service,
            )
        )
    else:
        rows.append(_missing_row("EV/CSM/保险服务结果", "年报/半年报 EV 章节与 IFRS17 附注", "缺少价值存量和利润释放质量验证。"))

    total_yield = fields.get("total_investment_yield")
    net_yield = fields.get("net_investment_yield")
    comprehensive_yield = fields.get("comprehensive_investment_yield")
    investment_assets = fields.get("investment_assets")
    if any([total_yield, net_yield, comprehensive_yield, investment_assets]):
        parts = []
        if investment_assets:
            parts.append(f"投资资产 {_fmt_fact(investment_assets)}")
        if total_yield:
            parts.append(f"总投资收益率 {_fmt_fact(total_yield)}")
        if net_yield:
            parts.append(f"净投资收益率 {_fmt_fact(net_yield)}")
        if comprehensive_yield:
            parts.append(f"综合投资收益率 {_fmt_fact(comprehensive_yield)}")
        rows.append(
            _partial_row(
                "投资表现/ALM",
                "；".join(parts),
                "投资收益率、OCI 和久期缺口决定利润、EV 经济偏差和偿付能力波动。",
                "下一步需要 OCI、权益/基金敞口、久期缺口、新钱收益率、信用/地产风险敞口。",
                investment_assets,
                total_yield,
                net_yield,
                comprehensive_yield,
            )
        )
    else:
        rows.append(_missing_row("投资收益率/OCI/久期", "定期报告投资分析章节", "缺少投资端与利率敏感性判断。"))

    core_solvency = fields.get("core_solvency_adequacy_ratio")
    comprehensive_solvency = fields.get("comprehensive_solvency_adequacy_ratio")
    core_capital = fields.get("core_capital")
    actual_capital = fields.get("actual_capital")
    minimum_capital = fields.get("minimum_capital")
    if any([core_solvency, comprehensive_solvency, core_capital, actual_capital, minimum_capital]):
        parts = []
        if core_solvency:
            parts.append(f"核心偿付 {_fmt_fact(core_solvency)}")
        if comprehensive_solvency:
            parts.append(f"综合偿付 {_fmt_fact(comprehensive_solvency)}")
        if core_capital:
            parts.append(f"核心资本 {_fmt_fact(core_capital)}")
        if actual_capital:
            parts.append(f"实际资本 {_fmt_fact(actual_capital)}")
        if minimum_capital:
            parts.append(f"最低资本 {_fmt_fact(minimum_capital)}")
        rows.append(
            _available_row(
                "资本/偿付能力/流动性",
                "；".join(parts),
                "偿付能力约束新业务扩张、分红、资本工具和风险承受能力。",
                core_solvency,
                comprehensive_solvency,
                core_capital,
                actual_capital,
                minimum_capital,
            )
        )
    else:
        rows.append(_missing_row("偿付能力", "偿付能力季度报告/监管披露", "资本安全边际和分红约束无法判断。"))

    profit = _row_if_present(fields, "股东盈利", "attributable_net_profit", "保险会计利润受投资和保险服务结果共同影响，需与 EV/NBV/CSM 交叉验证。", "attributable_net_profit_change_pct")
    dividend = _row_if_present(fields, "分红能力", "cash_dividend_per_10_shares", "分红需要由利润、资本和偿付能力共同支撑。")
    eps = _row_if_present(fields, "每股盈利", "basic_eps", "EPS 反映股东层面盈利，但不足以替代价值增长指标。", "basic_eps_change_pct")
    if any([profit, dividend, eps]):
        available = [item for item in [profit, dividend, eps] if item]
        rows.append(
            _partial_row(
                "股东盈利/分红回报",
                "；".join(str(item.get("latest_reading") or "") for item in available),
                "股东盈利和分红需要与 EV/NBV、偿付能力和投资波动共同验证。",
                "下一步需要年度分红实施、ROE、经营利润或利润来源拆分。",
                *(fields.get(name) for name in ["attributable_net_profit", "cash_dividend_per_10_shares", "basic_eps"] if fields.get(name)),
            )
        )
    else:
        rows.append(_missing_row("股东盈利/分红", "定期报告利润表、分红公告", "无法验证价值增长是否转化为股东回报。"))
    return rows


def _build_nonferrous_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    own_output = fields.get("own_concentrate_copper_output")
    copper_resource = fields.get("controlled_copper_resource")
    gold_resource = fields.get("controlled_gold_resource")
    own_cost_share = fields.get("own_mine_raw_material_cost_share")
    if own_output:
        reading_parts = [f"自产铜精矿含铜 {_fmt_fact(own_output)}"]
        if own_cost_share:
            reading_parts.append(f"自有矿山原材料成本占比 {_fmt_fact(own_cost_share)}")
        if copper_resource:
            reading_parts.append(f"权益铜资源量 {_fmt_fact(copper_resource)}")
        if gold_resource:
            reading_parts.append(f"权益黄金资源量 {_fmt_fact(gold_resource)}")
        rows.append(
            _available_row(
                "自有矿产量/资源自给率",
                "；".join(reading_parts),
                "自有矿产量和资源量决定资源端利润弹性、抗 TC 下行能力和长期供给安全边际。",
                own_output,
                own_cost_share,
                copper_resource,
                gold_resource,
            )
        )
    else:
        rows.append(_missing_row("自有矿产量/资源自给率", "定期报告经营数据、项目公告", "缺少资源端利润弹性和抗周期能力判断。"))

    tc_range = fields.get("tc_spot_range")
    if tc_range:
        rows.append(
            _partial_row(
                "TC/RC",
                f"年报历史披露 TC 现货区间 {_fmt_fact(tc_range)}；非实时日频 TC/RC。",
                "TC/RC 是外购矿冶炼利润核心变量；历史披露可解释趋势，但不能替代每日/每周行业报价。",
                "接入可靠现货/季度/长单 TC/RC 数据源，并与公司采购结构验证。",
                tc_range,
            )
        )
    else:
        rows.append(_missing_row("TC/RC", "可靠行业数据源或公司披露", "缺少冶炼利润核心变量。"))

    gold = fields.get("gold_output")
    silver = fields.get("silver_output")
    acid = fields.get("sulfuric_acid_output")
    if any([gold, silver, acid]):
        parts = []
        if gold:
            parts.append(f"黄金 {_fmt_fact(gold)}")
        if silver:
            parts.append(f"白银 {_fmt_fact(silver)}")
        if acid:
            parts.append(f"硫酸 {_fmt_fact(acid)}")
        rows.append(
            _available_row(
                "副产品贡献",
                "；".join(parts),
                "金、银、硫酸等副产品可部分对冲 TC/RC、铜加工和成本波动，但仍需收入/毛利贡献口径验证。",
                gold,
                silver,
                acid,
            )
        )
    else:
        rows.append(_missing_row("副产品贡献", "定期报告分产品数据、可靠商品价格源", "无法判断副产品是否对冲铜/冶炼波动。"))

    visible_inventory = fields.get("global_visible_copper_inventory")
    inventory_change = fields.get("global_visible_copper_inventory_change")
    if visible_inventory:
        reading = f"年报披露全球显性铜库存 {_fmt_fact(visible_inventory)}"
        if inventory_change:
            reading += f"；库存增加 {_fmt_fact(inventory_change)}"
        rows.append(
            _partial_row(
                "铜价/现货升贴水/库存",
                reading + "；缺少同一时间戳 SHFE/LME/COMEX、升贴水和期限结构。",
                "库存和升贴水解释铜价与股价、TC/RC、利润弹性之间的背离。",
                "接入 SHFE/LME/COMEX 库存、现货升贴水、期限结构和进口盈亏。",
                visible_inventory,
                inventory_change,
            )
        )
    else:
        rows.append(_missing_row("铜价/现货升贴水/库存", "SHFE/LME/COMEX 与可靠现货数据源", "缺少商品价格与物理市场温度，无法解释股价/利润弹性。"))

    own_cost = fields.get("own_mine_raw_material_cost")
    domestic_share = fields.get("domestic_purchase_cost_share")
    overseas_share = fields.get("overseas_purchase_cost_share")
    margin = _row_if_present(fields, "毛利率", "gross_margin", "毛利率帮助验证商品价格、TC/RC、成本和贸易占比变化。", "gross_margin_change_pct")
    if any([own_cost, own_cost_share, domestic_share, overseas_share, margin]):
        parts = []
        if own_cost:
            parts.append(f"自有矿山原材料成本 {_fmt_fact(own_cost)}")
        if own_cost_share:
            parts.append(f"自有矿占比 {_fmt_fact(own_cost_share)}")
        if domestic_share:
            parts.append(f"国内采购占比 {_fmt_fact(domestic_share)}")
        if overseas_share:
            parts.append(f"境外采购占比 {_fmt_fact(overseas_share)}")
        if margin:
            parts.append(f"毛利率线索 {margin.get('latest_reading')}")
        rows.append(
            _partial_row(
                "单位成本/能源成本",
                "；".join(parts),
                "采购结构、毛利率和自有矿占比可验证成本压力，但仍不能替代 C1/单位现金成本。",
                "下一步需要公司单位成本、能源/物流/矿山品位与采购成本说明。",
                own_cost,
                own_cost_share,
                domestic_share,
                overseas_share,
            )
        )
    else:
        rows.append(_missing_row("单位成本/能源成本", "定期报告成本披露、经营数据", "缺少成本曲线与利润弹性验证。"))

    cashflow = fields.get("operating_cash_flow")
    capex = fields.get("capex_cash_paid")
    fcf = fields.get("free_cash_flow")
    inventory = fields.get("inventory")
    short_debt = fields.get("short_term_borrowings")
    monetary = fields.get("monetary_funds")
    if any([cashflow, capex, fcf, inventory, short_debt, monetary]):
        parts = []
        if cashflow:
            parts.append(f"OCF {_fmt_fact(cashflow)}")
        if capex:
            parts.append(f"capex 现金流出 {_fmt_fact(capex)}")
        if fcf:
            parts.append(f"FCF {_fmt_fact(fcf)}")
        if inventory:
            parts.append(f"存货 {_fmt_fact(inventory)}")
        if short_debt:
            parts.append(f"短借 {_fmt_fact(short_debt)}")
        if monetary:
            parts.append(f"货币资金 {_fmt_fact(monetary)}")
        rows.append(
            _available_row(
                "现金流/资本开支",
                "；".join(parts),
                "现金流、营运资本和资本开支是验证周期利润含金量、项目回报和杠杆安全的核心。",
                cashflow,
                capex,
                fcf,
                inventory,
                short_debt,
                monetary,
            )
        )
    else:
        rows.append(_missing_row("Capex/FCF", "现金流量表和重大项目公告", "仅有利润时不能完整判断自由现金流和项目回报。"))

    revenue = _row_if_present(fields, "收入/价格传导", "revenue", "有色公司收入通常受商品价格、销量和贸易业务共同影响，需拆分验证。", "revenue_change_pct")
    profit = _row_if_present(fields, "利润弹性", "attributable_net_profit", "利润变化需与铜价、TC/RC、成本和副产品贡献交叉验证。", "attributable_net_profit_change_pct")
    equity = _row_if_present(fields, "资产/权益基底", "shareholder_equity", "资产权益变化用于观察资本开支、杠杆和资产减值压力。", "shareholder_equity_change_pct")
    dividend = _row_if_present(fields, "现金分红", "cash_dividend_per_10_shares", "分红可观察周期公司利润兑现和资本配置。")
    for row in [revenue, profit, margin, equity, dividend]:
        if row:
            rows.append(row)
    return rows


def _build_bank_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    assets = _row_if_present(fields, "资产规模", "total_assets", "银行资产规模变化影响贷款/存款扩张和资本消耗。", "total_assets_change_pct")
    equity = _row_if_present(fields, "股东权益", "shareholder_equity", "权益变化影响资本安全边际和每股净资产。", "shareholder_equity_change_pct")
    revenue = _row_if_present(fields, "营业收入", "revenue", "收入变化需进一步拆分净利息收入、手续费和投资收益。", "revenue_change_pct")
    profit = _row_if_present(fields, "归母净利润", "attributable_net_profit", "银行利润需与拨备、资产质量和资本消耗交叉验证。", "attributable_net_profit_change_pct")
    roe = _row_if_present(fields, "ROE", "weighted_roe", "ROE 观察资本回报，但需结合不良和拨备覆盖率。", "weighted_roe_change_pct")
    bvps = _row_if_present(fields, "每股净资产", "book_value_per_share", "PB 估值需要可靠每股净资产作为分母。", "book_value_per_share_change_pct")
    deposits = _row_if_present(fields, "存款规模", "customer_deposits", "存款增长影响负债成本、扩表能力和净息差。", "customer_deposits_change_pct")
    loans = _row_if_present(fields, "贷款规模", "loans_and_advances", "贷款增长影响资产收益、风险资本消耗和资产质量压力。", "loans_and_advances_change_pct")
    nim = _row_if_present(fields, "净息差", "net_interest_margin", "净息差决定银行核心收入压力。", "net_interest_margin_change_pct")
    npl = _row_if_present(fields, "不良率/关注率", "npl_ratio", "不良率是资产质量核心指标，需与拨备覆盖率一起看。", "npl_ratio_change_pct")
    provision = _row_if_present(fields, "拨备覆盖率", "provision_coverage_ratio", "拨备覆盖率反映风险缓冲厚度。", "provision_coverage_ratio_change_pct")
    capital = _row_if_present(fields, "资本充足率", "capital_adequacy_ratio", "资本充足率约束分红、扩表和风险吸收能力。", "capital_adequacy_ratio_change_pct")
    core_capital = _row_if_present(fields, "核心一级资本充足率", "core_tier1_capital_adequacy_ratio", "核心一级资本是最硬的资本安全垫。", "core_tier1_capital_adequacy_ratio_change_pct")
    dividend = _row_if_present(fields, "现金分红", "cash_dividend_per_10_shares", "银行分红需要由利润、资本充足率和监管要求共同支撑。")
    for row in [assets, equity, deposits, loans, revenue, profit, roe, bvps, nim, npl, provision, core_capital, capital, dividend]:
        if row:
            rows.append(row)
    if not nim:
        rows.append(_missing_row("净息差", "定期报告主要财务指标/经营分析", "净息差决定银行核心收入压力。"))
    if not npl:
        rows.append(_missing_row("不良率/关注率", "定期报告资产质量章节", "缺少资产质量判断，无法验证利润是否靠拨备调节。"))
    if not provision:
        rows.append(_missing_row("拨备覆盖率", "定期报告资产质量章节", "缺少风险缓冲指标。"))
    if not any([capital, core_capital]):
        rows.append(_missing_row("资本充足率", "定期报告资本管理章节", "缺少分红和扩表约束判断。"))
    return rows


def _build_securities_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "股东权益/净资本基底", "shareholder_equity", "券商业务扩张和自营风险承载依赖资本与权益基底。", "shareholder_equity_change_pct"),
        _row_if_present(fields, "投资与自营波动代理", "fair_value_change_income", "自营和交易性金融资产波动会影响利润稳定性。", "fair_value_change_income_change_pct"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("市场成交额/两融余额", "交易所/中证金融/可靠市场数据源", "缺少经纪和两融业务景气度温度。"),
            _missing_row("投行业务储备", "公司定期报告分部经营数据、交易所项目进度", "无法判断投行收入可持续性。"),
            _missing_row("财富管理/资管规模", "定期报告分部数据", "缺少轻资本业务质量判断。"),
            _missing_row("净资本/风险覆盖率", "定期报告风险控制指标", "缺少资本约束与杠杆安全边际。"),
        ]
    )
    return rows


def _build_real_estate_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "合同负债/预收款", "contract_liabilities", "预收款和合同负债是结转收入和交付节奏的重要线索。", "contract_liabilities_change_pct"),
        _row_if_present(fields, "存货/开发成本", "inventory", "存货反映土地和在建项目占用，也可能带来减值风险。", "inventory_change_pct"),
        _row_if_present(fields, "资产负债率", "asset_liability_ratio", "地产公司需优先观察杠杆和融资约束。", "asset_liability_ratio_change_pct"),
        _row_if_present(fields, "货币资金", "monetary_funds", "现金覆盖短债和交付压力。", "monetary_funds_change_pct"),
        _row_if_present(fields, "短期借款", "short_term_borrowings", "短债变化影响再融资和流动性风险。", "short_term_borrowings_change_pct"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("合同销售额/销售面积", "月度经营公告或定期报告经营数据", "缺少销售去化与现金回流判断。"),
            _missing_row("土储/拿地/竣工交付", "定期报告项目表和经营公告", "无法判断未来结转和交付风险。"),
            _missing_row("有息债务到期结构", "定期报告债务附注", "缺少短期流动性压力验证。"),
        ]
    )
    return rows


def _build_electronics_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "毛利率", "gross_margin", "电子/半导体毛利率反映价格、稼动率、产品结构和成本。", "gross_margin_change_pct"),
        _row_if_present(fields, "存货", "inventory", "存货是周期拐点、跌价风险和备货节奏的核心验证项。", "inventory_change_pct"),
        _row_if_present(fields, "资本开支", "capex_cash_paid", "Capex 决定产能扩张和现金流压力。", "capex_cash_paid_change_pct"),
        _row_if_present(fields, "研发费用", "rd_expense", "研发投入影响产品迭代和长期竞争力。", "rd_expense_change_pct"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("订单/在手订单/出货量", "定期报告经营讨论、公司公告或可靠行业数据", "缺少需求端验证。"),
            _missing_row("客户/产品结构", "定期报告分产品/分客户披露", "无法判断增长质量和集中度风险。"),
            _missing_row("产能利用率/价格周期", "公司披露或行业数据", "缺少周期位置判断。"),
        ]
    )
    return rows


def _build_new_energy_battery_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "毛利率", "gross_margin", "新能源/电池毛利率反映价格竞争、原材料成本和产品结构。", "gross_margin_change_pct"),
        _row_if_present(fields, "存货", "inventory", "存货变化可验证需求、价格下行和跌价风险。", "inventory_change_pct"),
        _row_if_present(fields, "资本开支", "capex_cash_paid", "Capex 影响产能扩张、折旧压力和自由现金流。", "capex_cash_paid_change_pct"),
        _row_if_present(fields, "研发费用", "rd_expense", "研发投入影响电池技术路线、客户粘性和长期竞争力。", "rd_expense_change_pct"),
        _row_if_present(fields, "自由现金流", "free_cash_flow", "自由现金流验证利润是否被产能扩张和营运资本吸收。"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("动力/储能电池出货或装机", "公司定期报告经营数据、动力电池联盟或可靠行业数据", "缺少量端景气和份额变化判断。"),
            _missing_row("电池单价/原材料价格", "行业价格数据、公司经营讨论或可靠商品数据", "无法拆分价格竞争与成本改善。"),
            _missing_row("产能利用率/在建产能", "定期报告产能、在建工程和经营讨论", "缺少过剩产能和折旧压力验证。"),
            _missing_row("客户/产品结构", "定期报告分产品、分客户或公司公告", "无法判断增长质量和客户集中度风险。"),
        ]
    )
    return rows


def _build_consumer_manufacturing_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "毛利率", "gross_margin", "毛利率反映产品结构、原材料成本、汇率和渠道价格。", "gross_margin_change_pct"),
        _row_if_present(fields, "存货", "inventory", "存货可验证渠道库存、备货和减值风险。", "inventory_change_pct"),
        _row_if_present(fields, "销售费用", "selling_expense", "销售费用影响品牌投放、渠道效率和利润弹性。", "selling_expense_change_pct"),
        _row_if_present(fields, "经营现金流", "operating_cash_flow", "经营现金流验证利润质量、渠道回款和营运资本占用。", "operating_cash_flow_change_pct"),
        _row_if_present(fields, "现金分红", "cash_dividend_per_10_shares", "分红是成熟消费制造公司股东回报的重要部分。"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("内外销/品类结构", "定期报告分产品、分地区经营数据", "缺少增长来源和利润结构判断。"),
            _missing_row("渠道库存/终端动销", "公司经营交流、渠道数据或可靠第三方数据", "无法验证收入是否由真实需求驱动。"),
            _missing_row("原材料成本/汇率影响", "定期报告经营讨论、商品和汇率数据", "缺少利润率弹性和成本压力判断。"),
        ]
    )
    return rows


def _build_pharma_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "毛利率", "gross_margin", "医药毛利率反映产品结构、集采和价格压力。", "gross_margin_change_pct"),
        _row_if_present(fields, "研发费用", "rd_expense", "研发费用是创新药、器械和平台型公司的核心投入。", "rd_expense_change_pct"),
        _row_if_present(fields, "销售费用", "selling_expense", "销售费用影响放量效率和合规风险。", "selling_expense_change_pct"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("管线/适应症/临床进度", "公司公告、药监局和定期报告研发章节", "缺少未来增长和失败风险判断。"),
            _missing_row("医保/集采/审评审批", "医保局、药监局和公司公告", "缺少政策价格风险。"),
            _missing_row("核心产品销量/放量", "定期报告产品数据或可靠行业数据", "无法验证收入增长质量。"),
        ]
    )
    return rows


def _build_utilities_energy_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    for item in [
        _row_if_present(fields, "毛利率", "gross_margin", "能源/公用事业毛利率受燃料成本、电价/气价和利用小时影响。", "gross_margin_change_pct"),
        _row_if_present(fields, "资本开支", "capex_cash_paid", "公用事业高 capex 会影响自由现金流和分红能力。", "capex_cash_paid_change_pct"),
        _row_if_present(fields, "自由现金流", "free_cash_flow", "自由现金流验证分红可持续性。"),
        _row_if_present(fields, "资产负债率", "asset_liability_ratio", "杠杆影响融资成本和扩张空间。", "asset_liability_ratio_change_pct"),
    ]:
        if item:
            rows.append(item)
    rows.extend(
        [
            _missing_row("电价/气价/煤价", "发改委、交易中心、公司公告或可靠商品数据", "缺少价差和盈利弹性判断。"),
            _missing_row("利用小时/发电量/装机", "月度经营公告或定期报告经营数据", "缺少量端和产能利用验证。"),
            _missing_row("项目投产/补贴/应收账款", "公司公告和定期报告附注", "无法判断现金回收和项目回报。"),
        ]
    )
    return rows


def _build_generic_mapping(fields: Dict[str, FactDict]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    _append_common_financial_rows(rows, fields)
    rows.extend(
        [
            _missing_row("毛利率/费用率", "定期报告利润表及附注", "缺少盈利质量拆分。"),
            _missing_row("资产负债率/债务结构", "定期报告资产负债表及附注", "缺少资产负债风险判断。"),
            _missing_row("行业专属 KPI", "行业经营数据或公司公告", "通用财务字段不能替代行业核心驱动。"),
        ]
    )
    return rows


def build_sector_indicator_mapping(industry: str, fact_summary: Dict[str, object]) -> Dict[str, object]:
    facts = list(fact_summary.get("recent_facts") or [])
    fields = _facts_by_field(facts)
    if industry == "白酒":
        rows = _build_baijiu_mapping(fields)
    elif industry == "保险":
        rows = _build_insurance_mapping(fields)
    elif industry == "有色/矿业":
        rows = _build_nonferrous_mapping(fields)
    elif industry == "银行":
        rows = _build_bank_mapping(fields)
    elif industry == "券商":
        rows = _build_securities_mapping(fields)
    elif industry == "地产":
        rows = _build_real_estate_mapping(fields)
    elif industry == "半导体/电子":
        rows = _build_electronics_mapping(fields)
    elif industry == "新能源/电池":
        rows = _build_new_energy_battery_mapping(fields)
    elif industry == "家电/消费制造":
        rows = _build_consumer_manufacturing_mapping(fields)
    elif industry == "医药":
        rows = _build_pharma_mapping(fields)
    elif industry == "公用/能源":
        rows = _build_utilities_energy_mapping(fields)
    else:
        rows = _build_generic_mapping(fields)

    available = [row for row in rows if row.get("status") == "Available"]
    partial = [row for row in rows if row.get("status") == "Partial"]
    missing = [row for row in rows if row.get("status") == "Missing"]
    return {
        "status": "Available" if available else "Missing",
        "rows": rows,
        "summary_lines": [
            f"{row.get('metric')}：{row.get('latest_reading')}｜{row.get('as_of')}"
            for row in (available + partial)[:6]
        ],
        "missing_inputs": _missing_inputs_from_rows(missing),
        "coverage": {
            "available": len(available),
            "partial": len(partial),
            "missing": len(missing),
            "total": len(rows),
        },
    }
