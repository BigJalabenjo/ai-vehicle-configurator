"""Runtime configuration, read from environment variables only (12-factor).

Secrets (``ANTHROPIC_API_KEY``) are never read or logged here; the Anthropic
SDK picks them up from the environment itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

Mode = Literal["auto", "claude", "offline"]


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    catalog_url: str = field(default_factory=lambda: os.getenv("CATALOG_URL", "http://localhost:8001"))
    agent_mode: Mode = field(default_factory=lambda: os.getenv("AGENT_MODE", "auto"))  # type: ignore[assignment]
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "claude-opus-5-5"))
    llm_effort: str = field(default_factory=lambda: os.getenv("LLM_EFFORT", "medium"))
    llm_max_steps: int = field(default_factory=lambda: int(os.getenv("LLM_MAX_STEPS", "8")))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "60")))
    llm_server_fallback: bool = field(default_factory=lambda: os.getenv("LLM_SERVER_FALLBACK", "true").lower() == "true")
    session_ttl_s: int = field(default_factory=lambda: int(os.getenv("SESSION_TTL_S", "3600")))
    max_sessions: int = field(default_factory=lambda: int(os.getenv("MAX_SESSIONS", "1000")))
    max_message_chars: int = field(default_factory=lambda: int(os.getenv("MAX_MESSAGE_CHARS", "2000")))
    cors_origins: list[str] = field(default_factory=lambda: _list(os.getenv("CORS_ORIGINS", "http://localhost:8080")))

    @property
    def claude_available(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))

    @property
    def use_claude(self) -> bool:
        if self.agent_mode == "offline":
            return False
        if self.agent_mode == "claude":
            return True
        return self.claude_available


settings = Settings()
