"""COD-10 — convenções REST e sumidouros de roteamento, pela rede.

Estes testes exercitam as bordas do contrato HTTP que NÃO dependem de dados
semeados: token ausente, caminho desconhecido, método errado, UUID malformado
em parâmetro de caminho e chave bem-formada porém inexistente. Todas as
asserções usam somente status e códigos publicados em ``docs/ROTAS.md``
(seção 2.2 e catálogo da seção 5): QIT000002, QIT000404, QIT000405,
QIT000001, CLI0001 e ACC0001.

Nada é importado de ``src/``; não há acesso a banco. As requisições passam por
``ClientRequisition.send``, como em ``tests/integration/test_healthcheck.py``.
Os UUIDs de "não encontrado" são aleatórios mas sintaticamente válidos, então
cada execução é determinística e isolada.
"""

from uuid import uuid4

import pytest

from tests.utils.requisition import ClientRequisition

from .support import auth_headers


# Rotas protegidas R01-R09 (método, caminho). R10 /health_check é pública e
# fica de fora de propósito (ROTAS 2.1). Usa-se um UUID fixo-por-chamada para
# os caminhos parametrizados; o que se testa aqui é o gate de token, que roda
# ANTES de qualquer consulta ao recurso.
_PROTECTED_ROUTES = [
    ("POST", "/client"),
    ("GET", "/client/{key}"),
    ("PATCH", "/client/{key}"),
    ("POST", "/client/{key}/analysis"),
    ("POST", "/client/{key}/account"),
    ("GET", "/account/{key}"),
    ("PATCH", "/account/{key}"),
    ("POST", "/account/{key}/transaction"),
    ("GET", "/account/{key}/transactions"),
]


def _render(path: str) -> str:
    return path.format(key=uuid4())


class TestInternalTokenGate:
    """ROTAS 2.1: R01-R09 exigem INTERNAL-TOKEN; ausência -> 403 QIT000002."""

    @pytest.mark.parametrize(
        ("method", "path"),
        _PROTECTED_ROUTES,
        ids=[f"{method}-{path}" for method, path in _PROTECTED_ROUTES],
    )
    def test_missing_token_is_forbidden(self, method: str, path: str) -> None:
        response = ClientRequisition.send(method, _render(path))

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"

    @pytest.mark.parametrize(
        ("method", "path"),
        _PROTECTED_ROUTES,
        ids=[f"{method}-{path}" for method, path in _PROTECTED_ROUTES],
    )
    def test_invalid_token_is_forbidden(self, method: str, path: str) -> None:
        response = ClientRequisition.send(
            method,
            _render(path),
            headers={"INTERNAL-TOKEN": "not-an-internal-token"},
        )

        assert response.response_status == 403
        assert response.response_json["code"] == "QIT000002"


class TestUnknownPaths:
    """ROTAS 2.2: caminho desconhecido -> 404 QIT000404."""

    @pytest.mark.parametrize(
        "path",
        [
            "/does-not-exist",
            "/client/{key}/unknown".format(key=uuid4()),
            "/account/{key}/unknown".format(key=uuid4()),
        ],
        ids=["flat", "under-client", "under-account"],
    )
    def test_unknown_path_is_not_found(self, path: str) -> None:
        response = ClientRequisition.send(
            "GET",
            path,
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "QIT000404"

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/sample_entity"),
            ("GET", "/sample_entities"),
            ("GET", "/sample_entity/{key}".format(key=uuid4())),
            ("PUT", "/sample_entity/{key}".format(key=uuid4())),
            ("PATCH", "/sample_entity/{key}".format(key=uuid4())),
        ],
        ids=[
            "post-sample_entity",
            "get-sample_entities",
            "get-sample_entity",
            "put-sample_entity",
            "patch-sample_entity",
        ],
    )
    def test_removed_demo_routes_are_gone(self, method: str, path: str) -> None:
        """COD-02: as rotas de demonstração SampleEntity foram removidas.

        Com token válido, elas agora caem no sumidouro genérico de 404 em vez
        de responderem como um recurso vivo, provando que a remoção não deixou
        um handler registrado para trás.
        """
        response = ClientRequisition.send(
            method,
            path,
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "QIT000404"


class TestMethodNotAllowed:
    """ROTAS 2.2: método errado em caminho existente -> 405 QIT000405."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("DELETE", "/client"),
            ("PUT", "/client"),
            ("DELETE", "/client/{key}".format(key=uuid4())),
            ("DELETE", "/account/{key}".format(key=uuid4())),
            ("PUT", "/account/{key}".format(key=uuid4())),
            ("DELETE", "/account/{key}/transaction".format(key=uuid4())),
            ("DELETE", "/account/{key}/transactions".format(key=uuid4())),
        ],
        ids=[
            "delete-client",
            "put-client",
            "delete-client-key",
            "delete-account-key",
            "put-account-key",
            "delete-transaction",
            "delete-transactions",
        ],
    )
    def test_wrong_method_is_not_allowed(self, method: str, path: str) -> None:
        response = ClientRequisition.send(
            method,
            path,
            headers=auth_headers(),
        )

        assert response.response_status == 405
        assert response.response_json["code"] == "QIT000405"


class TestMalformedPathUuid:
    """ROTAS 2.1: 'UUID inválido -> 400'."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/client/not-a-uuid"),
            ("PATCH", "/client/not-a-uuid"),
            ("POST", "/client/not-a-uuid/analysis"),
            ("POST", "/client/not-a-uuid/account"),
            ("GET", "/account/not-a-uuid"),
            ("PATCH", "/account/not-a-uuid"),
            ("GET", "/account/not-a-uuid/transactions"),
        ],
        ids=[
            "get-client",
            "patch-client",
            "post-analysis",
            "post-account",
            "get-account",
            "patch-account",
            "get-transactions",
        ],
    )
    def test_malformed_uuid_is_bad_request(self, method: str, path: str) -> None:
        response = ClientRequisition.send(
            method,
            path,
            headers=auth_headers(),
        )

        assert response.response_status == 400


class TestResourceNotFound:
    """ROTAS 2.1: UUID válido porém inexistente -> 404 com código do recurso.

    Rotas de cliente devolvem CLI0001; rotas de conta devolvem ACC0001.
    """

    def test_absent_client_on_get(self) -> None:
        response = ClientRequisition.send(
            "GET",
            f"/client/{uuid4()}",
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "CLI0001"

    def test_absent_client_on_analysis(self) -> None:
        response = ClientRequisition.send(
            "POST",
            f"/client/{uuid4()}/analysis",
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "CLI0001"

    def test_absent_client_on_account_opening(self) -> None:
        response = ClientRequisition.send(
            "POST",
            f"/client/{uuid4()}/account",
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "CLI0001"

    def test_absent_client_on_patch(self) -> None:
        response = ClientRequisition.send(
            "PATCH",
            f"/client/{uuid4()}",
            payload={"status": "PENDING", "reason": "Reanálise"},
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "CLI0001"

    def test_absent_account_on_get(self) -> None:
        response = ClientRequisition.send(
            "GET",
            f"/account/{uuid4()}",
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "ACC0001"

    def test_absent_account_on_statement(self) -> None:
        response = ClientRequisition.send(
            "GET",
            f"/account/{uuid4()}/transactions",
            headers=auth_headers(),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "ACC0001"

    def test_absent_account_on_transaction(self) -> None:
        response = ClientRequisition.send(
            "POST",
            f"/account/{uuid4()}/transaction",
            payload={"transaction_type": "DEPOSIT", "amount_cents": 50_000},
            headers=auth_headers({"Idempotency-Key": str(uuid4())}),
        )

        assert response.response_status == 404
        assert response.response_json["code"] == "ACC0001"
