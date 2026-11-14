from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from os import environ
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from tests.utils import DbUtils, INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


INDIVIDUAL_RESPONSE_FIELDS = {
    "client_key",
    "client_type",
    "email",
    "timezone",
    "status",
    "cpf",
    "full_name",
    "birth_date",
    "created_at",
    "updated_at",
}

COMPANY_RESPONSE_FIELDS = {
    "client_key",
    "client_type",
    "email",
    "timezone",
    "status",
    "cnpj",
    "legal_name",
    "trade_name",
    "created_at",
    "updated_at",
}


def _assert_utc_timestamp(value: str) -> None:
    assert value.endswith("Z")

    parsed_value = datetime.fromisoformat(f"{value[:-1]}+00:00")
    assert parsed_value.utcoffset() == timedelta(0)


def _assert_error_response(response, status_code: int, error_code: str) -> None:
    assert response.response_status == status_code
    response_body = response.response_json
    assert isinstance(response_body, dict)
    assert set(response_body) == {"title", "description", "translation", "code"}
    assert response_body["code"] == error_code
    for field in ("title", "description", "translation"):
        assert isinstance(response_body[field], str)
        assert response_body[field].strip()


@pytest.fixture(scope="module")
def existing_individual_client_key() -> str:
    payload = {
        "client_type": "INDIVIDUAL",
        "email": f"r02.auth.{uuid4()}@example.com",
        "cpf": RandomGenerator.generate_cpf(),
        "full_name": "Cliente R02 Autenticacao",
        "birth_date": "2000-01-01",
        "timezone": "America/Sao_Paulo",
    }
    response = ClientRequisition.send(
        "POST",
        "/client",
        payload=payload,
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )

    assert response.response_status == 201
    client_key = response.response_json["client_key"]
    assert isinstance(UUID(client_key), UUID)
    return client_key


@pytest.fixture(scope="module")
def api_database_engine() -> Iterator[Engine]:
    """Conecta ao mesmo PostgreSQL local usado pela API, nunca ao schema de teste."""
    api_url = make_url(DbUtils.database_url())
    raw_test_url = environ.get("TEST_DATABASE_URL")

    assert api_url.database == "bootcamp"
    assert api_url.host in {"localhost", "127.0.0.1"}
    if raw_test_url:
        test_url = make_url(raw_test_url)
        assert test_url.database and test_url.database.endswith("_test")
        assert api_url != test_url

    engine = create_engine(api_url)
    try:
        with engine.connect() as connection:
            database_identity = connection.execute(
                text(
                    """
                    SELECT current_database(),
                           (SELECT system_identifier
                            FROM pg_control_system())::text,
                           inet_server_port()
                    """
                )
            ).one()

        assert database_identity[0] == "bootcamp"
        assert database_identity[1]
        assert database_identity[2] == 5432

        yield engine
    finally:
        engine.dispose()


def _prepare_client_status(
    engine: Engine,
    client_key: str,
    expected_email: str,
    target_status: str,
) -> None:
    transition_paths = {
        "ACTIVE": [("PENDING", "ACTIVE", None)],
        "REJECTED": [
            (
                "PENDING",
                "REJECTED",
                "Rejeição controlada no teste de integração.",
            )
        ],
        "INACTIVE": [
            ("PENDING", "ACTIVE", None),
            (
                "ACTIVE",
                "INACTIVE",
                "Inativação controlada no teste de integração.",
            ),
        ],
    }
    transitions = transition_paths[target_status]

    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT c.id, c.email,
                       client_type.enumerator AS client_type,
                       s.enumerator AS status
                FROM client AS c
                JOIN client_status AS s ON s.id = c.status_id
                JOIN client_type ON client_type.id = c.client_type_id
                WHERE c.client_key = CAST(:client_key AS uuid)
                """
            ),
            {"client_key": client_key},
        ).mappings().one()

        assert client["email"] == expected_email
        assert client["client_type"] == "INDIVIDUAL"
        assert client["status"] == "PENDING"

        initial_events = connection.execute(
            text(
                """
                SELECT e.from_status_id, to_status.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, e.reason
                FROM client_status_event AS e
                JOIN client_status AS to_status
                  ON to_status.id = e.to_status_id
                JOIN actor_type ON actor_type.id = e.actor_type_id
                WHERE e.client_id = :client_id
                """
            ),
            {"client_id": client["id"]},
        ).mappings().all()
        assert len(initial_events) == 1
        assert initial_events[0]["from_status_id"] is None
        assert initial_events[0]["to_status"] == "PENDING"
        assert initial_events[0]["actor_type"] == "SYSTEM"
        assert initial_events[0]["reason"] is None

        account_count = connection.execute(
            text("SELECT COUNT(*) FROM account WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one()
        assert account_count == 0

        status_ids = dict(
            connection.execute(
                text(
                    "SELECT enumerator, id FROM client_status "
                    "WHERE enumerator IN "
                    "('PENDING', 'ACTIVE', 'REJECTED', 'INACTIVE')"
                )
            ).all()
        )

        assert set(status_ids) == {"PENDING", "ACTIVE", "REJECTED", "INACTIVE"}

        current_status = "PENDING"
        expected_events = [
            {
                "from_status": None,
                "to_status": "PENDING",
                "actor_type": "SYSTEM",
                "reason": None,
            }
        ]
        transition_time = datetime.now(timezone.utc)
        for index, (from_status, to_status, reason) in enumerate(transitions):
            assert current_status == from_status
            event_time = transition_time + timedelta(microseconds=index)
            update_result = connection.execute(
                text(
                    """
                    UPDATE client
                    SET status_id = :to_status_id, updated_at = :updated_at
                    WHERE id = :client_id AND status_id = :from_status_id
                    """
                ),
                {
                    "to_status_id": status_ids[to_status],
                    "updated_at": event_time,
                    "client_id": client["id"],
                    "from_status_id": status_ids[from_status],
                },
            )
            assert update_result.rowcount == 1

            connection.execute(
                text(
                    """
                    INSERT INTO client_status_event (
                        client_id, from_status_id, to_status_id,
                        actor_type_id, reason, created_at
                    )
                    VALUES (
                        :client_id, :from_status_id, :to_status_id,
                        (SELECT id FROM actor_type
                         WHERE enumerator = 'INTERNAL'),
                        :reason, :created_at
                    )
                    """
                ),
                {
                    "client_id": client["id"],
                    "from_status_id": status_ids[from_status],
                    "to_status_id": status_ids[to_status],
                    "reason": reason,
                    "created_at": event_time,
                },
            )
            current_status = to_status
            expected_events.append(
                {
                    "from_status": from_status,
                    "to_status": to_status,
                    "actor_type": "INTERNAL",
                    "reason": reason,
                }
            )

        persisted_status = connection.execute(
            text(
                """
                SELECT s.enumerator
                FROM client AS c
                JOIN client_status AS s ON s.id = c.status_id
                WHERE c.id = :client_id
                """
            ),
            {"client_id": client["id"]},
        ).scalar_one()
        assert persisted_status == target_status

        event_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM client_status_event "
                "WHERE client_id = :client_id"
            ),
            {"client_id": client["id"]},
        ).scalar_one()
        assert event_count == 1 + len(transitions)

        events = connection.execute(
            text(
                """
                SELECT from_status.enumerator AS from_status,
                       to_status.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, e.reason
                FROM client_status_event AS e
                LEFT JOIN client_status AS from_status
                  ON from_status.id = e.from_status_id
                JOIN client_status AS to_status
                  ON to_status.id = e.to_status_id
                JOIN actor_type ON actor_type.id = e.actor_type_id
                WHERE e.client_id = :client_id
                ORDER BY e.id
                """
            ),
            {"client_id": client["id"]},
        ).mappings().all()
        assert [dict(event) for event in events] == expected_events

__all__ = [name for name in globals() if not name.startswith("__")]
