from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile

from app.config import get_settings


MAX_UPLOAD_BYTES = 2 * 1024 * 1024
PREVIEW_LIMIT = 20


@dataclass(frozen=True)
class ProviderFileDefinition:
    key: str
    filename: str
    example_filename: str
    title: str
    description: str
    required_columns: tuple[str, ...]
    recommended_columns: tuple[str, ...]


PROVIDER_FILES: dict[str, ProviderFileDefinition] = {
    "copper_chain": ProviderFileDefinition(
        key="copper_chain",
        filename="copper_chain.csv",
        example_filename="copper_chain.example.csv",
        title="铜链专属数据",
        description="补充 TC/RC、LME/SHFE/COMEX 库存、现货升贴水等有色/铜行业数据。",
        required_columns=("metric", "as_of", "value"),
        recommended_columns=("unit", "source", "source_url", "note"),
    ),
    "custom_metrics": ProviderFileDefinition(
        key="custom_metrics",
        filename="custom_metrics.csv",
        example_filename="custom_metrics.example.csv",
        title="通用行业指标",
        description="按股票代码或行业补充任意行业 KPI，例如白酒批价、保险渠道指标、消费客流等。",
        required_columns=("metric", "as_of"),
        recommended_columns=("symbol", "industry", "status", "value", "unit", "latest_reading", "source", "source_url", "relevance", "next_evidence", "note"),
    ),
}


def _data_dir() -> Path:
    path = Path(get_settings().industry_provider_data_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _repo_example_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "industry_providers" / filename


def get_provider_definition(key: str) -> ProviderFileDefinition:
    definition = PROVIDER_FILES.get(key)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"未知行业 provider 文件：{key}")
    return definition


def provider_file_path(key: str) -> Path:
    definition = get_provider_definition(key)
    return _data_dir() / definition.filename


def provider_example_path(key: str) -> Path:
    definition = get_provider_definition(key)
    mounted = _data_dir() / definition.example_filename
    if mounted.exists():
        return mounted
    fallback = _repo_example_path(definition.example_filename)
    if fallback.exists():
        return fallback
    raise HTTPException(status_code=404, detail=f"未找到示例文件：{definition.example_filename}")


def _file_updated_at(path: Path) -> str:
    if not path.exists():
        return ""
    timezone = ZoneInfo(get_settings().scheduler_timezone)
    return datetime.fromtimestamp(path.stat().st_mtime, timezone).isoformat(timespec="seconds")


def _read_csv(path: Path, definition: ProviderFileDefinition, *, preview_limit: int = PREVIEW_LIMIT) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "columns": [],
            "total_rows": 0,
            "preview_rows": [],
            "errors": [],
        }

    errors: list[str] = []
    preview_rows: list[dict[str, str]] = []
    total_rows = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            missing_columns = [column for column in definition.required_columns if column not in columns]
            if missing_columns:
                errors.append(f"缺少必要列：{', '.join(missing_columns)}")

            for row_index, raw in enumerate(reader, start=2):
                total_rows += 1
                row = {str(key or ""): str(value or "").strip() for key, value in raw.items()}
                if len(preview_rows) < preview_limit:
                    preview_rows.append(row)
                if not str(raw.get("metric") or "").strip():
                    errors.append(f"第 {row_index} 行缺少 metric")
                if not str(raw.get("as_of") or "").strip():
                    errors.append(f"第 {row_index} 行缺少 as_of")
                if definition.key == "custom_metrics":
                    if not str(raw.get("symbol") or "").strip() and not str(raw.get("industry") or "").strip():
                        errors.append(f"第 {row_index} 行需要填写 symbol 或 industry")
                if definition.key == "copper_chain" and not str(raw.get("value") or "").strip():
                    errors.append(f"第 {row_index} 行缺少 value")
    except UnicodeDecodeError:
        return {
            "exists": True,
            "columns": [],
            "total_rows": 0,
            "preview_rows": [],
            "errors": ["CSV 编码无法识别，请使用 UTF-8 或 UTF-8 with BOM。"],
        }
    except csv.Error as exc:
        return {
            "exists": True,
            "columns": [],
            "total_rows": 0,
            "preview_rows": [],
            "errors": [f"CSV 解析失败：{exc}"],
        }

    return {
        "exists": True,
        "columns": columns,
        "total_rows": total_rows,
        "preview_rows": preview_rows,
        "errors": errors[:50],
        "error_truncated": len(errors) > 50,
    }


def provider_file_status(key: str) -> dict[str, Any]:
    definition = get_provider_definition(key)
    path = provider_file_path(key)
    csv_status = _read_csv(path, definition)
    example = provider_example_path(key)
    return {
        "key": definition.key,
        "title": definition.title,
        "description": definition.description,
        "filename": definition.filename,
        "example_filename": definition.example_filename,
        "required_columns": list(definition.required_columns),
        "recommended_columns": list(definition.recommended_columns),
        "path": str(path),
        "exists": csv_status["exists"],
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "updated_at": _file_updated_at(path),
        "columns": csv_status["columns"],
        "total_rows": csv_status["total_rows"],
        "preview_rows": csv_status["preview_rows"],
        "errors": csv_status["errors"],
        "error_truncated": csv_status.get("error_truncated", False),
        "example_available": example.exists(),
    }


def list_provider_file_statuses() -> list[dict[str, Any]]:
    return [provider_file_status(key) for key in PROVIDER_FILES]


async def save_provider_upload(key: str, upload: UploadFile) -> dict[str, Any]:
    definition = get_provider_definition(key)
    filename = upload.filename or ""
    if filename and not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="只支持上传 .csv 文件。")
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="CSV 文件过大，当前限制为 2MB。")
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV 编码无法识别，请使用 UTF-8 或 UTF-8 with BOM。") from exc

    target = provider_file_path(key)
    temporary = target.with_suffix(".csv.tmp")
    temporary.write_text(text, encoding="utf-8")
    status = _read_csv(temporary, definition)
    if status["errors"]:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="；".join(status["errors"][:8]))
    temporary.replace(target)
    return provider_file_status(key)


def delete_provider_file(key: str) -> dict[str, Any]:
    path = provider_file_path(key)
    path.unlink(missing_ok=True)
    return provider_file_status(key)
