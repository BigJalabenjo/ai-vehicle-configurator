"""Runtime configuration, read from environment variables only (12-factor).

Secrets (``ANTHROPIC_API_KEY``) are never read or logged here; the Anthropic
SDK picks them up from the environment itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["auto", "llm", "offline"]
Provider = Literal["auto", "openai", "anthropic"]

DEFAULT_MODELS = {"openai": "gpt-5.5", "anthropic": "claude-opus-5-5"}


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    catalog_url: str = field(default_factory=lambda: os.getenv("CATALOG_URL", "http://localhost:8001"))
    agent_mode: Mode = field(default_factory=lambda: os.getenv("AGENT_MODE", "auto"))  # type: ignore[assignment]
    llm_provider: Provider = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto"))  # type: ignore[assignment]
    llm_model_override: str | None = field(default_factory=lambda: os.getenv("LLM_MODEL") or None)
    llm_effort: str | None = field(default_factory=lambda: os.getenv("LLM_EFFORT") or None)
    llm_max_steps: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_STEPS", "8")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "60")))
    llm_server_fallback: bool = field(default_factory=lambda: os.getenv("LLM_SERVER_FALLBACK", "true").lower() == "true")
    session_ttl_s: int = field(default_factory=lambda: int(os.getenv("SESSION_TTL_S", "3600")))
    max_sessions: int = field(default_factory=lambda: int(os.getenv("MAX_SESSIONS", "1000")))
    max_message_chars: int = field(default_factory=lambda: int(os.getenv("MAX_MESSAGE_CHARS", "2000")))
    cors_origins: list[str] = field(default_factory=lambda: _list(os.getenv("CORS_ORIGINS", "http://localhost:8080")))
    # Shared-password protection (see auth.py). Off when APP_PASSWORD is empty.
    app_password: str | None = field(default_factory=lambda: os.getenv("APP_PASSWORD") or None)
    app_secret: str | None = field(default_factory=lambda: os.getenv("APP_SECRET") or None)
    auth_ttl_h: float = field(default_factory=lambda: float(os.getenv("AUTH_TTL_HOURS", "12")))
    # Sites allowed to embed the app (Chrome extension overlay), space-separated, e.g. "https://configure.bmw.de".
    embed_origins: list[str] = field(default_factory=lambda: os.getenv("EMBED_ORIGINS", "").split())

    @property
    def provider(self) -> str | None:
        """Which LLM provider to use, or None for guided (offline) mode.

        auto: OpenAI if OPENAI_API_KEY is set, else Anthropic if ANTHROPIC_API_KEY is set, else guided.
        """
        if self.agent_mode == "offline":
            return None
        if self.llm_provider != "auto":
            return self.llm_provider
        if os.getenv("OPENAI_API_KEY"):
            return "openai"
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return "anthropic"
        return "openai" if self.agent_mode == "llm" else None

    @property
    def llm_model(self) -> str:
        return self.llm_model_override or DEFAULT_MODELS.get(self.provider or "openai", "gpt-5.5")


settings = Settings()
