"""Helpers coesos e locais da rota R04."""

from .base import *


def _prepare_client_as_active(
    engine: Engine,
    client_key: str,
    expected_email: str,
    expected_client_type: str,
) -> None:
    """Transiciona somente o CLIENT recém-criado e registra seu evento."""
    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT c.id, c.email,
                       client_type.enumerator AS client_type,
                       s.id AS status_id,
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
        assert client["client_type"] == expected_client_type
        assert client["status"] == "PENDING"

        initial_event = connection.execute(
            text(
                """
                SELECT e.from_status_id, destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, e.reason
                FROM client_status_event AS e
                JOIN client_status AS destination
                  ON destination.id = e.to_status_id
                JOIN actor_type ON actor_type.id = e.actor_type_id
                WHERE e.client_id = :client_id
                """
            ),
            {"client_id": client["id"]},
        ).mappings().all()
        assert len(initial_event) == 1
        assert initial_event[0]["from_status_id"] is None
        assert initial_event[0]["to_status"] == "PENDING"
        assert initial_event[0]["actor_type"] == "SYSTEM"
        assert initial_event[0]["reason"] is None

        assert connection.execute(
            text("SELECT id FROM client_status WHERE enumerator = 'ACTIVE'")
        ).scalar_one()

        account_count = connection.execute(
            text("SELECT COUNT(*) FROM account WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one()
        assert account_count == 0

        transition_time = datetime.now(timezone.utc)
        update_result = connection.execute(
            text(
                """
                UPDATE client
                SET status_id = (
                    SELECT id FROM client_status WHERE enumerator = 'ACTIVE'
                ), updated_at = :updated_at
                WHERE id = :client_id AND client_key = CAST(:client_key AS uuid)
                  AND status_id = :previous_status_id
                """
            ),
            {
                "updated_at": transition_time,
                "client_id": client["id"],
                "client_key": client_key,
                "previous_status_id": client["status_id"],
            },
        )
        assert update_result.rowcount == 1

        event_result = connection.execute(
            text(
                """
                INSERT INTO client_status_event (
                    client_id, from_status_id, to_status_id,
                    actor_type_id, reason, created_at
                )
                SELECT :client_id, :from_status_id, destination.id,
                       (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                       NULL, :created_at
                FROM client_status AS destination
                WHERE destination.enumerator = 'ACTIVE'
                """
            ),
            {
                "client_id": client["id"],
                "from_status_id": client["status_id"],
                "created_at": transition_time,
            },
        )
        assert event_result.rowcount == 1

        current_status = connection.execute(
            text(
                """
                SELECT status.enumerator
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                WHERE client.id = :client_id
                """
            ),
            {"client_id": client["id"]},
        ).scalar_one()
        assert current_status == "ACTIVE"

        event_count = connection.execute(
            text("SELECT COUNT(*) FROM client_status_event WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one()
        assert event_count == 2

        transition_event = connection.execute(
            text(
                """
                SELECT source.enumerator AS from_status,
                       destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, event.reason
                FROM client_status_event AS event
                LEFT JOIN client_status AS source
                  ON source.id = event.from_status_id
                JOIN client_status AS destination
                  ON destination.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE event.client_id = :client_id
                  AND event.from_status_id IS NOT NULL
                """
            ),
            {"client_id": client["id"]},
        ).mappings().one()
        assert transition_event["from_status"] == "PENDING"
        assert transition_event["to_status"] == "ACTIVE"
        assert transition_event["actor_type"] == "INTERNAL"
        assert transition_event["reason"] is None


def _transition_client_status(
    engine: Engine,
    client_key: str,
    expected_email: str,
    expected_client_type: str,
    expected_status: str,
    next_status: str,
    reason: str,
) -> None:
    """Prepara uma transição de CLIENT exclusiva para o cenário de teste."""
    with engine.begin() as connection:
        client = connection.execute(
            text(
                """
                SELECT c.id, c.email,
                       client_type.enumerator AS client_type,
                       c.status_id,
                       status.enumerator AS status
                FROM client AS c
                JOIN client_status AS status ON status.id = c.status_id
                JOIN client_type ON client_type.id = c.client_type_id
                WHERE c.client_key = CAST(:client_key AS uuid)
                """
            ),
            {"client_key": client_key},
        ).mappings().one()

        assert client["email"] == expected_email
        assert client["client_type"] == expected_client_type
        assert client["status"] == expected_status
        assert connection.execute(
            text("SELECT COUNT(*) FROM account WHERE client_id = :client_id"),
            {"client_id": client["id"]},
        ).scalar_one() == 0

        next_status_id = connection.execute(
            text("SELECT id FROM client_status WHERE enumerator = :status"),
            {"status": next_status},
        ).scalar_one()
        transition_time = datetime.now(timezone.utc)
        update_result = connection.execute(
            text(
                """
                UPDATE client
                SET status_id = :next_status_id, updated_at = :updated_at
                WHERE id = :client_id
                  AND client_key = CAST(:client_key AS uuid)
                  AND status_id = :previous_status_id
                """
            ),
            {
                "next_status_id": next_status_id,
                "updated_at": transition_time,
                "client_id": client["id"],
                "client_key": client_key,
                "previous_status_id": client["status_id"],
            },
        )
        assert update_result.rowcount == 1

        event_result = connection.execute(
            text(
                """
                INSERT INTO client_status_event (
                    client_id, from_status_id, to_status_id,
                    actor_type_id, reason, created_at
                ) VALUES (
                    :client_id, :from_status_id, :to_status_id,
                    (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                    :reason, :created_at
                )
                """
            ),
            {
                "client_id": client["id"],
                "from_status_id": client["status_id"],
                "to_status_id": next_status_id,
                "reason": reason,
                "created_at": transition_time,
            },
        )
        assert event_result.rowcount == 1


def _create_pending_individual() -> tuple[str, str]:
    email = f"r04.account.error.{uuid4()}@example.com"
    response = ClientRequisition.send(
        "POST",
        "/client",
        payload={
            "client_type": "INDIVIDUAL",
            "email": email,
            "cpf": RandomGenerator.generate_cpf(),
            "full_name": "Cliente R04 Erro",
            "birth_date": "1990-05-17",
            "timezone": "America/Sao_Paulo",
        },
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
    )
    assert response.response_status == 201
    return response.response_json["client_key"], email


def _close_account_and_inactivate_client(engine: Engine, client_key: str) -> None:
    """Prepara o histórico F02 ACTIVE/ACTIVE -> INACTIVE/CLOSED."""
    with engine.begin() as connection:
        persisted = connection.execute(
            text(
                """
                SELECT client.id AS client_id, client.status_id AS client_status_id,
                       account.id AS account_id, account.status_id AS account_status_id,
                       account.balance_cents
                FROM client
                JOIN account ON account.client_id = client.id
                WHERE client.client_key = CAST(:client_key AS uuid)
                """
            ),
            {"client_key": client_key},
        ).mappings().one()
        assert persisted["balance_cents"] == 0

        statuses = connection.execute(
            text(
                """
                SELECT enumerator, id
                FROM client_status
                WHERE enumerator IN ('ACTIVE', 'INACTIVE')
                """
            )
        ).mappings().all()
        client_status_ids = {status["enumerator"]: status["id"] for status in statuses}
        account_status_ids = {
            status["enumerator"]: status["id"]
            for status in connection.execute(
                text(
                    """
                    SELECT enumerator, id
                    FROM account_status
                    WHERE enumerator IN ('ACTIVE', 'CLOSED')
                    """
                )
            ).mappings()
        }
        assert persisted["client_status_id"] == client_status_ids["ACTIVE"]
        assert persisted["account_status_id"] == account_status_ids["ACTIVE"]

        transition_time = datetime.now(timezone.utc)
        reason = "Encerramento controlado do cenário R04"
        account_update = connection.execute(
            text(
                """
                UPDATE account
                SET status_id = :closed_status_id, updated_at = :updated_at
                WHERE id = :account_id AND status_id = :active_status_id
                """
            ),
            {
                "closed_status_id": account_status_ids["CLOSED"],
                "updated_at": transition_time,
                "account_id": persisted["account_id"],
                "active_status_id": account_status_ids["ACTIVE"],
            },
        )
        assert account_update.rowcount == 1
        account_event = connection.execute(
            text(
                """
                INSERT INTO account_status_event (
                    account_id, from_status_id, to_status_id,
                    actor_type_id, reason, created_at
                ) VALUES (
                    :account_id, :from_status_id, :to_status_id,
                    (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                    :reason, :created_at
                )
                """
            ),
            {
                "account_id": persisted["account_id"],
                "from_status_id": account_status_ids["ACTIVE"],
                "to_status_id": account_status_ids["CLOSED"],
                "reason": reason,
                "created_at": transition_time,
            },
        )
        assert account_event.rowcount == 1
        client_update = connection.execute(
            text(
                """
                UPDATE client
                SET status_id = :inactive_status_id, updated_at = :updated_at
                WHERE id = :client_id AND status_id = :active_status_id
                """
            ),
            {
                "inactive_status_id": client_status_ids["INACTIVE"],
                "updated_at": transition_time,
                "client_id": persisted["client_id"],
                "active_status_id": client_status_ids["ACTIVE"],
            },
        )
        assert client_update.rowcount == 1
        client_event = connection.execute(
            text(
                """
                INSERT INTO client_status_event (
                    client_id, from_status_id, to_status_id,
                    actor_type_id, reason, created_at
                ) VALUES (
                    :client_id, :from_status_id, :to_status_id,
                    (SELECT id FROM actor_type WHERE enumerator = 'INTERNAL'),
                    :reason, :created_at
                )
                """
            ),
            {
                "client_id": persisted["client_id"],
                "from_status_id": client_status_ids["ACTIVE"],
                "to_status_id": client_status_ids["INACTIVE"],
                "reason": reason,
                "created_at": transition_time,
            },
        )
        assert client_event.rowcount == 1

__all__ = [name for name in globals() if not name.startswith("__")]
