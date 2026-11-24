import pytest

from agent_service.config import Settings

KEYS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "LLM_MODEL", "LLM_PROVIDER", "AGENT_MODE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)


def test_no_keys_means_guided_mode():
    assert Settings().provider is None


def test_openai_key_selects_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cfg = Settings()
    assert cfg.provider == "openai" and cfg.llm_model == "gpt-5.5"


def test_openai_wins_when_both_keys_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert Settings().provider == "openai"


def test_anthropic_key_selects_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cfg = Settings()
    assert cfg.provider == "anthropic" and cfg.llm_model == "claude-opus-5-5"


def test_explicit_overrides(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-mini")
    assert Settings().llm_model == "gpt-5.4-mini"
    monkeypatch.setenv("AGENT_MODE", "offline")
    assert Settings().provider is None
