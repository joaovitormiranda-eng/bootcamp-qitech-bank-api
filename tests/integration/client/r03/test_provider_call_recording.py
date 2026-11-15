"""Confirma via request-recording do MockServer que a R03 chama o provedor real."""

import json

from tests.integration.client.r03.support import (
    analyze_client,
    create_pending_company,
    create_pending_individual,
    expect_client_analysis,
    expect_provider_response,
    provider_request,
)
from tests.utils.mockserver import MockServer


PROVIDER_REQUEST_MATCHER = {
    "method": "POST",
    "path": "/v1/client-analysis",
}


def _extract_recorded_json_body(recorded_request: dict) -> dict:
    """Normaliza o corpo registrado, que pode vir como dict ou string."""
    body = recorded_request.get("body")

    if isinstance(body, dict):
        if "json" in body:
            return body["json"]
        if "string" in body:
            return json.loads(body["string"])
        return body
    if isinstance(body, str):
        return json.loads(body)

    raise AssertionError(f"Corpo registrado inesperado: {body!r}")


def _single_recorded_provider_request() -> dict:
    """Recupera e valida que houve exatamente uma chamada ao provedor."""
    recorded = MockServer.retrieve_recorded_requests(PROVIDER_REQUEST_MATCHER)

    assert isinstance(recorded, list)
    assert len(recorded) == 1

    recorded_request = recorded[0]
    assert recorded_request["method"] == "POST"
    assert recorded_request["path"] == "/v1/client-analysis"
    return recorded_request


def test_approve_records_real_provider_call() -> None:
    MockServer.reset()

    client_key, normalized_cpf = create_pending_individual()
    expected_provider_request = provider_request(
        client_key,
        "INDIVIDUAL",
        normalized_cpf,
    )
    expect_client_analysis(
        expected_provider_request,
        decision="APPROVE",
        reason=None,
    )

    response = analyze_client(client_key)

    assert response.response_status == 200
    assert response.response_json == {
        "client_key": client_key,
        "status": "ACTIVE",
    }

    recorded_request = _single_recorded_provider_request()
    assert _extract_recorded_json_body(recorded_request) == {
        "client_key": client_key,
        "client_type": "INDIVIDUAL",
        "document": normalized_cpf,
    }


def test_reject_records_real_provider_call() -> None:
    MockServer.reset()

    client_key, normalized_cnpj = create_pending_company()
    expected_provider_request = provider_request(
        client_key,
        "COMPANY",
        normalized_cnpj,
    )
    expect_client_analysis(
        expected_provider_request,
        decision="REJECT",
        reason="Cadastro nao aprovado",
    )

    response = analyze_client(client_key)

    assert response.response_status == 200
    assert response.response_json == {
        "client_key": client_key,
        "status": "REJECTED",
    }

    recorded_request = _single_recorded_provider_request()
    assert _extract_recorded_json_body(recorded_request) == {
        "client_key": client_key,
        "client_type": "COMPANY",
        "document": normalized_cnpj,
    }


def test_provider_failure_still_records_real_provider_call() -> None:
    MockServer.reset()

    client_key, normalized_cpf = create_pending_individual()
    expected_provider_request = provider_request(
        client_key,
        "INDIVIDUAL",
        normalized_cpf,
    )
    expect_provider_response(
        expected_request=expected_provider_request,
        response_body={"error": "provider unavailable"},
        status_code=500,
    )

    response = analyze_client(client_key)

    assert response.response_status == 500
    assert response.response_json["code"] == "QIT000500"

    recorded_request = _single_recorded_provider_request()
    assert _extract_recorded_json_body(recorded_request) == {
        "client_key": client_key,
        "client_type": "INDIVIDUAL",
        "document": normalized_cpf,
    }
