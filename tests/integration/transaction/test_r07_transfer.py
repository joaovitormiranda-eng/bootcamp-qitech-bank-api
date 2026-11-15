"""Primeiro ciclo HTTP da R07: happy path de TRANSFER."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    TRANSACTION_RESPONSE_FIELDS,
    create_account,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def test_transfer_returns_created_transaction(
    api_database_engine: Engine,
) -> None:
    source_account_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    target_account_key = create_account(
        api_database_engine,
        balance_cents=0,
    )

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        accounts = connection.execute(
            text(
                """
                SELECT account.account_key, account.client_id,
                       account.balance_cents,
                       account_status.enumerator AS status,
                       client_type.enumerator AS client_type
                FROM account
                JOIN account_status
                  ON account_status.id = account.status_id
                JOIN client
                  ON client.id = account.client_id
                JOIN client_type
                  ON client_type.id = client.client_type_id
                WHERE account.account_key IN (
                    :source_account_key,
                    :target_account_key
                )
                """
            ),
            {
                "source_account_key": UUID(source_account_key),
                "target_account_key": UUID(target_account_key),
            },
        ).mappings().all()

    accounts_by_key = {
        str(account["account_key"]): account for account in accounts
    }
    source = accounts_by_key[source_account_key]
    target = accounts_by_key[target_account_key]

    assert source_account_key != target_account_key
    assert source["client_id"] != target["client_id"]
    assert source["client_type"] == "INDIVIDUAL"
    assert source["status"] == "ACTIVE"
    assert source["balance_cents"] == 100_000
    assert target["status"] == "ACTIVE"
    assert target["balance_cents"] == 0

    idempotency_key = uuid4()
    response = ClientRequisition.send(
        "POST",
        f"/account/{source_account_key}/transaction",
        headers={
            "INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Idempotency-Key": str(idempotency_key),
        },
        payload={
            "transaction_type": "TRANSFER",
            "target_account_key": target_account_key,
            "amount_cents": 50_000,
        },
    )

    observed_body = (
        response.response_json
        if response.response_json is not None
        else response.response_content.decode(errors="replace")
    )
    assert response.response_status == 201, (
        f"body={observed_body!r}; source={source_account_key}; "
        f"target={target_account_key}; idempotency_key={idempotency_key}"
    )
    assert response.response.headers["content-type"].startswith(
        "application/json"
    )

    response_body = response.response_json
    assert isinstance(response_body, dict)
    assert set(response_body) == TRANSACTION_RESPONSE_FIELDS
    assert isinstance(UUID(response_body["transaction_key"]), UUID)
    assert response_body["transaction_type"] == "TRANSFER"
    assert response_body["account_key"] == source_account_key
    assert response_body["counterparty_account_key"] == target_account_key
    assert response_body["amount_cents"] == 50_000
    assert response_body["fee_cents"] == 250

    created_at = response_body["created_at"]
    assert isinstance(created_at, str)
    assert created_at.endswith("Z")
    parsed_created_at = datetime.fromisoformat(
        created_at.replace("Z", "+00:00")
    )
    assert parsed_created_at.tzinfo is not None
    assert parsed_created_at.utcoffset() == timezone.utc.utcoffset(
        parsed_created_at
    )

    canonical_request = (
        f"TRANSFER|{source_account_key}|{target_account_key}|50000"
    )
    expected_request_hash = sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()

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
    assert str(transaction["transaction_key"]) == response_body[
        "transaction_key"
    ]
    assert transaction["request_control_key"] == idempotency_key
    assert transaction["request_hash"] == expected_request_hash
    assert transaction["transaction_type"] == "TRANSFER"
    assert transaction["created_at"] == parsed_created_at

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        entries = connection.execute(
            text(
                """
                SELECT transaction_direction.enumerator AS direction,
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

    assert len(entries) == 3
    assert [
        (
            str(entry["account_key"]),
            entry["direction"],
            entry["entry_type"],
            entry["amount_cents"],
            entry["balance_after_cents"],
        )
        for entry in entries
    ] == [
        (source_account_key, "DEBIT", "PRINCIPAL", 50_000, 50_000),
        (source_account_key, "DEBIT", "FEE", 250, 49_750),
        (target_account_key, "CREDIT", "PRINCIPAL", 50_000, 50_000),
    ]
    assert all(
        entry["created_at"] == transaction["created_at"]
        for entry in entries
    )

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        persisted_accounts = connection.execute(
            text(
                """
                SELECT account_key, balance_cents, updated_at
                FROM account
                WHERE account_key IN (
                    :source_account_key,
                    :target_account_key
                )
                """
            ),
            {
                "source_account_key": UUID(source_account_key),
                "target_account_key": UUID(target_account_key),
            },
        ).mappings().all()

    persisted_by_key = {
        str(account["account_key"]): account
        for account in persisted_accounts
    }
    persisted_source = persisted_by_key[source_account_key]
    persisted_target = persisted_by_key[target_account_key]

    assert persisted_source["balance_cents"] == 49_750
    assert persisted_target["balance_cents"] == 50_000
    assert persisted_source["updated_at"] == transaction["created_at"]
    assert persisted_target["updated_at"] == transaction["created_at"]
    assert entries[1]["balance_after_cents"] == persisted_source[
        "balance_cents"
    ]
    assert entries[2]["balance_after_cents"] == persisted_target[
        "balance_cents"
    ]

    delta_source = persisted_source["balance_cents"] - 100_000
    delta_target = persisted_target["balance_cents"] - 0
    assert delta_source + delta_target == -response_body["fee_cents"]
