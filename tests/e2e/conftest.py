"""Configuração de fixtures para testes E2E.

Este módulo configura opções adicionais do pytest para E2E.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    """Adiciona opções de linha de comando personalizadas."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests against running server"
    )
    parser.addoption(
        "--e2e-url",
        action="store",
        default="http://localhost:8000",
        help="Base URL for E2E tests"
    )


def pytest_collection_modifyitems(config, items):
    """Modifica itens de teste baseado nas opções."""
    if not config.getoption("--run-e2e"):
        # Skip E2E tests unless --run-e2e is passed
        skip_e2e = pytest.mark.skip(reason="Need --run-e2e option to run")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)


@pytest.fixture(scope="session")
def e2e_base_url(request):
    """Retorna a URL base para testes E2E."""
    return request.config.getoption("--e2e-url")


@pytest.fixture(scope="session")
def api_prefix():
    """Retorna o prefixo da API."""
    return "/api/v1"
