"""Zentrale Konfiguration via pydantic-settings.

Alle Werte werden aus Umgebungsvariablen (Präfix ``KOLLEGE_``) oder einer
``.env``-Datei gelesen. Secrets liegen nie im Repo (siehe ``.env.example``).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(StrEnum):
    OLLAMA = "ollama"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OPENROUTER = "openrouter"


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

    # OpenRouter — bequemes Benchmark-Backend (8.11): ein Key, viele Modelle
    # (OpenAI-kompatibel). Nur für die Entdeckungsphase mit synthetischen
    # Fixtures gedacht, kein DSGVO-Fundament für die Produktion (siehe 8.12).
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str | None = None

    # Storage.
    db_path: str = "data/kollege.db"
    markdown_dir: str = "data/projects"

    # Signal (Phase 1).
    signal_api_url: str = "http://localhost:8080"
    signal_number: str = ""

    # LLM-Traces (Schritt 8.21) — opt-in, Volltext (Prompts/Tool-Calls).
    # Datensparsamkeit (Prinzip 5): nur für Debugging-Phasen aktivieren.
    # Kurzer Env-Name ohne Präfix-Verdopplung: KOLLEGE_TRACE=1 statt KOLLEGE_TRACE_ENABLED.
    trace_enabled: bool = Field(default=False, validation_alias="KOLLEGE_TRACE")
    trace_dir: str = "data/traces"

    # Proaktive Erinnerungen (Schritt 8.27) — Zeitplan frei konfigurierbar ohne
    # Code anzufassen, siehe docs/reminders.example.toml. Fehlt die Datei, werden
    # schlicht keine Erinnerungen versendet.
    reminders_config_path: str = "data/reminders.toml"


def load_settings() -> Settings:
    """Settings aus Umgebung/`.env` laden. Eigene Funktion erleichtert Mocking."""
    return Settings()
