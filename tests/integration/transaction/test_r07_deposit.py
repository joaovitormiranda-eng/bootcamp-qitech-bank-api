"""Primeiro ciclo HTTP da R07: happy path de DEPOSIT."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    TRANSACTION_RESPONSE_FIELDS,
    read_deposit_state as _read_deposit_state,
    send_deposit as _send_deposit,
    set_account_status as _set_account_status,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def test_deposit_returns_created_transaction(
    active_account_key: str,
    api_database_engine: Engine,
) -> None:
    idempotency_key = uuid4()
    response = ClientRequisition.send(
        "POST",
        f"/account/{active_account_key}/transaction",
        headers={
            "INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Idempotency-Key": str(idempotency_key),
        },
        payload={
            "transaction_type": "DEPOSIT",
            "amount_cents": 50_000,
        },
    )

    assert response.response_status == 201
    assert response.response.headers["content-type"].startswith("application/json")

    response_body = response.response_json
    assert isinstance(response_body, dict)
    assert set(response_body) == TRANSACTION_RESPONSE_FIELDS
    assert isinstance(UUID(response_body["transaction_key"]), UUID)
    assert response_body["transaction_type"] == "DEPOSIT"
    assert response_body["account_key"] == active_account_key
    assert response_body["counterparty_account_key"] is None
    assert response_body["amount_cents"] == 50_000
    assert response_body["fee_cents"] == 0

    created_at = response_body["created_at"]
    assert isinstance(created_at, str)
    assert created_at.endswith("Z")
    parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    assert parsed_created_at.tzinfo is not None
    assert parsed_created_at.utcoffset() == timezone.utc.utcoffset(parsed_created_at)

    canonical_request = f"DEPOSIT|{active_account_key}|50000"
    expected_request_hash = sha256(canonical_request.encode("utf-8")).hexdigest()

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
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
                  ON transaction_type.id = financial_transaction.transaction_type_id
                WHERE request_control_key = :request_control_key
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()

    assert len(transactions) == 1
    transaction = transactions[0]
    assert str(transaction["transaction_key"]) == response_body["transaction_key"]
    assert transaction["request_control_key"] == idempotency_key
    assert transaction["request_hash"] == expected_request_hash
    assert transaction["transaction_type"] == "DEPOSIT"
    assert transaction["created_at"] == parsed_created_at

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        entries = connection.execute(
            text(
                """
                SELECT entry.transaction_id,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents, entry.balance_after_cents,
                       entry.created_at, account.account_key
                FROM transaction_entry AS entry
                JOIN account ON account.id = entry.account_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type ON entry_type.id = entry.entry_type_id
                WHERE entry.transaction_id = :transaction_id
                ORDER BY entry.id
                """
            ),
            {"transaction_id": transaction["id"]},
        ).mappings().all()

    assert len(entries) == 1
    entry = entries[0]
    assert entry["transaction_id"] == transaction["id"]
    assert entry["account_key"] == UUID(active_account_key)
    assert entry["direction"] == "CREDIT"
    assert entry["entry_type"] == "PRINCIPAL"
    assert entry["amount_cents"] == 50_000
    assert entry["balance_after_cents"] == 50_000
    assert entry["created_at"] == transaction["created_at"]
    assert all(persisted["entry_type"] != "FEE" for persisted in entries)

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        persisted_account = connection.execute(
            text(
                """
                SELECT balance_cents, updated_at
                FROM account
                WHERE account_key = :account_key
                """
            ),
            {"account_key": UUID(active_account_key)},
        ).mappings().one()

    assert persisted_account["balance_cents"] == 50_000
    assert persisted_account["updated_at"] == transaction["created_at"]


def test_deposit_replays_original_transaction_for_same_idempotency_key(
    active_account_key: str,
    api_database_engine: Engine,
) -> None:
    idempotency_key = uuid4()

    first_response = _send_deposit(active_account_key, idempotency_key)

    assert first_response.response_status == 201
    original_transaction = first_response.response_json
    assert isinstance(original_transaction, dict)
    assert set(original_transaction) == TRANSACTION_RESPONSE_FIELDS
    assert original_transaction["transaction_type"] == "DEPOSIT"
    assert original_transaction["account_key"] == active_account_key
    assert original_transaction["counterparty_account_key"] is None
    assert original_transaction["amount_cents"] == 50_000
    assert original_transaction["fee_cents"] == 0
    assert isinstance(UUID(original_transaction["transaction_key"]), UUID)
    assert original_transaction["created_at"].endswith("Z")

    state_after_first_request = _read_deposit_state(
        api_database_engine,
        active_account_key,
        idempotency_key,
    )
    assert state_after_first_request["balance_cents"] == 50_000
    assert len(state_after_first_request["transactions"]) == 1
    assert len(state_after_first_request["entries"]) == 1

    original_entry = state_after_first_request["entries"][0]
    assert original_entry["direction"] == "CREDIT"
    assert original_entry["entry_type"] == "PRINCIPAL"
    assert original_entry["amount_cents"] == 50_000

    second_response = _send_deposit(active_account_key, idempotency_key)
    state_after_second_request = _read_deposit_state(
        api_database_engine,
        active_account_key,
        idempotency_key,
    )

    observed_body = (
        second_response.response_json
        if second_response.response_json is not None
        else second_response.response_content.decode(errors="replace")
    )
    assert second_response.response_status == 201, (
        f"second response was {second_response.response_status}: "
        f"{observed_body!r}; original transaction_key="
        f"{original_transaction['transaction_key']}; persisted state: "
        f"balance={state_after_second_request['balance_cents']}, "
        f"transactions={len(state_after_second_request['transactions'])}, "
        f"entries={len(state_after_second_request['entries'])}"
    )
    assert second_response.response_json == original_transaction
    assert state_after_second_request["balance_cents"] == 50_000
    assert len(state_after_second_request["transactions"]) == 1
    assert len(state_after_second_request["entries"]) == 1
    assert state_after_second_request["entries"][0] == original_entry


def test_deposit_replay_ignores_current_inactive_account_status(
    active_account_key: str,
    api_database_engine: Engine,
) -> None:
    idempotency_key = uuid4()
    first_response = _send_deposit(active_account_key, idempotency_key)
    assert first_response.response_status == 201

    original_transaction = first_response.response_json
    state_after_original = _read_deposit_state(
        api_database_engine,
        active_account_key,
        idempotency_key,
    )
    _set_account_status(
        api_database_engine,
        active_account_key,
        "INACTIVE",
    )

    replay_response = _send_deposit(active_account_key, idempotency_key)
    state_after_replay = _read_deposit_state(
        api_database_engine,
        active_account_key,
        idempotency_key,
    )

    assert replay_response.response_status == 201
    assert replay_response.response_json == original_transaction
    assert state_after_replay["status"] == "INACTIVE"
    assert state_after_replay["balance_cents"] == 50_000
    assert state_after_replay["updated_at"] == state_after_original["updated_at"]
    assert len(state_after_replay["transactions"]) == 1
    assert len(state_after_replay["entries"]) == 1


def test_deposit_rejects_same_idempotency_key_for_different_intention(
    active_account_key: str,
    api_database_engine: Engine,
) -> None:
    idempotency_key = uuid4()
    original_response = _send_deposit(active_account_key, idempotency_key)
    assert original_response.response_status == 201

    conflict_response = _send_deposit(
        active_account_key,
        idempotency_key,
        amount_cents=60_000,
    )
    persisted_state = _read_deposit_state(
        api_database_engine,
        active_account_key,
        idempotency_key,
    )

    assert conflict_response.response_status == 409
    assert conflict_response.response_json["code"] == "TRX0003"
    assert persisted_state["balance_cents"] == 50_000
    assert len(persisted_state["transactions"]) == 1
    assert len(persisted_state["entries"]) == 1
    assert persisted_state["entries"][0]["amount_cents"] == 50_000


def test_deposit_with_new_idempotency_key_creates_new_transaction(
    active_account_key: str,
    api_database_engine: Engine,
) -> None:
    first_key = uuid4()
    second_key = uuid4()

    first_response = _send_deposit(active_account_key, first_key)
    second_response = _send_deposit(active_account_key, second_key)

    assert first_response.response_status == 201
    assert second_response.response_status == 201
    assert (
        first_response.response_json["transaction_key"]
        != second_response.response_json["transaction_key"]
    )

    first_state = _read_deposit_state(
        api_database_engine,
        active_account_key,
        first_key,
    )
    second_state = _read_deposit_state(
        api_database_engine,
        active_account_key,
        second_key,
    )
    assert second_state["balance_cents"] == 100_000
    assert len(first_state["transactions"]) == 1
    assert len(first_state["entries"]) == 1
    assert len(second_state["transactions"]) == 1
    assert len(second_state["entries"]) == 1
    assert (
        first_state["transactions"][0]["request_hash"]
        == second_state["transactions"][0]["request_hash"]
    )
