"""pytest-Konfiguration: gemeinsame Optionen und Fixtures für alle Tests."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help=(
            "Eval-Tests gegen echtes LLM ausführen (Ollama/Anthropic). "
            "Erfordert laufenden Ollama-Server oder ANTHROPIC_API_KEY. "
            "Standard: FunctionModel-Mocks (CI-sicher, kein Netz)."
        ),
    )


@pytest.fixture
def real_llm(request: pytest.FixtureRequest) -> bool:
    """True wenn --real-llm übergeben wurde (Eval-Tests gegen echtes LLM)."""
    return bool(request.config.getoption("--real-llm"))
