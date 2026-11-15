"""SEC-05 — exposição da documentação OpenAPI por ambiente (fail-closed).

A auditoria P2-A apontou uma divergência entre o comentário de ``src/app.py``
e a configuração real, que deixava ``/docs``, ``/redoc`` e ``/openapi.json``
sempre habilitados. A correção aplica uma política **fail-closed**: a
documentação só é habilitada quando ``APP_ENV`` é EXPLICITAMENTE um ambiente de
desenvolvimento conhecido (``"local"`` ou ``"test"``). Qualquer outro caso
— ``"production"``, variável ausente, vazia ou desconhecida — DESLIGA a doc.

A decisão é feita com ``os.environ.get("APP_ENV")`` (valor cru do ambiente), e
não com o ``APP_ENV`` de ``constants.py``, que aplica o fallback ``"local"``
quando a variável está ausente — fallback que reabriria o caso fail-open.

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


DOC_PATHS = ("/openapi.json", "/docs", "/redoc")
# Amostra de rotas R01-R10 + públicas que NUNCA devem ser afetadas pelo gating.
BUSINESS_AND_PUBLIC_PATHS = ("/", "/health_check", "/client")


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


def _build_app(monkeypatch, *, app_env):
    """Constrói a app em processo. ``app_env=None`` remove a variável do ambiente.

    Qualquer outro valor (inclusive ``""``) é definido literalmente, permitindo
    cobrir os cinco cenários de SEC-05: local, test, production, ausente e
    vazio/desconhecido.
    """
    source_root = Path(__file__).resolve().parents[2] / "src"
    monkeypatch.syspath_prepend(str(source_root))
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://bootcamp:bootcamp@127.0.0.1:5432/bootcamp",
    )
    monkeypatch.setenv("INTERNAL_TOKEN", "default_token")
    monkeypatch.setenv("ANALYSIS_PROVIDER_URL", "http://127.0.0.1:1080")

    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)

    # constants lê APP_ENV na importação; app importa de constants. Recarregar
    # os dois garante que o estado de ambiente deste teste seja o que vale.
    import constants

    importlib.reload(constants)
    import app as app_module

    importlib.reload(app_module)
    return app_module.create_app()


def _assert_docs_enabled(paths: set) -> None:
    for doc in DOC_PATHS:
        assert doc in paths, f"esperava {doc} habilitado"


def _assert_docs_disabled(paths: set) -> None:
    for doc in DOC_PATHS:
        assert doc not in paths, f"esperava {doc} DESABILITADO (fail-closed)"


def _assert_business_routes_present(paths: set) -> None:
    # O gating de doc nunca pode afetar as rotas R01-R10 nem as públicas.
    for route in BUSINESS_AND_PUBLIC_PATHS:
        assert route in paths, f"rota de negócio/pública {route} ausente"


@pytest.mark.usefixtures("restore_app_modules")
class TestOpenApiExposureByEnvironment:
    """Cinco cenários da política fail-closed (SEC-05)."""

    @pytest.mark.parametrize("app_env", ["local", "test"], ids=["local", "test"])
    def test_docs_enabled_only_for_explicit_dev_environments(
        self, monkeypatch, app_env
    ):
        application = _build_app(monkeypatch, app_env=app_env)
        paths = _registered_paths(application)

        _assert_docs_enabled(paths)
        _assert_business_routes_present(paths)

    def test_docs_disabled_in_production(self, monkeypatch):
        application = _build_app(monkeypatch, app_env="production")
        paths = _registered_paths(application)

        _assert_docs_disabled(paths)
        _assert_business_routes_present(paths)

    def test_docs_disabled_when_app_env_absent(self, monkeypatch):
        # Fail-closed: variável ausente NÃO habilita a doc, mesmo que o fallback
        # global de constants.py seja "local".
        application = _build_app(monkeypatch, app_env=None)
        paths = _registered_paths(application)

        _assert_docs_disabled(paths)
        _assert_business_routes_present(paths)

    def test_docs_disabled_when_app_env_empty(self, monkeypatch):
        application = _build_app(monkeypatch, app_env="")
        paths = _registered_paths(application)

        _assert_docs_disabled(paths)
        _assert_business_routes_present(paths)

    @pytest.mark.parametrize(
        "app_env",
        ["staging", "prod", "Production", "LOCAL", "dev", "qa"],
        ids=["staging", "prod", "Production", "LOCAL-uppercase", "dev", "qa"],
    )
    def test_docs_disabled_for_unknown_or_miscased_environments(
        self, monkeypatch, app_env
    ):
        # Qualquer valor fora do allowlist exato {"local","test"} fica fechado,
        # inclusive variações de caixa como "LOCAL".
        application = _build_app(monkeypatch, app_env=app_env)
        paths = _registered_paths(application)

        _assert_docs_disabled(paths)
        _assert_business_routes_present(paths)
