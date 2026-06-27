import pytest

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
        return {}

    monkeypatch.setattr("app.services.industry_providers.fetch_sina_quotes", fake_fetch_sina_quotes)
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

    assert any(row["metric"] == "保险板块温度 provider" for row in result["rows"])
