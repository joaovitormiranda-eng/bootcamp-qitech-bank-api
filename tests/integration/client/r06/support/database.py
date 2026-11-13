"""Helpers coesos e locais da rota R06."""

from .base import *


@pytest.fixture(scope="module")
def api_database_engine() -> Iterator[Engine]:
    api_url = make_url(DbUtils.database_url())
    test_url = make_url(environ["TEST_DATABASE_URL"])
    assert api_url.database == "bootcamp"
    assert api_url.host in {"localhost", "127.0.0.1"}
    assert test_url.database == "bootcamp_test"
    assert test_url.host in {"localhost", "127.0.0.1"}
    assert api_url != test_url
    engine = create_engine(api_url)
    test_engine = create_engine(test_url)
    try:
        with engine.connect() as connection:
            api_identity = connection.execute(
                text("SELECT (SELECT system_identifier::text FROM pg_control_system())")
            ).scalar_one()
        with test_engine.connect() as connection:
            test_identity = connection.execute(
                text("SELECT (SELECT system_identifier::text FROM pg_control_system())")
            ).scalar_one()
        assert api_identity != test_identity
        yield engine
    finally:
        test_engine.dispose()
        engine.dispose()


def _snapshot(engine: Engine, account_key: str) -> dict:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        row = connection.execute(
            text(
                """
                SELECT account.id AS account_id, client.id AS client_id,
                       account.account_key::text AS account_key,
                       client.client_key::text AS client_key,
                       account_status.enumerator AS account_status,
                       client_status.enumerator AS client_status,
                       account.balance_cents, account.created_at AS account_created_at,
                       account.updated_at AS account_updated_at,
                       client.created_at AS client_created_at,
                       client.updated_at AS client_updated_at,
                       (SELECT COUNT(*) FROM account_status_event
                        WHERE account_id = account.id) AS account_event_count,
                       (SELECT COUNT(*) FROM client_status_event
                        WHERE client_id = client.id) AS client_event_count,
                       (SELECT COUNT(*) FROM transaction_entry
                        WHERE account_id = account.id) AS entry_count,
                       (SELECT COUNT(DISTINCT financial_transaction.id)
                        FROM transaction_entry
                        JOIN financial_transaction
                          ON financial_transaction.id = transaction_entry.transaction_id
                        WHERE transaction_entry.account_id = account.id) AS transaction_count
                FROM account
                JOIN client ON client.id = account.client_id
                JOIN account_status ON account_status.id = account.status_id
                JOIN client_status ON client_status.id = client.status_id
                WHERE account.account_key = CAST(:account_key AS uuid)
                """
            ),
            {"account_key": account_key},
        ).mappings().one()
        return dict(row)


def _events(engine: Engine, account_key: str) -> tuple[list[dict], list[dict]]:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        account_events = connection.execute(
            text(
                """
                SELECT source.enumerator AS from_status, destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, event.reason, event.created_at
                FROM account_status_event AS event
                JOIN account ON account.id = event.account_id
                LEFT JOIN account_status AS source ON source.id = event.from_status_id
                JOIN account_status AS destination ON destination.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE account.account_key = CAST(:account_key AS uuid)
                ORDER BY event.id
                """
            ),
            {"account_key": account_key},
        ).mappings().all()
        client_events = connection.execute(
            text(
                """
                SELECT source.enumerator AS from_status, destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type, event.reason, event.created_at
                FROM client_status_event AS event
                JOIN client ON client.id = event.client_id
                JOIN account ON account.client_id = client.id
                LEFT JOIN client_status AS source ON source.id = event.from_status_id
                JOIN client_status AS destination ON destination.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE account.account_key = CAST(:account_key AS uuid)
                ORDER BY event.id
                """
            ),
            {"account_key": account_key},
        ).mappings().all()
        return [dict(row) for row in account_events], [dict(row) for row in client_events]


def _set_balance(engine: Engine, account_key: str, balance_cents: int) -> None:
    with engine.begin() as connection:
        assert connection.execute(
            text(
                """
                UPDATE account SET balance_cents = :balance_cents
                WHERE account_key = CAST(:account_key AS uuid)
                """
            ),
            {"account_key": account_key, "balance_cents": balance_cents},
        ).rowcount == 1


def _force_client_status(engine: Engine, account_key: str, status: str) -> None:
    with engine.begin() as connection:
        assert connection.execute(
            text(
                """
                UPDATE client
                SET status_id = (SELECT id FROM client_status WHERE enumerator = :status)
                WHERE id = (
                    SELECT client_id FROM account
                    WHERE account_key = CAST(:account_key AS uuid)
                )
                """
            ),
            {"account_key": account_key, "status": status},
        ).rowcount == 1

__all__ = [name for name in globals() if not name.startswith("__")]
