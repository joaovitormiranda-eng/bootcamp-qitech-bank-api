"""Fluxos APPROVE e REJECT da R03."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.client.r03.support import (
    analyze_client,
    create_pending_company,
    create_pending_individual,
    expect_client_analysis,
    provider_request,
)
from tests.utils.mockserver import MockServer


def test_approve_pending_client_updates_status_and_creates_event(
    app_db_engine: Engine,
) -> None:
    MockServer.reset()

    client_key, normalized_cpf = create_pending_individual()
    expected_provider_request = provider_request(
        client_key,
        "INDIVIDUAL",
        normalized_cpf,
    )
    expect_client_analysis(
        expected_request=expected_provider_request,
        decision="APPROVE",
        reason=None,
    )

    analysis_response = analyze_client(client_key)

    assert analysis_response.response_status == 200
    assert analysis_response.response_json == {
        "client_key": client_key,
        "status": "ACTIVE",
    }
    MockServer.verify_exactly(expected_provider_request, count=1)

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        client = connection.execute(
            text("""
                SELECT c.id, current_status.enumerator AS status,
                       c.created_at, c.updated_at
                FROM client AS c
                JOIN client_status AS current_status
                  ON current_status.id = c.status_id
                WHERE c.client_key = CAST(:client_key AS uuid)
            """),
            {"client_key": client_key},
        ).mappings().one()

        events = connection.execute(
            text("""
                SELECT previous_status.enumerator AS from_status,
                       next_status.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, event.reason
                FROM client_status_event AS event
                LEFT JOIN client_status AS previous_status
                  ON previous_status.id = event.from_status_id
                JOIN client_status AS next_status
                  ON next_status.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE event.client_id = :client_id
                ORDER BY event.created_at, event.id
            """),
            {"client_id": client["id"]},
        ).mappings().all()

    assert client["status"] == "ACTIVE"
    assert client["updated_at"] >= client["created_at"]
    assert [dict(event) for event in events] == [
        {
            "from_status": None,
            "to_status": "PENDING",
            "actor_type": "SYSTEM",
            "reason": None,
        },
        {
            "from_status": "PENDING",
            "to_status": "ACTIVE",
            "actor_type": "INTERNAL",
            "reason": None,
        },
    ]


def test_reject_pending_client_persists_reason_in_status_event(
    app_db_engine: Engine,
) -> None:
    MockServer.reset()

    client_key, normalized_cnpj = create_pending_company()
    expected_provider_request = provider_request(
        client_key,
        "COMPANY",
        normalized_cnpj,
    )
    provider_reason = "  Cadastro nao aprovado  "
    persisted_reason = "Cadastro nao aprovado"
    expect_client_analysis(
        expected_request=expected_provider_request,
        decision="REJECT",
        reason=provider_reason,
    )

    analysis_response = analyze_client(client_key)

    assert analysis_response.response_status == 200
    assert analysis_response.response_json == {
        "client_key": client_key,
        "status": "REJECTED",
    }
    MockServer.verify_exactly(expected_provider_request, count=1)

    with app_db_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        lifecycle = connection.execute(
            text("""
                SELECT current_status.enumerator AS status,
                       previous_status.enumerator AS from_status,
                       next_status.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, event.reason
                FROM client AS client
                JOIN client_status AS current_status
                  ON current_status.id = client.status_id
                JOIN client_status_event AS event
                  ON event.client_id = client.id
                LEFT JOIN client_status AS previous_status
                  ON previous_status.id = event.from_status_id
                JOIN client_status AS next_status
                  ON next_status.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                  AND previous_status.enumerator = 'PENDING'
            """),
            {"client_key": client_key},
        ).mappings().one()

    assert dict(lifecycle) == {
        "status": "REJECTED",
        "from_status": "PENDING",
        "to_status": "REJECTED",
        "actor_type": "INTERNAL",
        "reason": persisted_reason,
    }
