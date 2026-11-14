"""Cen?rios de R04 organizados por comportamento."""

from .support import *


def test_create_account_for_active_individual_returns_201(
    api_database_engine: Engine,
) -> None:
    email = f"r04.account.{uuid4()}@example.com"
    client_payload = {
        "client_type": "INDIVIDUAL",
        "email": email,
        "cpf": RandomGenerator.generate_cpf(),
        "full_name": "Cliente R04 Teste",
        "birth_date": "1990-05-17",
        "timezone": "America/Sao_Paulo",
    }

    client_response = ClientRequisition.send(
        "POST",
        "/client",
        payload=client_payload,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert client_response.response_status == 201

    client_key = client_response.response_json["client_key"]
    assert client_response.response_json["status"] == "PENDING"

    _prepare_client_as_active(
        api_database_engine,
        client_key,
        email,
        expected_client_type="INDIVIDUAL",
    )

    account_response = ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    _assert_created_account_response(account_response, client_key)


def test_create_account_for_active_company_returns_public_contract(
    api_database_engine: Engine,
) -> None:
    email = f"r04.company.account.{uuid4()}@example.com"
    client_payload = {
        "client_type": "COMPANY",
        "email": email,
        "cnpj": RandomGenerator.generate_cnpj(),
        "legal_name": "Empresa R04 Teste Ltda.",
        "trade_name": "Empresa R04",
        "timezone": "America/Sao_Paulo",
    }

    client_response = ClientRequisition.send(
        "POST",
        "/client",
        payload=client_payload,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert client_response.response_status == 201

    client_key = client_response.response_json["client_key"]
    assert client_response.response_json["status"] == "PENDING"

    _prepare_client_as_active(
        api_database_engine,
        client_key,
        email,
        expected_client_type="COMPANY",
    )

    account_response = ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    _assert_created_account_response(account_response, client_key)


def test_create_account_persists_account_and_initial_status_event(
    api_database_engine: Engine,
) -> None:
    email = f"r04.persistence.{uuid4()}@example.com"
    client_response = ClientRequisition.send(
        "POST",
        "/client",
        payload={
            "client_type": "INDIVIDUAL",
            "email": email,
            "cpf": RandomGenerator.generate_cpf(),
            "full_name": "Cliente R04 Persistencia",
            "birth_date": "1990-05-17",
            "timezone": "America/Sao_Paulo",
        },
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert client_response.response_status == 201

    client_key = client_response.response_json["client_key"]
    _prepare_client_as_active(
        api_database_engine,
        client_key,
        email,
        expected_client_type="INDIVIDUAL",
    )

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        client_before = connection.execute(
            text(
                """
                SELECT client.id, client.status_id,
                       status.enumerator AS status, client.updated_at,
                       COUNT(event.id) AS status_event_count
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                LEFT JOIN client_status_event AS event ON event.client_id = client.id
                WHERE client.client_key = CAST(:client_key AS uuid)
                GROUP BY client.id, client.status_id, status.enumerator, client.updated_at
                """
            ),
            {"client_key": client_key},
        ).mappings().one()
        assert client_before["status"] == "ACTIVE"
        assert client_before["status_event_count"] == 2

    account_response = ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    _assert_created_account_response(account_response, client_key)
    account_key = account_response.response_json["account_key"]

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        accounts = connection.execute(
            text(
                """
                SELECT account.id, account.account_key::text AS account_key,
                       client.client_key::text AS client_key,
                       account.balance_cents,
                       status.enumerator AS status,
                       account.created_at, account.updated_at
                FROM account
                JOIN client ON client.id = account.client_id
                JOIN account_status AS status ON status.id = account.status_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                """
            ),
            {"client_key": client_key},
        ).mappings().all()

        assert len(accounts) == 1
        account = accounts[0]
        assert account["account_key"] == account_key
        assert account["client_key"] == client_key
        assert account["status"] == "ACTIVE"
        assert type(account["balance_cents"]) is int
        assert account["balance_cents"] == 0
        for timestamp_name in ("created_at", "updated_at"):
            timestamp = account[timestamp_name]
            assert isinstance(timestamp, datetime)
            assert timestamp.tzinfo is not None
            assert timestamp.utcoffset() == timezone.utc.utcoffset(timestamp)

        client_after = connection.execute(
            text(
                """
                SELECT client.status_id, status.enumerator AS status,
                       client.updated_at, COUNT(event.id) AS status_event_count
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                LEFT JOIN client_status_event AS event ON event.client_id = client.id
                WHERE client.id = :client_id
                GROUP BY client.status_id, status.enumerator, client.updated_at
                """
            ),
            {"client_id": client_before["id"]},
        ).mappings().one()
        assert client_after["status_id"] == client_before["status_id"]
        assert client_after["status"] == client_before["status"]
        assert client_after["updated_at"] == client_before["updated_at"]
        assert client_after["status_event_count"] == client_before["status_event_count"]

        events = connection.execute(
            text(
                """
                SELECT event.account_id, event.from_status_id,
                       destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type,
                       event.reason, event.created_at
                FROM account_status_event AS event
                JOIN account_status AS destination
                  ON destination.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE event.account_id = :account_id
                """
            ),
            {"account_id": account["id"]},
        ).mappings().all()

        financial_counts = connection.execute(
            text(
                """
                SELECT COUNT(entry.id) AS entry_count,
                       COUNT(DISTINCT transaction.id) AS transaction_count
                FROM transaction_entry AS entry
                LEFT JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                WHERE entry.account_id = :account_id
                """
            ),
            {"account_id": account["id"]},
        ).mappings().one()
        assert financial_counts["entry_count"] == 0
        assert financial_counts["transaction_count"] == 0

    assert len(events) == 1
    event = events[0]
    assert event["account_id"] == account["id"]
    assert event["from_status_id"] is None
    assert event["to_status"] == "ACTIVE"
    assert event["actor_type"] == "SYSTEM"
    assert event["reason"] is None
    assert isinstance(event["created_at"], datetime)
    assert event["created_at"].tzinfo is not None
    assert event["created_at"].utcoffset() == timezone.utc.utcoffset(
        event["created_at"]
    )
