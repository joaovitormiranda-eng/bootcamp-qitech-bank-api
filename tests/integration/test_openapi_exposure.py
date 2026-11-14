"""SEC-05 — exposição da documentação OpenAPI por ambiente.

A auditoria P2-A apontou uma divergência entre o comentário de ``src/app.py``
("os três None desligam a documentação") e a configuração real, que tinha
``/docs``, ``/redoc`` e ``/openapi.json`` habilitados. A correção alinha
comentário e código e, como defesa em profundidade, desliga a documentação
quando ``APP_ENV == "production"``.

Estes testes constroem a aplicação em processo (``create_app``) sob diferentes
valores de ``APP_ENV`` e inspecionam as rotas registradas. Não tocam o
PostgreSQL compartilhado nem a instância viva do CI (que roda com
``APP_ENV=test`` e, portanto, mantém a documentação ligada). A URL de banco
existe só para permitir criar o Engine na importação; nenhuma rota é chamada.

Como os testes recarregam ``constants`` e ``app`` (que leem ``APP_ENV`` na
importação), a fixture ``restore_app_modules`` tira um retrato de ``sys.modules``
e o restaura ao final, para não contaminar nenhum teste que importe esses
módulos depois.
"""

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture
def restore_app_modules():
    saved = {name: sys.modules.get(name) for name in ("constants", "app")}
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
                importlib.reload(module)


def _registered_paths(app) -> set:
    return {getattr(route, "path", None) for route in app.routes}


def _build_app_with_env(monkeypatch, app_env: str):
    source_root = Path(__file__).resolve().parents[2] / "src"
    monkeypatch.syspath_prepend(str(source_root))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://bootcamp:bootcamp@127.0.0.1:5432/bootcamp",
    )
    monkeypatch.setenv("INTERNAL_TOKEN", "default_token")
    monkeypatch.setenv("ANALYSIS_PROVIDER_URL", "http://127.0.0.1:1080")
    monkeypatch.setenv("APP_ENV", app_env)

    # constants lê APP_ENV na importação; app importa de constants. Recarregar
    # os dois garante que o valor de APP_ENV deste teste seja o que vale.
    import constants

    importlib.reload(constants)
    import app as app_module

    importlib.reload(app_module)
    return app_module.create_app()


@pytest.mark.usefixtures("restore_app_modules")
class TestOpenApiExposureByEnvironment:
    @pytest.mark.parametrize("app_env", ["local", "test"], ids=["local", "test"])
    def test_docs_are_enabled_outside_production(self, monkeypatch, app_env):
        application = _build_app_with_env(monkeypatch, app_env)
        paths = _registered_paths(application)

        assert "/openapi.json" in paths
        assert "/docs" in paths
        assert "/redoc" in paths

    def test_docs_are_disabled_in_production(self, monkeypatch):
        application = _build_app_with_env(monkeypatch, "production")
        paths = _registered_paths(application)

        assert "/openapi.json" not in paths
        assert "/docs" not in paths
        assert "/redoc" not in paths

        # As rotas de negócio e as públicas continuam registradas mesmo com a
        # documentação desligada: o gate de desligar doc não afeta a API.
        assert "/" in paths
        assert "/health_check" in paths
        assert "/client" in paths
