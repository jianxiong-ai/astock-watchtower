from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./astock_watchtower.sqlite3"
    redis_url: str = "redis://localhost:6379/0"
    api_cors_origins: str = "http://localhost:3000"
    feishu_default_secret: str = ""
    feishu_message_mode: str = "card"
    scheduler_enabled: bool = True
    scheduler_timezone: str = "Asia/Shanghai"
    scheduler_hour: int = 8
    scheduler_minute: int = 0
    a_share_holidays: str = ""
    announcement_lookback_days: int = 30
    analysis_announcement_lookback_days: int = 180
    pdf_extract_max_pages: int = 8
    pdf_text_max_chars: int = 20000
    pdf_table_max_pages: int = 12
    pdf_table_max_tables: int = 12
    pdf_table_max_chars: int = 15000
    periodic_report_pdf_extract_max_pages: int = 80
    periodic_report_pdf_text_max_chars: int = 80000
    periodic_report_pdf_table_max_pages: int = 60
    periodic_report_pdf_table_max_tables: int = 80
    periodic_report_pdf_table_max_chars: int = 60000
    industry_provider_data_dir: str = "/data/industry_providers"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins(self) -> List[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def holiday_dates(self) -> List[str]:
        return [item.strip() for item in self.a_share_holidays.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
