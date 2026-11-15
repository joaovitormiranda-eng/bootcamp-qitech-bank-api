from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    create_account,
    open_funded_account_via_api,
    send_deposit,
    send_transfer,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def _get_statement(account_key: str, order_by: str):
    return ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"order_by": order_by},
    )


def _set_transaction_timestamp(
    api_database_engine: Engine,
    transaction_key: str,
    created_at: datetime,
) -> None:
    with api_database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE financial_transaction
                SET created_at = :created_at
                WHERE transaction_key = :transaction_key
                """
            ),
            {
                "created_at": created_at,
                "transaction_key": UUID(transaction_key),
            },
        )


@pytest.mark.parametrize(
    ("order_by", "expected_order"),
    [
        ("asc", ("older", "newer")),
        ("desc", ("newer", "older")),
    ],
)
def test_statement_orders_transactions_by_financial_transaction_timestamp(
    api_database_engine: Engine,
    order_by: str,
    expected_order: tuple[str, str],
) -> None:
    account_key = open_funded_account_via_api()
    older_response = send_deposit(account_key, uuid4(), amount_cents=10_000)
    newer_response = send_deposit(account_key, uuid4(), amount_cents=20_000)
    assert older_response.response_status == 201
    assert newer_response.response_status == 201

    older_timestamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    newer_timestamp = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    _set_transaction_timestamp(
        api_database_engine,
        older_response.response_json["transaction_key"],
        older_timestamp,
    )
    _set_transaction_timestamp(
        api_database_engine,
        newer_response.response_json["transaction_key"],
        newer_timestamp,
    )

    response_by_label = {
        "older": older_response.response_json,
        "newer": newer_response.response_json,
    }
    statement_response = _get_statement(account_key, order_by)

    assert statement_response.response_status == 200
    assert [item["transaction_key"] for item in statement_response.response_json["data"]] == [
        response_by_label[label]["transaction_key"] for label in expected_order
    ]
    assert [item["created_at"] for item in statement_response.response_json["data"]] == [
        (
            older_timestamp
            if label == "older"
            else newer_timestamp
        ).isoformat().replace("+00:00", "Z")
        for label in expected_order
    ]


@pytest.mark.parametrize("order_by", ["asc", "desc"])
def test_statement_uses_financial_transaction_id_to_break_timestamp_ties(
    api_database_engine: Engine,
    order_by: str,
) -> None:
    account_key = open_funded_account_via_api()
    first_response = send_deposit(account_key, uuid4(), amount_cents=10_000)
    second_response = send_deposit(account_key, uuid4(), amount_cents=20_000)
    assert first_response.response_status == 201
    assert second_response.response_status == 201

    tied_timestamp = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    transaction_keys = [
        first_response.response_json["transaction_key"],
        second_response.response_json["transaction_key"],
    ]
    for transaction_key in transaction_keys:
        _set_transaction_timestamp(
            api_database_engine,
            transaction_key,
            tied_timestamp,
        )

    with api_database_engine.connect() as connection:
        persisted = connection.execute(
            text(
                """
                SELECT id, transaction_key
                FROM financial_transaction
                WHERE transaction_key IN (:first_key, :second_key)
                ORDER BY id
                """
            ),
            {
                "first_key": UUID(transaction_keys[0]),
                "second_key": UUID(transaction_keys[1]),
            },
        ).mappings().all()

    expected = [str(row["transaction_key"]) for row in persisted]
    if order_by == "desc":
        expected.reverse()

    statement_response = _get_statement(account_key, order_by)

    assert statement_response.response_status == 200
    assert [item["transaction_key"] for item in statement_response.response_json["data"]] == expected


@pytest.mark.parametrize("order_by", ["asc", "desc"])
def test_statement_keeps_transfer_principal_before_fee(
    api_database_engine: Engine,
    order_by: str,
) -> None:
    # Saldo de abertura da origem semeado por SQL (sem lançamento) porque o
    # teste afirma que o extrato da ORIGEM contém EXATAMENTE os dois
    # lançamentos [PRINCIPAL, FEE] nesta ordem; um DEPOSIT de funding
    # adicionaria um terceiro lançamento (CRÉDITO) ao próprio extrato da
    # origem. A API não permite saldo de abertura sem depósito.
    source_account_key = create_account(
        api_database_engine,
        client_type="INDIVIDUAL",
        balance_cents=100_000,
    )
    target_account_key = open_funded_account_via_api()
    transfer_response = send_transfer(
        source_account_key,
        target_account_key,
        uuid4(),
        amount_cents=50_000,
    )
    assert transfer_response.response_status == 201

    statement_response = _get_statement(source_account_key, order_by)

    assert statement_response.response_status == 200
    assert [item["entry_type"] for item in statement_response.response_json["data"]] == [
        "PRINCIPAL",
        "FEE",
    ]
    assert [item["direction"] for item in statement_response.response_json["data"]] == [
        "DEBIT",
        "DEBIT",
    ]
