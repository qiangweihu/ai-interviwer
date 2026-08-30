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
    mock_mimo: bool = os.getenv("MOCK_MIMO", "false").lower() in {"1", "true", "yes"}
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    session_ttl_hours: int = int(os.getenv("SESSION_TTL_HOURS", "24"))
    max_resume_bytes: int = int(os.getenv("MAX_RESUME_BYTES", str(10 * 1024 * 1024)))
    max_answer_chars: int = int(os.getenv("MAX_ANSWER_CHARS", "12000"))
    max_model_calls_per_hour: int = int(os.getenv("MAX_MODEL_CALLS_PER_HOUR", "60"))
    local_asr_enabled: bool = os.getenv("LOCAL_ASR_ENABLED", "true").lower() in {"1", "true", "yes"}
    local_asr_model: str = os.getenv("LOCAL_ASR_MODEL", "small")
    local_asr_model_dir: str = os.getenv("LOCAL_ASR_MODEL_DIR", "")
    local_asr_compute_type: str = os.getenv("LOCAL_ASR_COMPUTE_TYPE", "int8")
    local_asr_language: str = os.getenv("LOCAL_ASR_LANGUAGE", "zh")
    max_audio_bytes: int = int(os.getenv("MAX_AUDIO_BYTES", str(15 * 1024 * 1024)))
    max_audio_seconds: int = int(os.getenv("MAX_AUDIO_SECONDS", "180"))
    # Practical tasks fail closed in production until the private runner is
    # explicitly enabled. Mock mode enables the deterministic test runner.
    practical_runner_enabled: bool = os.getenv(
        "PRACTICAL_RUNNER_ENABLED", "true" if os.getenv("MOCK_MIMO", "false").lower() in {"1", "true", "yes"} else "false"
    ).lower() in {"1", "true", "yes"}
    practical_runner_url: str = os.getenv("PRACTICAL_RUNNER_URL", "http://runner:8080")
    practical_runner_token: str = os.getenv("PRACTICAL_RUNNER_TOKEN", "")
    practical_max_runs_per_task: int = int(os.getenv("PRACTICAL_MAX_RUNS_PER_TASK", "10"))
    practical_max_source_chars: int = int(os.getenv("PRACTICAL_MAX_SOURCE_CHARS", "65536"))

    @property
    def database_url(self) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'interview.db').resolve()}"


settings = Settings()
