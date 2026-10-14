"""Runtime configuration loaded from environment / .env (read once on startup)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader (avoids hard dependency on python-dotenv at import)."""
    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(ROOT / ".env")
        return
    except Exception:
        pass
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)).strip())
        return value if value > 0 else default
    except (ValueError, AttributeError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)).strip())
    except (ValueError, AttributeError):
        return default


@dataclass(frozen=True)
class Settings:
    llm_provider: str  # "openai" | "anthropic"
    openai_api_url: str
    openai_api_key: str
    openai_model: str
    anthropic_api_url: str
    anthropic_api_key: str
    anthropic_model: str
    llm_temperature: float
    llm_reasoning_effort: str
    max_summaries: int
    database_path: str
    host: str
    port: int
    admin_username: str
    admin_password: str

    @property
    def active_api_url(self) -> str:
        return self.anthropic_api_url if self.llm_provider == "anthropic" else self.openai_api_url

    @property
    def active_api_key(self) -> str:
        return self.anthropic_api_key if self.llm_provider == "anthropic" else self.openai_api_key

    @property
    def active_model(self) -> str:
        return self.anthropic_model if self.llm_provider == "anthropic" else self.openai_model


def get_settings() -> Settings:
    provider = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    if provider not in ("openai", "anthropic"):
        provider = "openai"
    return Settings(
        llm_provider=provider,
        openai_api_url=os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip(),
        anthropic_api_url=os.environ.get("ANTHROPIC_API_URL", "https://api.anthropic.com").strip().rstrip("/"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip(),
        llm_temperature=_float("LLM_TEMPERATURE", 0.4),
        llm_reasoning_effort=os.environ.get("LLM_REASONING_EFFORT", "").strip().lower(),
        max_summaries=_int("MAX_SUMMARIES_PER_URL_LENGTH", 5),
        database_path=os.environ.get("DATABASE_PATH", "backend/data/summaries.db").strip(),
        host=os.environ.get("HOST", "127.0.0.1").strip(),
        port=_int("PORT", 8000),
        admin_username=os.environ.get("ADMIN_USERNAME", "admin").strip(),
        admin_password=os.environ.get("ADMIN_PASSWORD", "changeme").strip(),
    )


settings = get_settings()
