from app.services.data_quality import missing_input, stale_source
from app.services.indicators import infer_industry, sector_indicator_template
from app.services.sector_mapping import build_sector_indicator_mapping
from app.services.symbols import _symbol_from_eastmoney_suggest_item, normalize_symbol


def test_data_quality_helpers_use_consistent_shape():
    missing = missing_input(
        "TC/RC",
        "可靠行业数据源",
        "缺少冶炼利润核心变量。",
        company="600362.SH",
        attempted_source="MVP provider",
    )
    stale = stale_source(
        "估值数据",
        "2026-06-26T15:00:00+08:00",
        "PE/PB 不可靠可得。",
        preferred_source="可靠行情估值 provider",
    )

    for item in [missing, stale]:
        assert item["metric"]
        assert item["status"] in {"Missing", "Stale"}
        assert "attempted_source" in item
        assert "preferred_source" in item
        assert "next_source" in item
        assert "impact" in item


def test_extended_industry_inference_and_templates():
    assert infer_industry("中信证券", "600030.SH") == "券商"
    assert infer_industry("万科A", "000002.SZ") == "地产"
    assert infer_industry("京东方A", "000725.SZ") == "半导体/电子"
    assert infer_industry("宁德时代", "300750.SZ") == "新能源/电池"
    assert infer_industry("美的集团", "000333.SZ") == "家电/消费制造"
    assert infer_industry("恒瑞医药", "600276.SH") == "医药"
    assert infer_industry("长江电力", "600900.SH") == "公用/能源"

    assert "投行业务" in sector_indicator_template("券商")["core_metrics"]
    assert "合同销售" in sector_indicator_template("地产")["core_metrics"]
    assert "研发投入" in sector_indicator_template("半导体/电子")["core_metrics"]
    assert "出货/装机" in sector_indicator_template("新能源/电池")["core_metrics"]
    assert "渠道库存" in sector_indicator_template("家电/消费制造")["core_metrics"]
    assert "管线进度" in sector_indicator_template("医药")["core_metrics"]


def test_stock_name_and_eastmoney_suggest_symbol_normalization():
    assert normalize_symbol("中信证券").symbol == "600030.SH"
    assert normalize_symbol("宁德时代").symbol == "300750.SZ"
    assert (
        _symbol_from_eastmoney_suggest_item(
            {
                "Code": "600030",
                "Name": "中信证券",
                "Classify": "AStock",
                "QuoteID": "1.600030",
                "SecurityTypeName": "沪A",
            }
        )
        == "600030.SH"
    )
    assert (
        _symbol_from_eastmoney_suggest_item(
            {
                "Code": "300750",
                "Name": "宁德时代",
                "Classify": "AStock",
                "QuoteID": "0.300750",
                "SecurityTypeName": "深A",
            }
        )
        == "300750.SZ"
    )


def test_real_estate_sector_mapping_uses_available_balance_sheet_facts():
    fact_summary = {
        "recent_facts": [
            {
                "field_name": "contract_liabilities",
                "value": "¥10,000,000",
                "published_at": "2026-04-30T18:00:00",
                "announcement_title": "2026年第一季度报告",
                "source_url": "https://example.test/report.pdf",
            },
            {
                "field_name": "asset_liability_ratio",
                "value": "72.50%",
                "published_at": "2026-04-30T18:00:00",
                "announcement_title": "2026年第一季度报告",
                "source_url": "https://example.test/report.pdf",
            },
        ]
    }

    mapping = build_sector_indicator_mapping("地产", fact_summary)
    metrics = {row["metric"]: row for row in mapping["rows"]}

    assert metrics["合同负债/预收款"]["status"] == "Available"
    assert metrics["资产负债率"]["latest_reading"] == "72.50%"
    assert mapping["coverage"]["available"] >= 2
    assert any(item["metric"] == "合同销售额/销售面积" for item in mapping["missing_inputs"])
