"""Integração do snapshot público de ACCOUNT."""

from collections.abc import Iterator
from datetime import datetime, timezone
from os import environ
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from tests.utils import DbUtils, INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


ACCOUNT_RESPONSE_FIELDS = {
    "account_key",
    "client_key",
    "status",
    "balance_cents",
    "created_at",
    "updated_at",
}
INVALID_ACCOUNT_KEY_ERROR = {
    "title": "Bad Request",
    "description": "account_key must be a valid UUID",
    "translation": "Payload Inválido",
    "code": "QIT000001",
}
FORBIDDEN_ERROR = {
    "title": "Forbidden",
    "description": "Request must be internal",
    "translation": "Requisição precisa ser interna",
    "code": "QIT000002",
}


@pytest.fixture(scope="module")
def api_database_engine() -> Iterator[Engine]:
    """Conecta somente ao banco local da API, separado do banco de schema."""
    api_url = make_url(DbUtils.database_url())
    test_url = make_url(environ["TEST_DATABASE_URL"])

    assert api_url.database == "bootcamp"
    assert api_url.host in {"localhost", "127.0.0.1"}
    assert test_url.database == "bootcamp_test"
    assert test_url.host in {"localhost", "127.0.0.1"}
    assert api_url != test_url

    engine = create_engine(api_url)
    try:
        with engine.connect() as connection:
            api_identity = connection.execute(
                text(
                    "SELECT current_database(), "
                    "(SELECT system_identifier::text FROM pg_control_system())"
                )
            ).one()

        test_engine = create_engine(test_url)
        try:
            with test_engine.connect() as connection:
                test_identity = connection.execute(
                    text(
                        "SELECT current_database(), "
                        "(SELECT system_identifier::text FROM pg_control_system())"
                    )
                ).one()
        finally:
            test_engine.dispose()

        assert api_identity[0] == "bootcamp"
        assert test_identity[0] == "bootcamp_test"
        assert api_identity[1] != test_identity[1]
        yield engine
    finally:
        engine.dispose()


def _assert_utc_timestamp(value: str) -> None:
    assert isinstance(value, str)
    assert value.endswith("Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _assert_error_response(response, status: int, expected: dict) -> None:
    assert response.response_status == status
    assert response.response.headers["content-type"].startswith("application/json")
    assert response.response_json == expected


def _create_active_account(engine: Engine, client_type: str) -> tuple[str, str]:
    email = f"r05.{client_type.lower()}.{uuid4()}@example.com"
    if client_type == "INDIVIDUAL":
        payload = {
            "client_type": client_type,
            "email": email,
            "cpf": RandomGenerator.generate_cpf(),
            "full_name": "Cliente R05 Individual",
            "birth_date": "1990-05-17",
            "timezone": "America/Sao_Paulo",
        }
    else:
        payload = {
            "client_type": client_type,
            "email": email,
            "cnpj": RandomGenerator.generate_cnpj(),
            "legal_name": "Empresa R05 Ltda.",
            "trade_name": "Empresa R05",
            "timezone": "America/Sao_Paulo",
        }

    client_response = ClientRequisition.send(
        "POST", "/client", payload=payload, headers={"INTERNAL-TOKEN": INTERNAL_TOKEN}
    )
    assert client_response.response_status == 201
    client_key = client_response.response_json["client_key"]

    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT client.id, client.status_id
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                JOIN client_type ON client_type.id = client.client_type_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                  AND client.email = :email
                  AND client_type.enumerator = :client_type
                  AND status.enumerator = 'PENDING'
                """
            ),
            {"client_key": client_key, "email": email, "client_type": client_type},
        ).mappings().one()
        transition_time = datetime.now(timezone.utc)
        updated = connection.execute(
            text(
                """
                UPDATE client
                SET status_id = (SELECT id FROM client_status WHERE enumerator = 'ACTIVE'),
                    updated_at = :updated_at
                WHERE id = :client_id AND status_id = :pending_status_id
                """
            ),
            {
                "client_id": client["id"],
                "pending_status_id": client["status_id"],
                "updated_at": transition_time,
            },
        )
        assert updated.rowcount == 1
        event = connection.execute(
            text(
                """
                INSERT INTO client_status_event (
                    client_id, from_status_id, to_status_id, actor_type_id, reason, created_at
                )
                SELECT :client_id, :from_status_id, status.id,
                       (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                       NULL, :created_at
                FROM client_status AS status
                WHERE status.enumerator = 'ACTIVE'
                """
            ),
            {
                "client_id": client["id"],
                "from_status_id": client["status_id"],
                "created_at": transition_time,
            },
        )
        assert event.rowcount == 1

    account_response = ClientRequisition.send(
        "POST",
        f"/client/{client_key}/account",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert account_response.response_status == 201
    return client_key, account_response.response_json["account_key"]


def _get_persisted_account(engine: Engine, account_key: str) -> dict:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return connection.execute(
            text(
                """
                SELECT account.id, account.account_key::text AS account_key,
                       client.client_key::text AS client_key,
                       status.enumerator AS status, account.balance_cents,
                       account.created_at, account.updated_at,
                       client.status_id AS client_status_id,
                       client.updated_at AS client_updated_at,
                       (SELECT COUNT(*) FROM account_status_event
                        WHERE account_id = account.id) AS account_event_count,
                       (SELECT COUNT(*) FROM client_status_event
                        WHERE client_id = client.id) AS client_event_count,
                       (SELECT COUNT(*) FROM transaction_entry
                        WHERE account_id = account.id) AS entry_count,
                       (SELECT COUNT(DISTINCT transaction.id)
                        FROM transaction_entry AS entry
                        JOIN financial_transaction AS transaction
                          ON transaction.id = entry.transaction_id
                        WHERE entry.account_id = account.id) AS transaction_count
                FROM account
                JOIN client ON client.id = account.client_id
                JOIN account_status AS status ON status.id = account.status_id
                WHERE account.account_key = CAST(:account_key AS uuid)
                """
            ),
            {"account_key": account_key},
        ).mappings().one()


def _transition_account_status(engine: Engine, account_key: str, target_status: str) -> None:
    with engine.begin() as connection:
        account = connection.execute(
            text(
                """
                SELECT account.id, account.status_id, account.balance_cents
                FROM account
                WHERE account.account_key = CAST(:account_key AS uuid)
                """
            ),
            {"account_key": account_key},
        ).mappings().one()
        assert account["balance_cents"] == 0
        updated_at = datetime.now(timezone.utc)
        updated = connection.execute(
            text(
                """
                UPDATE account
                SET status_id = (SELECT id FROM account_status WHERE enumerator = :target_status),
                    updated_at = :updated_at
                WHERE id = :account_id AND status_id = :previous_status_id
                """
            ),
            {
                "account_id": account["id"],
                "previous_status_id": account["status_id"],
                "target_status": target_status,
                "updated_at": updated_at,
            },
        )
        assert updated.rowcount == 1
        event = connection.execute(
            text(
                """
                INSERT INTO account_status_event (
                    account_id, from_status_id, to_status_id, actor_type_id, reason, created_at
                )
                SELECT :account_id, :from_status_id, status.id,
                       (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                       :reason, :created_at
                FROM account_status AS status
                WHERE status.enumerator = :target_status
                """
            ),
            {
                "account_id": account["id"],
                "from_status_id": account["status_id"],
                "target_status": target_status,
                "reason": "Preparação controlada para R05",
                "created_at": updated_at,
            },
        )
        assert event.rowcount == 1


def _set_account_balance(engine: Engine, account_key: str, balance_cents: int) -> None:
    with engine.begin() as connection:
        updated = connection.execute(
            text(
                """
                UPDATE account
                SET balance_cents = :balance_cents, updated_at = :updated_at
                WHERE account_key = CAST(:account_key AS uuid)
                """
            ),
            {
                "account_key": account_key,
                "balance_cents": balance_cents,
                "updated_at": datetime.now(timezone.utc),
            },
        )
        assert updated.rowcount == 1


def _assert_account_snapshot_response(response, persisted: dict) -> None:
    assert response.response_status == 200
    assert response.response.headers["content-type"].startswith("application/json")
    body = response.response_json
    assert set(body) == ACCOUNT_RESPONSE_FIELDS
    assert str(UUID(body["account_key"])) == persisted["account_key"]
    assert str(UUID(body["client_key"])) == persisted["client_key"]
    assert body["status"] == persisted["status"]
    assert type(body["balance_cents"]) is int
    assert body["balance_cents"] == persisted["balance_cents"]
    _assert_utc_timestamp(body["created_at"])
    _assert_utc_timestamp(body["updated_at"])
    assert body["created_at"] == persisted["created_at"].isoformat().replace("+00:00", "Z")
    assert body["updated_at"] == persisted["updated_at"].isoformat().replace("+00:00", "Z")

__all__ = [name for name in globals() if not name.startswith("__")]
