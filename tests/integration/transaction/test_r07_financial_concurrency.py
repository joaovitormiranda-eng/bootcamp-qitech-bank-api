"""Concorrência financeira entre TRANSFERs com keys independentes."""

from concurrent.futures import ThreadPoolExecutor
from os import environ
from threading import Barrier
from time import monotonic, sleep
from uuid import UUID, uuid4

from requests import Response, Session
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from tests.integration.transaction.support import create_account
from tests.utils import INTERNAL_TOKEN


HTTP_TIMEOUT_SECONDS = 8
FUTURE_TIMEOUT_SECONDS = 10
GATE_TIMEOUT_SECONDS = 5


def _post_transfer(
    barrier: Barrier,
    source_account_key: str,
    target_account_key: str,
    idempotency_key: UUID,
    amount_cents: int,
) -> Response:
    barrier.wait(timeout=GATE_TIMEOUT_SECONDS)
    api_host = environ.get("SERVER_LOCALHOST", "0.0.0.0")
    api_port = environ.get("API_PORT", "3000")
    with Session() as http_session:
        return http_session.post(
            (
                f"http://{api_host}:{api_port}/account/"
                f"{source_account_key}/transaction"
            ),
            headers={
                "INTERNAL-TOKEN": INTERNAL_TOKEN,
                "Idempotency-Key": str(idempotency_key),
            },
            json={
                "transaction_type": "TRANSFER",
                "target_account_key": target_account_key,
                "amount_cents": amount_cents,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )


def _wait_for_blocked_requests(
    connection: Connection,
    expected_count: int,
) -> None:
    control_pid = connection.execute(
        text("SELECT pg_backend_pid()")
    ).scalar_one()
    deadline = monotonic() + GATE_TIMEOUT_SECONDS
    while monotonic() < deadline:
        connection.execute(text("SELECT pg_stat_clear_snapshot()"))
        waiting_count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_stat_activity AS activity
                WHERE activity.datname = current_database()
                  AND activity.pid <> :control_pid
                  AND activity.wait_event_type = 'Lock'
                  AND activity.query ILIKE '%FOR UPDATE OF account%'
                """
            ),
            {"control_pid": control_pid},
        ).scalar_one()
        if waiting_count >= expected_count:
            return
        sleep(0.01)
    raise AssertionError(
        f"Expected {expected_count} transaction requests waiting for locks"
    )


def _run_gated_transfers(
    engine: Engine,
    account_a_key: str,
    account_b_key: str,
    requests_data: list[tuple[str, str, UUID, int]],
) -> tuple[list[Response], list[dict]]:
    barrier = Barrier(len(requests_data) + 1)

    with engine.connect() as lock_connection:
        gate_transaction = lock_connection.begin()
        locked_accounts = lock_connection.execute(
            text(
                """
                SELECT id, account_key
                FROM account
                WHERE account_key IN (
                    CAST(:account_a_key AS uuid),
                    CAST(:account_b_key AS uuid)
                )
                ORDER BY id
                FOR UPDATE
                """
            ),
            {
                "account_a_key": account_a_key,
                "account_b_key": account_b_key,
            },
        ).mappings().all()
        assert len(locked_accounts) == 2
        assert [account["id"] for account in locked_accounts] == sorted(
            account["id"] for account in locked_accounts
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _post_transfer,
                    barrier,
                    source_account_key,
                    target_account_key,
                    idempotency_key,
                    amount_cents,
                )
                for (
                    source_account_key,
                    target_account_key,
                    idempotency_key,
                    amount_cents,
                ) in requests_data
            ]
            try:
                barrier.wait(timeout=GATE_TIMEOUT_SECONDS)
                _wait_for_blocked_requests(
                    lock_connection,
                    expected_count=len(requests_data),
                )
            finally:
                if gate_transaction.is_active:
                    gate_transaction.rollback()

            responses = [
                future.result(timeout=FUTURE_TIMEOUT_SECONDS)
                for future in futures
            ]

    return responses, [dict(account) for account in locked_accounts]


def _read_state(
    engine: Engine,
    account_a_key: str,
    account_b_key: str,
    idempotency_keys: tuple[UUID, UUID],
) -> dict:
    with engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        accounts = connection.execute(
            text(
                """
                SELECT id, account_key, balance_cents, updated_at
                FROM account
                WHERE account_key IN (
                    CAST(:account_a_key AS uuid),
                    CAST(:account_b_key AS uuid)
                )
                ORDER BY id
                """
            ),
            {
                "account_a_key": account_a_key,
                "account_b_key": account_b_key,
            },
        ).mappings().all()
        transactions = connection.execute(
            text(
                """
                SELECT financial_transaction.id,
                       financial_transaction.transaction_key,
                       financial_transaction.request_control_key,
                       financial_transaction.request_hash,
                       transaction_type.enumerator AS transaction_type,
                       financial_transaction.created_at
                FROM financial_transaction
                JOIN transaction_type
                  ON transaction_type.id
                   = financial_transaction.transaction_type_id
                WHERE request_control_key IN (
                    :first_idempotency_key,
                    :second_idempotency_key
                )
                ORDER BY id
                """
            ),
            {
                "first_idempotency_key": idempotency_keys[0],
                "second_idempotency_key": idempotency_keys[1],
            },
        ).mappings().all()
        entries = connection.execute(
            text(
                """
                SELECT entry.id, entry.transaction_id,
                       account.account_key,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents,
                       entry.balance_after_cents, entry.created_at
                FROM transaction_entry AS entry
                JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                JOIN account ON account.id = entry.account_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type
                  ON entry_type.id = entry.entry_type_id
                WHERE transaction.request_control_key IN (
                    :first_idempotency_key,
                    :second_idempotency_key
                )
                ORDER BY entry.transaction_id, entry.id
                """
            ),
            {
                "first_idempotency_key": idempotency_keys[0],
                "second_idempotency_key": idempotency_keys[1],
            },
        ).mappings().all()

    return {
        "accounts": {
            str(account["account_key"]): account for account in accounts
        },
        "transactions": transactions,
        "entries": entries,
    }


def _response_summary(response: Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return {"status": response.status_code, "body": body}


def test_concurrent_transfers_cannot_spend_same_source_balance_twice(
    api_database_engine: Engine,
) -> None:
    source_key = create_account(
        api_database_engine,
        balance_cents=50_250,
    )
    target_key = create_account(api_database_engine)
    first_key = uuid4()
    second_key = uuid4()
    assert first_key != second_key

    responses, locked_accounts = _run_gated_transfers(
        api_database_engine,
        source_key,
        target_key,
        [
            (source_key, target_key, first_key, 50_000),
            (source_key, target_key, second_key, 50_000),
        ],
    )
    state = _read_state(
        api_database_engine,
        source_key,
        target_key,
        (first_key, second_key),
    )
    summaries = [_response_summary(response) for response in responses]

    assert state["accounts"][source_key]["balance_cents"] == 0
    assert state["accounts"][target_key]["balance_cents"] == 50_000
    assert len(state["transactions"]) == 1
    assert len(state["entries"]) == 3
    assert sorted(response.status_code for response in responses) == [201, 422], {
        "responses": summaries,
        "locks": locked_accounts,
        "state": state,
    }
    rejected_index = next(
        index
        for index, response in enumerate(responses)
        if response.status_code == 422
    )
    rejected_response = responses[rejected_index]
    operation_keys = (first_key, second_key)
    rejected_key = operation_keys[rejected_index]
    accepted_key = operation_keys[1 - rejected_index]
    persisted_keys = {
        transaction["request_control_key"]
        for transaction in state["transactions"]
    }
    assert rejected_response.json()["code"] == "TRX0001"
    assert rejected_key not in persisted_keys
    assert accepted_key in persisted_keys


def test_opposite_concurrent_transfers_finish_without_deadlock(
    api_database_engine: Engine,
) -> None:
    account_a_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    account_b_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    first_key = uuid4()
    second_key = uuid4()
    assert first_key != second_key

    responses, locked_accounts = _run_gated_transfers(
        api_database_engine,
        account_a_key,
        account_b_key,
        [
            (account_a_key, account_b_key, first_key, 50_000),
            (account_b_key, account_a_key, second_key, 50_000),
        ],
    )
    state = _read_state(
        api_database_engine,
        account_a_key,
        account_b_key,
        (first_key, second_key),
    )
    summaries = [_response_summary(response) for response in responses]

    assert [response.status_code for response in responses] == [201, 201], {
        "responses": summaries,
        "locks": locked_accounts,
        "state": state,
    }
    assert state["accounts"][account_a_key]["balance_cents"] == 99_750
    assert state["accounts"][account_b_key]["balance_cents"] == 99_750
    assert len(state["transactions"]) == 2
    assert len(state["entries"]) == 6

    entries_by_transaction = {
        transaction["id"]: [
            entry
            for entry in state["entries"]
            if entry["transaction_id"] == transaction["id"]
        ]
        for transaction in state["transactions"]
    }
    running_balances = {
        account_a_key: 100_000,
        account_b_key: 100_000,
    }
    for transaction in state["transactions"]:
        entries = entries_by_transaction[transaction["id"]]
        assert [
            (
                entry["direction"],
                entry["entry_type"],
                entry["amount_cents"],
            )
            for entry in entries
        ] == [
            ("DEBIT", "PRINCIPAL", 50_000),
            ("DEBIT", "FEE", 250),
            ("CREDIT", "PRINCIPAL", 50_000),
        ]
        assert all(
            entry["created_at"] == transaction["created_at"]
            for entry in entries
        )

        source_key = str(entries[0]["account_key"])
        target_key = str(entries[2]["account_key"])
        assert str(entries[1]["account_key"]) == source_key
        assert target_key != source_key

        running_balances[source_key] -= 50_000
        assert entries[0]["balance_after_cents"] == running_balances[source_key]
        running_balances[source_key] -= 250
        assert entries[1]["balance_after_cents"] == running_balances[source_key]
        running_balances[target_key] += 50_000
        assert entries[2]["balance_after_cents"] == running_balances[target_key]

    assert running_balances == {
        account_a_key: state["accounts"][account_a_key]["balance_cents"],
        account_b_key: state["accounts"][account_b_key]["balance_cents"],
    }

    initial_total = 200_000
    total_fee = sum(
        entry["amount_cents"]
        for entry in state["entries"]
        if entry["entry_type"] == "FEE"
    )
    final_total = sum(
        account["balance_cents"]
        for account in state["accounts"].values()
    )
    assert total_fee == 500
    assert final_total == initial_total - total_fee == 199_500

    final_updated_at = {
        account["updated_at"] for account in state["accounts"].values()
    }
    transaction_timestamps = {
        transaction["created_at"] for transaction in state["transactions"]
    }
    assert len(final_updated_at) == 1
    assert final_updated_at <= transaction_timestamps
