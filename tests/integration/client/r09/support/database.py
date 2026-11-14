"""Helpers coesos e locais da rota R09."""

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
                text("SELECT system_identifier::text FROM pg_control_system()")
            ).scalar_one()
        with test_engine.connect() as connection:
            test_identity = connection.execute(
                text("SELECT system_identifier::text FROM pg_control_system()")
            ).scalar_one()
        assert api_identity != test_identity
        yield engine
    finally:
        test_engine.dispose()
        engine.dispose()


def _snapshot(engine: Engine, client_key: str) -> dict:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        row = connection.execute(
            text(
                """
                SELECT client.id AS client_id, client.client_key::text AS client_key,
                       client_type.enumerator AS client_type,
                       client.email, client.timezone,
                       client.created_at, client.updated_at,
                       status.enumerator AS client_status,
                       (SELECT COUNT(*) FROM client_status_event
                        WHERE client_id = client.id) AS client_event_count,
                       (SELECT COUNT(*) FROM account
                        WHERE client_id = client.id) AS account_count,
                       (SELECT COUNT(*) FROM account_status_event
                        JOIN account ON account.id = account_status_event.account_id
                        WHERE account.client_id = client.id) AS account_event_count,
                       (SELECT COUNT(*) FROM transaction_entry
                        JOIN account ON account.id = transaction_entry.account_id
                        WHERE account.client_id = client.id) AS entry_count,
                       (SELECT COUNT(DISTINCT financial_transaction.id)
                        FROM financial_transaction
                        JOIN transaction_entry
                          ON transaction_entry.transaction_id = financial_transaction.id
                        JOIN account ON account.id = transaction_entry.account_id
                        WHERE account.client_id = client.id) AS transaction_count,
                       (SELECT status.enumerator FROM account
                        JOIN account_status AS status ON status.id = account.status_id
                        WHERE account.client_id = client.id) AS account_status,
                       (SELECT account.balance_cents FROM account
                        WHERE account.client_id = client.id) AS balance_cents,
                       (SELECT account.updated_at FROM account
                        WHERE account.client_id = client.id) AS account_updated_at
                FROM client
                JOIN client_status AS status ON status.id = client.status_id
                JOIN client_type ON client_type.id = client.client_type_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                """
            ),
            {"client_key": client_key},
        ).mappings().one()
        return dict(row)


def _events(engine: Engine, client_key: str) -> list[dict]:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        rows = connection.execute(
            text(
                """
                SELECT source.enumerator AS from_status,
                       destination.enumerator AS to_status,
                       actor_type.enumerator AS actor_type,
                       event.reason, event.created_at
                FROM client_status_event AS event
                JOIN client ON client.id = event.client_id
                LEFT JOIN client_status AS source ON source.id = event.from_status_id
                JOIN client_status AS destination ON destination.id = event.to_status_id
                JOIN actor_type ON actor_type.id = event.actor_type_id
                WHERE client.client_key = CAST(:client_key AS uuid)
                ORDER BY event.id
                """
            ),
            {"client_key": client_key},
        ).mappings().all()
        return [dict(row) for row in rows]

__all__ = [name for name in globals() if not name.startswith("__")]
