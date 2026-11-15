"""COD-03 — envelope de erro de domínio e mapeamento, pela rede.

Cobre a correspondência exceção-de-domínio -> contrato HTTP que pode ser
disparada sem semeadura pesada, estritamente conforme ``docs/ROTAS.md``
seção 5. Em cada falha confirma-se que o envelope tem EXATAMENTE as chaves
``{title, description, translation, code}`` (ROTAS 2.2) e que o código é um
dos publicados — QIT000001, CLI0006, CLI0007, CLI0008 — sem inventar nada.

Tudo via ``ClientRequisition.send`` por HTTP; nada importado de ``src/`` e sem
acesso a banco. E-mails/CPF/CNPJ são únicos por chamada (determinísticos).
"""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from tests.utils.requisition import ClientRequisition

from .support import (
    ERROR_ENVELOPE_FIELDS,
    auth_headers,
    company_payload,
    individual_payload,
)


def _assert_envelope(response, *, status: int, code: str) -> None:
    assert response.response_status == status
    body = response.response_json
    assert body is not None
    # ROTAS 2.2: o envelope de erro tem EXATAMENTE estas quatro chaves.
    assert set(body) == ERROR_ENVELOPE_FIELDS
    assert body["code"] == code
    # title/description/translation são texto humano não vazio.
    for field in ("title", "description", "translation"):
        assert isinstance(body[field], str)
        assert body[field].strip() != ""


class TestClientCreationErrorEnvelope:
    def test_malformed_body_is_bad_request(self) -> None:
        response = ClientRequisition.send(
            "POST",
            "/client",
            payload={"client_type": "INDIVIDUAL"},
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="QIT000001")

    def test_non_json_mapping_body_is_bad_request(self) -> None:
        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=["not", "an", "object"],
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="QIT000001")

    def test_invalid_cpf_check_digits_maps_to_cli0006(self) -> None:
        payload = individual_payload()
        # CPF estruturalmente plausível mas com dígito verificador quebrado.
        payload["cpf"] = "529.982.247-26"

        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=payload,
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="CLI0006")

    def test_invalid_cnpj_check_digits_maps_to_cli0006(self) -> None:
        payload = company_payload()
        digits = (
            payload["cnpj"].replace(".", "").replace("/", "").replace("-", "")
        )
        broken_last = (int(digits[-1]) + 1) % 10
        payload["cnpj"] = f"{digits[:-1]}{broken_last}"

        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=payload,
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="CLI0006")

    def test_unsupported_timezone_maps_to_cli0008(self) -> None:
        payload = individual_payload()
        payload["timezone"] = "Europe/London"

        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=payload,
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="CLI0008")

    def test_underage_individual_maps_to_cli0007(self) -> None:
        payload = individual_payload()
        today = datetime.now(ZoneInfo(payload["timezone"])).date()
        # Nasceu ontem há 17 anos: comprovadamente menor de 18.
        payload["birth_date"] = (
            today.replace(year=today.year - 17) + timedelta(days=1)
        ).isoformat()

        response = ClientRequisition.send(
            "POST",
            "/client",
            payload=payload,
            headers=auth_headers(),
        )

        _assert_envelope(response, status=422, code="CLI0007")


class TestTransactionHeaderContract:
    """R07: Idempotency-Key é header obrigatório (ROTAS §R07)."""

    def test_transaction_without_idempotency_key_is_bad_request(self) -> None:
        # Conta inexistente, mas o header ausente é verificado como parte do
        # contrato de entrada: ROTAS documenta 400 para header/body inválido.
        response = ClientRequisition.send(
            "POST",
            f"/account/{uuid4()}/transaction",
            payload={"transaction_type": "DEPOSIT", "amount_cents": 50_000},
            headers=auth_headers(),
        )

        _assert_envelope(response, status=400, code="QIT000001")

    def test_transaction_with_malformed_idempotency_key_is_bad_request(
        self,
    ) -> None:
        response = ClientRequisition.send(
            "POST",
            f"/account/{uuid4()}/transaction",
            payload={"transaction_type": "DEPOSIT", "amount_cents": 50_000},
            headers=auth_headers({"Idempotency-Key": "not-a-uuid"}),
        )

        _assert_envelope(response, status=400, code="QIT000001")


class TestStatementQueryContract:
    """R08: parâmetros de consulta fora do formato -> 400 QIT000001."""

    @pytest.mark.parametrize(
        "query_params",
        [
            {"page": "0"},
            {"limit": "0"},
            {"limit": "101"},
            {"order_by": "ASC"},
            {"unknown": "1"},
            {"date_from": "2026-13-01"},
        ],
        ids=[
            "page-below-min",
            "limit-below-min",
            "limit-above-max",
            "uppercase-order",
            "unknown-param",
            "impossible-date",
        ],
    )
    def test_invalid_query_params_are_bad_request(
        self, query_params: dict
    ) -> None:
        # A validação de parâmetros ocorre antes da resolução do recurso, então
        # um account_key válido-mas-inexistente ainda exercita o contrato.
        response = ClientRequisition.send(
            "GET",
            f"/account/{uuid4()}/transactions",
            headers=auth_headers(),
            query_params=query_params,
        )

        _assert_envelope(response, status=400, code="QIT000001")
