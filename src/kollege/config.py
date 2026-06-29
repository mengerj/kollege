"""Zentrale Konfiguration via pydantic-settings.

Alle Werte werden aus Umgebungsvariablen (Präfix ``KOLLEGE_``) oder einer
``.env``-Datei gelesen. Secrets liegen nie im Repo (siehe ``.env.example``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KOLLEGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM / Agent — lokal-first default.
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    llm_model: str = "qwen2.5:7b-instruct"
    ollama_base_url: str = "http://localhost:11434/v1"

    # Storage.
    db_path: str = "data/kollege.db"
    markdown_dir: str = "data/projects"

    # Signal (Phase 1).
    signal_api_url: str = "http://localhost:8080"
    signal_number: str = ""


def load_settings() -> Settings:
    """Settings aus Umgebung/`.env` laden. Eigene Funktion erleichtert Mocking."""
    return Settings()
