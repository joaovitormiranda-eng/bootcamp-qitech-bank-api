"""COD-03 — caminhos de erro de domínio exercitados 100% por HTTP (black-box).

A auditoria P1 (COD-03) pontua por fração de erro de domínio efetivamente
disparado por teste; a P1-B e a P1-C deixaram alguns códigos cobertos apenas
de forma MISTA (gatilho HTTP, mas pré-condição/verificação por SQL) ou com um
único ponto de disparo. Este módulo fecha duas lacunas reais sem tocar lógica
financeira, SQL de produção ou controllers:

  - ACC0002 (AccountAlreadyExists, 409): até aqui só referenciado dentro de um
    helper de suporte da R04; não havia teste nomeado disparando a abertura de
    uma SEGUNDA conta para o mesmo cliente. Aqui o cenário inteiro (criar
    cliente, aprovar na R03 via MockServer, abrir conta, tentar abrir de novo)
    roda apenas pela rede.

  - TRX0002 (SelfTransferNotAllowed, 409): existia um único teste, porém MISTO
    (conta sem fundos semeada por SQL para poder asserir extrato vazio). Esta é
    a variante PURA black-box: conta ACTIVE com saldo semeado via R07 DEPOSIT
    pela API, transferência para si mesma, e asserção só do contrato de erro.

Regras de disciplina do arquivo (COD-04/08/14):
  - NÃO importa nada de ``src``.
  - NÃO acessa o banco: toda preparação e verificação é por ``ClientRequisition``.
  - Reusa os blocos HTTP já existentes em ``support.py`` e no suporte da R03.
  - Asserções restritas a status HTTP, ``code`` publicado e envelope de erro;
    nenhuma mudança de semântica financeira.
"""

from uuid import uuid4

from tests.integration.client.r03.support import (
    analyze_client,
    expect_client_analysis,
    provider_request,
)
from tests.integration.transaction.support import (
    open_funded_account_via_api,
    send_transfer,
)
from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.mockserver import MockServer
from tests.utils.requisition import ClientRequisition


ERROR_ENVELOPE_FIELDS = {"title", "description", "translation", "code"}


def _auth_headers(extra: dict | None = None) -> dict:
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
    if extra:
        headers.update(extra)
    return headers


def _create_active_individual_via_api() -> str:
    """Cria um cliente PF e o leva a ACTIVE só por HTTP; devolve o client_key.

    Equivale à primeira metade de ``open_funded_account_via_api``, mas devolve
    o ``client_key`` (e não a ``account_key``), porque os testes abaixo
    precisam operar sobre o cliente — inclusive abrir conta duas vezes.
    """
    cpf = RandomGenerator.generate_cpf()
    normalized_cpf = cpf.replace(".", "").replace("-", "")
    client_payload = {
        "client_type": "INDIVIDUAL",
        "email": f"r04.negative.{uuid4()}@example.com",
        "cpf": cpf,
        "full_name": "Cliente R04 Negative",
        "birth_date": "1990-05-17",
        "timezone": "America/Sao_Paulo",
    }

    MockServer.reset()
    try:
        client_response = ClientRequisition.send(
            "POST",
            "/client",
            payload=client_payload,
            headers=_auth_headers(),
        )
        assert client_response.response_status == 201, (
            f"R01 failed: {client_response.response_status} "
            f"{client_response.response_content!r}"
        )
        client_key = client_response.response_json["client_key"]

        expect_client_analysis(
            expected_request=provider_request(
                client_key,
                "INDIVIDUAL",
                normalized_cpf,
            ),
            decision="APPROVE",
            reason=None,
        )
        analysis_response = analyze_client(client_key)
        assert analysis_response.response_status == 200, (
            f"R03 failed: {analysis_response.response_status} "
            f"{analysis_response.response_content!r}"
        )
        assert analysis_response.response_json["status"] == "ACTIVE"
    finally:
        MockServer.reset()

    return client_key


def _open_account(client_key: str):
    return ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers=_auth_headers(),
    )


class TestAccountAlreadyExistsBlackBox:
    """R04: um cliente só pode ter uma conta — a segunda abertura é 409 ACC0002."""

    def test_second_account_opening_is_conflict(self):
        client_key = _create_active_individual_via_api()

        first = _open_account(client_key)
        assert first.response_status == 201, (
            f"primeira abertura deveria ser 201: {first.response_status} "
            f"{first.response_content!r}"
        )

        second = _open_account(client_key)

        assert second.response_status == 409
        body = second.response_json
        assert body["code"] == "ACC0002"
        assert ERROR_ENVELOPE_FIELDS <= set(body)

    def test_second_account_opening_does_not_create_a_new_account(self):
        """O conflito não deixa o cliente com duas contas: a chave não muda."""
        client_key = _create_active_individual_via_api()

        first = _open_account(client_key)
        assert first.response_status == 201
        first_account_key = first.response_json["account_key"]

        conflict = _open_account(client_key)
        assert conflict.response_status == 409
        assert conflict.response_json["code"] == "ACC0002"

        # A conta visível na R05 continua sendo a primeira, provando que a
        # tentativa recusada não criou um segundo registro.
        snapshot = ClientRequisition.send(
            "GET",
            f"/account/{first_account_key}",
            headers=_auth_headers(),
        )
        assert snapshot.response_status == 200
        assert snapshot.response_json["account_key"] == first_account_key


class TestSelfTransferBlackBox:
    """R07: transferência para a própria conta é 409 TRX0002, por HTTP puro."""

    def test_self_transfer_is_rejected(self):
        account_key = open_funded_account_via_api(balance_cents=100_000)

        response = send_transfer(
            account_key,
            account_key,
            uuid4(),
            amount_cents=50_000,
        )

        assert response.response_status == 409
        body = response.response_json
        assert body["code"] == "TRX0002"
        assert ERROR_ENVELOPE_FIELDS <= set(body)
