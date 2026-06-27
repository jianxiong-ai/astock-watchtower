from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile

from app.services import custom_provider_files
from app.services.custom_provider_files import delete_provider_file, provider_file_status, save_provider_upload


def _settings(data_dir):
    return SimpleNamespace(industry_provider_data_dir=str(data_dir), scheduler_timezone="Asia/Shanghai")


@pytest.mark.anyio
async def test_save_provider_upload_accepts_valid_custom_metrics_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "industry_providers"
    monkeypatch.setattr(custom_provider_files, "get_settings", lambda: _settings(data_dir))
    content = (
        "symbol,industry,metric,status,as_of,value,unit,latest_reading,source,source_url,relevance,next_evidence,note\n"
        "600519.SH,白酒,飞天茅台批价,Available,2026-06-26,2350,CNY/瓶,,User source,,批价验证渠道,继续维护批价,\n"
    )
    upload = UploadFile(filename="custom_metrics.csv", file=BytesIO(content.encode("utf-8")))

    status = await save_provider_upload("custom_metrics", upload)

    assert status["exists"] is True
    assert status["total_rows"] == 1
    assert status["errors"] == []
    assert (data_dir / "custom_metrics.csv").exists()


@pytest.mark.anyio
async def test_save_provider_upload_rejects_invalid_rows(tmp_path, monkeypatch):
    data_dir = tmp_path / "industry_providers"
    monkeypatch.setattr(custom_provider_files, "get_settings", lambda: _settings(data_dir))
    content = "symbol,industry,metric,status,as_of,value\n,,,,,\n"
    upload = UploadFile(filename="custom_metrics.csv", file=BytesIO(content.encode("utf-8")))

    with pytest.raises(HTTPException) as exc_info:
        await save_provider_upload("custom_metrics", upload)

    assert exc_info.value.status_code == 400
    assert "缺少 metric" in str(exc_info.value.detail)
    assert not (data_dir / "custom_metrics.csv").exists()


def test_provider_file_status_and_delete(tmp_path, monkeypatch):
    data_dir = tmp_path / "industry_providers"
    data_dir.mkdir()
    monkeypatch.setattr(custom_provider_files, "get_settings", lambda: _settings(data_dir))
    (data_dir / "copper_chain.csv").write_text(
        "metric,as_of,value,unit,source,source_url,note\n"
        "tc_rc,2026-06-26,-40,USD/t,User TC source,,\n",
        encoding="utf-8",
    )

    status = provider_file_status("copper_chain")
    assert status["exists"] is True
    assert status["total_rows"] == 1
    assert status["required_columns"] == ["metric", "as_of", "value"]

    deleted = delete_provider_file("copper_chain")
    assert deleted["exists"] is False
