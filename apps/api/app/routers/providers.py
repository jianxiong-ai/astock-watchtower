from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.services.custom_provider_files import (
    delete_provider_file,
    list_provider_file_statuses,
    provider_example_path,
    provider_file_path,
    provider_file_status,
    save_provider_upload,
)


router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("/industry-files")
def list_industry_provider_files() -> list[dict]:
    return list_provider_file_statuses()


@router.get("/industry-files/{key}")
def get_industry_provider_file(key: str) -> dict:
    return provider_file_status(key)


@router.post("/industry-files/{key}/upload")
async def upload_industry_provider_file(key: str, file: UploadFile = File(...)) -> dict:
    return await save_provider_upload(key, file)


@router.delete("/industry-files/{key}")
def remove_industry_provider_file(key: str) -> dict:
    return delete_provider_file(key)


@router.get("/industry-files/{key}/download")
def download_industry_provider_file(key: str) -> FileResponse:
    path = provider_file_path(key)
    if not path.exists():
        raise HTTPException(status_code=404, detail="当前自定义 CSV 文件不存在，请先上传。")
    return FileResponse(path, media_type="text/csv", filename=path.name)


@router.get("/industry-files/{key}/example")
def download_industry_provider_example(key: str) -> FileResponse:
    path = provider_example_path(key)
    return FileResponse(path, media_type="text/csv", filename=path.name)
