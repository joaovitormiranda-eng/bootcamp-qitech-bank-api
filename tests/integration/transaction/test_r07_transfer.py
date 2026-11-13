"""Primeiro ciclo HTTP da R07: happy path de TRANSFER (black-box + hash SQL)."""

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
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def test_transfer_returns_created_transaction(
    api_database_engine: Engine,
) -> None:
    source_account_key = open_funded_account_via_api(balance_cents=100_000)
    target_account_key = open_funded_account_via_api(balance_cents=0)

    source_snapshot = get_account_via_api(source_account_key)
    target_snapshot = get_account_via_api(target_account_key)

    assert source_account_key != target_account_key
    assert source_snapshot["client_key"] != target_snapshot["client_key"]
    assert source_snapshot["status"] == "ACTIVE"
    assert source_snapshot["balance_cents"] == 100_000
    assert target_snapshot["status"] == "ACTIVE"
    assert target_snapshot["balance_cents"] == 0

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

    # Movimentos observáveis via R08: origem com PRINCIPAL+FEE, destino com
    # o CREDIT, cada um com o balance_after_cents publicado.
    source_entries = list_statement_via_api(
        source_account_key,
        query_params={"order_by": "asc"},
    )["data"]
    target_entries = list_statement_via_api(
        target_account_key,
        query_params={"order_by": "asc"},
    )["data"]

    assert [
        (
            entry["transaction_key"],
            entry["direction"],
            entry["entry_type"],
            entry["amount_cents"],
            entry["balance_after_cents"],
            entry["counterparty_account_key"],
            entry["created_at"],
        )
        for entry in source_entries
    ] == [
        (
            response_body["transaction_key"],
            "DEBIT",
            "PRINCIPAL",
            50_000,
            50_000,
            target_account_key,
            created_at,
        ),
        (
            response_body["transaction_key"],
            "DEBIT",
            "FEE",
            250,
            49_750,
            None,
            created_at,
        ),
    ]
    assert [
        (
            entry["transaction_key"],
            entry["direction"],
            entry["entry_type"],
            entry["amount_cents"],
            entry["balance_after_cents"],
            entry["counterparty_account_key"],
            entry["created_at"],
        )
        for entry in target_entries
    ] == [
        (
            response_body["transaction_key"],
            "CREDIT",
            "PRINCIPAL",
            50_000,
            50_000,
            source_account_key,
            created_at,
        ),
    ]

    persisted_source = get_account_via_api(source_account_key)
    persisted_target = get_account_via_api(target_account_key)

    assert persisted_source["balance_cents"] == 49_750
    assert persisted_target["balance_cents"] == 50_000
    # account.updated_at acompanha o created_at da transação (ambos via HTTP).
    assert persisted_source["updated_at"] == created_at
    assert persisted_target["updated_at"] == created_at
    assert source_entries[1]["balance_after_cents"] == (
        persisted_source["balance_cents"]
    )
    assert target_entries[0]["balance_after_cents"] == (
        persisted_target["balance_cents"]
    )

    delta_source = persisted_source["balance_cents"] - 100_000
    delta_target = persisted_target["balance_cents"] - 0
    assert delta_source + delta_target == -response_body["fee_cents"]

    # request_hash (SHA-256) não tem projeção HTTP: leitura SQL mínima
    # apenas para essa asserção de persistência.
    canonical_request = (
        f"TRANSFER|{source_account_key}|{target_account_key}|50000"
    )
    expected_request_hash = sha256(
        canonical_request.encode("utf-8")
    ).hexdigest()
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        persisted_hash = connection.execute(
            text(
                """
                SELECT transaction_key, request_hash
                FROM financial_transaction
                WHERE request_control_key = :request_control_key
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()

    assert len(persisted_hash) == 1
    assert str(persisted_hash[0]["transaction_key"]) == (
        response_body["transaction_key"]
    )
    assert persisted_hash[0]["request_hash"] == expected_request_hash
