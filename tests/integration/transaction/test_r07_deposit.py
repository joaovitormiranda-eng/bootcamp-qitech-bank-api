"""Primeiro ciclo HTTP da R07: happy path de DEPOSIT (black-box + hash SQL)."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    TRANSACTION_RESPONSE_FIELDS,
    get_account_via_api,
    list_statement_via_api,
    open_funded_account_via_api,
    send_deposit as _send_deposit,
    set_account_status as _set_account_status,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def test_deposit_returns_created_transaction(
    api_database_engine: Engine,
) -> None:
    active_account_key = open_funded_account_via_api()
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

    # Lançamento único observável via R08, com balance_after publicado.
    entries = list_statement_via_api(active_account_key)["data"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["transaction_key"] == response_body["transaction_key"]
    assert entry["transaction_type"] == "DEPOSIT"
    assert entry["counterparty_account_key"] is None
    assert entry["direction"] == "CREDIT"
    assert entry["entry_type"] == "PRINCIPAL"
    assert entry["amount_cents"] == 50_000
    assert entry["balance_after_cents"] == 50_000
    assert entry["created_at"] == created_at
    assert all(persisted["entry_type"] != "FEE" for persisted in entries)

    # Saldo e updated_at via R05 (updated_at acompanha o created_at).
    persisted_account = get_account_via_api(active_account_key)
    assert persisted_account["balance_cents"] == 50_000
    assert persisted_account["updated_at"] == created_at

    # request_hash (SHA-256) não tem projeção HTTP: leitura SQL mínima só
    # para essa asserção de persistência.
    canonical_request = f"DEPOSIT|{active_account_key}|50000"
    expected_request_hash = sha256(canonical_request.encode("utf-8")).hexdigest()
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        transactions = connection.execute(
            text(
                """
                SELECT transaction_key, request_control_key, request_hash
                FROM financial_transaction
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


def test_deposit_replays_original_transaction_for_same_idempotency_key(
) -> None:
    active_account_key = open_funded_account_via_api()
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

    assert get_account_via_api(active_account_key)["balance_cents"] == 50_000
    entries_after_first = list_statement_via_api(active_account_key)["data"]
    assert len(entries_after_first) == 1
    original_entry = entries_after_first[0]
    assert original_entry["direction"] == "CREDIT"
    assert original_entry["entry_type"] == "PRINCIPAL"
    assert original_entry["amount_cents"] == 50_000

    second_response = _send_deposit(active_account_key, idempotency_key)

    observed_body = (
        second_response.response_json
        if second_response.response_json is not None
        else second_response.response_content.decode(errors="replace")
    )
    entries_after_second = list_statement_via_api(active_account_key)["data"]
    assert second_response.response_status == 201, (
        f"second response was {second_response.response_status}: "
        f"{observed_body!r}; original transaction_key="
        f"{original_transaction['transaction_key']}; entries now: "
        f"{len(entries_after_second)}"
    )
    assert second_response.response_json == original_transaction
    assert get_account_via_api(active_account_key)["balance_cents"] == 50_000
    assert len(entries_after_second) == 1
    assert entries_after_second[0] == original_entry


def test_deposit_replay_ignores_current_inactive_account_status(
    api_database_engine: Engine,
) -> None:
    active_account_key = open_funded_account_via_api()
    idempotency_key = uuid4()
    first_response = _send_deposit(active_account_key, idempotency_key)
    assert first_response.response_status == 201

    original_transaction = first_response.response_json
    updated_at_after_original = get_account_via_api(
        active_account_key
    )["updated_at"]
    # A pré-condição INACTIVE é arranjada por SQL (set_account_status atualiza
    # apenas status_id) para ISOLAR o invariante sob teste: "um replay não
    # move account.updated_at". A R06 PATCH teria um efeito colateral
    # observável em updated_at (account.updated_at = changed_at), fora do
    # escopo deste teste de idempotência, e quebraria a comparação
    # updated_at_after_replay == updated_at_after_original.
    _set_account_status(api_database_engine, active_account_key, "INACTIVE")

    replay_response = _send_deposit(active_account_key, idempotency_key)
    account_after_replay = get_account_via_api(active_account_key)
    entries_after_replay = list_statement_via_api(active_account_key)["data"]

    assert replay_response.response_status == 201
    assert replay_response.response_json == original_transaction
    assert account_after_replay["status"] == "INACTIVE"
    assert account_after_replay["balance_cents"] == 50_000
    # O replay não movimenta nem altera o updated_at da conta.
    assert account_after_replay["updated_at"] == updated_at_after_original
    assert len(entries_after_replay) == 1


def test_deposit_rejects_same_idempotency_key_for_different_intention(
) -> None:
    active_account_key = open_funded_account_via_api()
    idempotency_key = uuid4()
    original_response = _send_deposit(active_account_key, idempotency_key)
    assert original_response.response_status == 201

    conflict_response = _send_deposit(
        active_account_key,
        idempotency_key,
        amount_cents=60_000,
    )

    assert conflict_response.response_status == 409
    assert conflict_response.response_json["code"] == "TRX0003"
    assert get_account_via_api(active_account_key)["balance_cents"] == 50_000
    entries = list_statement_via_api(active_account_key)["data"]
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 50_000


def test_deposit_with_new_idempotency_key_creates_new_transaction(
    api_database_engine: Engine,
) -> None:
    active_account_key = open_funded_account_via_api()
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

    assert get_account_via_api(active_account_key)["balance_cents"] == 100_000
    entries = list_statement_via_api(active_account_key)["data"]
    assert len(entries) == 2
    assert {entry["transaction_key"] for entry in entries} == {
        first_response.response_json["transaction_key"],
        second_response.response_json["transaction_key"],
    }
    assert all(entry["amount_cents"] == 50_000 for entry in entries)

    # request_hash não tem projeção HTTP: leitura SQL mínima para provar que
    # depósitos idênticos produzem o mesmo hash canônico (SHA-256).
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        hashes = connection.execute(
            text(
                """
                SELECT request_hash
                FROM financial_transaction
                WHERE request_control_key IN (:first_key, :second_key)
                """
            ),
            {"first_key": first_key, "second_key": second_key},
        ).scalars().all()

    assert len(hashes) == 2
    assert hashes[0] == hashes[1]
