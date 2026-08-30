from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Environment-backed settings with safe development defaults."""

    app_env: str = os.getenv("APP_ENV", "development")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    mimo_api_key: str = os.getenv("MIMO_API_KEY", "")
    mimo_base_url: str = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
    mimo_model: str = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    mimo_web_search_enabled: bool = os.getenv("MIMO_WEB_SEARCH_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    mock_mimo: bool = os.getenv("MOCK_MIMO", "false").lower() in {"1", "true", "yes"}
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))
    max_resume_bytes: int = int(os.getenv("MAX_RESUME_BYTES", str(10 * 1024 * 1024)))
    max_answer_chars: int = int(os.getenv("MAX_ANSWER_CHARS", "12000"))
    max_model_calls_per_hour: int = int(os.getenv("MAX_MODEL_CALLS_PER_HOUR", "60"))

    @property
    def database_url(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'interview.db').resolve()}"


settings = Settings()
