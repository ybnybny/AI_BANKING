"""应用配置。通过环境变量/.env 覆盖默认值。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # 项目根目录 (f:\AI_BANKING)
load_dotenv(BASE_DIR / ".env")


class Settings:
    def __init__(self) -> None:
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")

        self.app_host: str = os.getenv("APP_HOST", "0.0.0.0")
        self.app_port: int = int(os.getenv("APP_PORT", "8000"))
        self.database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ai_banking.db")

        # 高风险操作确认阈值（转账金额 >= 该值需二次确认）
        self.transfer_confirm_threshold: float = float(
            os.getenv("TRANSFER_CONFIRM_THRESHOLD", "500")
        )

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


settings = Settings()
