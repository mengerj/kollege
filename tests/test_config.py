"""Tests für die Konfiguration."""

from __future__ import annotations

import pytest

from kollege.config import LLMProvider, Settings


def test_defaults_are_lokal_first() -> None:
    s = Settings(_env_file=None)
    assert s.llm_provider is LLMProvider.OLLAMA
    assert s.ollama_base_url.endswith("/v1")
    assert s.db_path.endswith(".db")


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOLLEGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("KOLLEGE_LLM_MODEL", "claude-sonnet-4-6")
    s = Settings(_env_file=None)
    assert s.llm_provider is LLMProvider.ANTHROPIC
    assert s.llm_model == "claude-sonnet-4-6"
