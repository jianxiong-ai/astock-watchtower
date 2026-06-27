import pytest
from types import SimpleNamespace

from app.services.industry_providers import build_industry_provider_context, merge_provider_rows


@pytest.mark.anyio
async def test_nonferrous_provider_uses_market_weather_copper_context():
    market_weather = {
        "commodities": [
            {
                "symbol": "HG=F",
                "name": "COMEX Copper",
                "current": 6.2,
                "change_pct": -2.35,
                "timestamp": "2026-06-26T20:59:51",
                "source": "Yahoo Finance secondary futures",
            }
        ],
        "sector_weather": {
            "timestamp": "2026-06-26T15:30:00+08:00",
            "top_losers": [
                {"code": "BK0478", "name": "能源金属", "change_pct": -7.81, "main_net_inflow": -1000000}
            ],
            "top_gainers": [],
            "top_inflows": [],
            "top_outflows": [],
        },
    }

    result = await build_industry_provider_context("有色/矿业", "600362.SH", market_weather)
    metrics = [row["metric"] for row in result["rows"]]

    assert result["status"] == "Available"
    assert "铜价/商品价格 provider" in metrics
    assert "有色/铜链板块温度 provider" in metrics
    assert "TC/RC 外部报价 provider" in metrics
    assert any(item["metric"] == "TC/RC 外部报价 provider" for item in result["missing_inputs"])


@pytest.mark.anyio
async def test_nonferrous_custom_csv_provider_overrides_missing(tmp_path, monkeypatch):
    data_dir = tmp_path / "industry_providers"
    data_dir.mkdir()
    (data_dir / "copper_chain.csv").write_text(
        "\n".join(
            [
                "metric,as_of,value,unit,source,source_url,note",
                "tc_rc,2026-06-26,-40,USD/t,User TC source,,spot TC representative",
                "lme_inventory,2026-06-26,125000,t,User inventory source,,",
                "shfe_inventory,2026-06-26,98000,t,User inventory source,,",
                "shfe_spot_premium,2026-06-26,-80,CNY/t,User premium source,,",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.services.industry_providers.get_settings",
        lambda: SimpleNamespace(industry_provider_data_dir=str(data_dir)),
    )
    market_weather = {"commodities": [], "sector_weather": {"sectors": []}}

    result = await build_industry_provider_context("有色/矿业", "600362.SH", market_weather)
    rows = {row["metric"]: row for row in result["rows"]}

    assert rows["TC/RC 外部报价 provider"]["status"] == "Available"
    assert "TC/RC -40.00USD/t" in rows["TC/RC 外部报价 provider"]["latest_reading"]
    assert rows["SHFE/LME/COMEX 库存/升贴水 provider"]["status"] == "Available"
    assert "LME库存 125,000.00t" in rows["SHFE/LME/COMEX 库存/升贴水 provider"]["latest_reading"]
    assert not any(item["metric"] == "TC/RC 外部报价 provider" for item in result["missing_inputs"])


def test_merge_provider_rows_replaces_missing_with_provider_partial():
    rows = [
        {
            "metric": "铜价/现货升贴水/库存",
            "status": "Missing",
            "latest_reading": "不可靠可得",
        }
    ]
    provider_rows = [
        {
            "metric": "铜价/商品价格 provider",
            "status": "Partial",
            "latest_reading": "COMEX Copper 6.20，-2.35%",
        }
    ]

    merged = merge_provider_rows(rows, provider_rows)

    assert merged[0]["metric"] == "铜价/商品价格 provider"
    assert merged[0]["status"] == "Partial"


def test_merge_provider_rows_keeps_filing_partial_over_provider_missing():
    rows = [
        {
            "metric": "TC/RC",
            "status": "Partial",
            "latest_reading": "年报历史披露 TC 现货区间 -50至-40",
        }
    ]
    provider_rows = [
        {
            "metric": "TC/RC 外部报价 provider",
            "status": "Missing",
            "latest_reading": "不可靠可得",
        }
    ]

    merged = merge_provider_rows(rows, provider_rows)

    assert len(merged) == 1
    assert merged[0]["metric"] == "TC/RC"


@pytest.mark.anyio
async def test_insurance_provider_uses_full_sector_list_when_not_top_ranked(monkeypatch):
    async def fake_fetch_sina_quotes(symbols):
        return {
            "601336.SH": {
                "name": "新华保险",
                "current": 59.6,
                "timestamp": "2026-06-26 15:00:03",
                "source": "Sina secondary quote",
            }
        }

    async def fake_fetch_chinamoney_gov_yield():
        return {
            "date": "2026-06-26",
            "one_year_yield": 1.1089,
            "ten_year_yield": 1.7598,
            "timestamp": "2026-06-27 18:25:38",
            "source": "ChinaMoney official public government bond yield history",
            "source_url": "https://www.chinamoney.com.cn/chinese/sddsintigy/",
        }

    async def fake_fetch_sina_hk_stock_quote(hk_code):
        return {
            "symbol": hk_code,
            "name": "新华保险",
            "current": 46.38,
            "timestamp": "2026/06/26 16:08:14",
            "source": "Sina secondary HK stock quote",
        }

    async def fake_fetch_sina_fx_quote(code):
        return {
            "symbol": "HKDCNY",
            "name": "港元兑人民币",
            "current": 0.867,
            "timestamp": "2026-06-27 04:59:53",
            "source": "Sina secondary FX quote",
        }

    monkeypatch.setattr("app.services.industry_providers.fetch_sina_quotes", fake_fetch_sina_quotes)
    monkeypatch.setattr("app.services.industry_providers.fetch_chinamoney_gov_yield", fake_fetch_chinamoney_gov_yield)
    monkeypatch.setattr("app.services.industry_providers.fetch_sina_hk_stock_quote", fake_fetch_sina_hk_stock_quote)
    monkeypatch.setattr("app.services.industry_providers.fetch_sina_fx_quote", fake_fetch_sina_fx_quote)
    market_weather = {
        "sector_weather": {
            "timestamp": "2026-06-26T15:30:00+08:00",
            "sectors": [
                {"code": "BK0474", "name": "保险", "change_pct": -4.11, "main_net_inflow": -800000000}
            ],
            "top_gainers": [],
            "top_losers": [],
            "top_inflows": [],
            "top_outflows": [],
        }
    }

    result = await build_industry_provider_context("保险", "601336.SH", market_weather)
    rows = {row["metric"]: row for row in result["rows"]}

    assert rows["保险板块温度 provider"]["status"] == "Available"
    assert rows["中国10年国债收益率 provider"]["status"] == "Available"
    assert "10年期国债收益率 1.76%" in rows["中国10年国债收益率 provider"]["latest_reading"]
    assert rows["A/H 溢价与 H 股价格 provider"]["status"] == "Partial"
    assert "A/H 溢价约" in rows["A/H 溢价与 H 股价格 provider"]["latest_reading"]
