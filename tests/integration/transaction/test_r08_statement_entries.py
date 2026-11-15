from datetime import datetime, timezone
from uuid import UUID, uuid4

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


def _get_statement(account_key: str, *, order_by: str = "desc"):
    return ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={"order_by": order_by},
    )


def test_statement_returns_deposit_entry_from_persisted_history() -> None:
    account_key = open_funded_account_via_api()
    deposit_response = send_deposit(account_key, uuid4(), amount_cents=50_000)

    assert deposit_response.response_status == 201
    persisted_transaction = deposit_response.response_json

    statement_response = _get_statement(account_key)

    assert statement_response.response_status == 200
    assert statement_response.response_json == {
        "data": [
            {
                "transaction_key": persisted_transaction["transaction_key"],
                "transaction_type": "DEPOSIT",
                "entry_type": "PRINCIPAL",
                "direction": "CREDIT",
                "amount_cents": 50_000,
                "balance_after_cents": 50_000,
                "counterparty_account_key": None,
                "created_at": persisted_transaction["created_at"],
            }
        ],
        "pagination": {
            "current_page": 1,
            "next_page": None,
            "rows_per_page": 20,
        },
    }


def test_statement_returns_transfer_principal_and_fee_for_source(
    api_database_engine: Engine,
) -> None:
    # Saldo de abertura da origem semeado por SQL (sem lançamento) porque o
    # teste afirma que o extrato da ORIGEM é EXATAMENTE [PRINCIPAL, FEE] com
    # next_page None; um DEPOSIT de funding deixaria um CRÉDITO extra no
    # próprio extrato da origem. A API não oferece saldo de abertura sem
    # depósito, então o SQL de abertura é a fixture fiel do formato do
    # extrato. O destino permanece preparado via API.
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
    persisted_transaction = transfer_response.response_json

    statement_response = _get_statement(source_account_key)

    assert statement_response.response_status == 200
    assert statement_response.response_json["data"] == [
        {
            "transaction_key": persisted_transaction["transaction_key"],
            "transaction_type": "TRANSFER",
            "entry_type": "PRINCIPAL",
            "direction": "DEBIT",
            "amount_cents": 50_000,
            "balance_after_cents": 50_000,
            "counterparty_account_key": target_account_key,
            "created_at": persisted_transaction["created_at"],
        },
        {
            "transaction_key": persisted_transaction["transaction_key"],
            "transaction_type": "TRANSFER",
            "entry_type": "FEE",
            "direction": "DEBIT",
            "amount_cents": 250,
            "balance_after_cents": 49_750,
            "counterparty_account_key": None,
            "created_at": persisted_transaction["created_at"],
        },
    ]
    assert statement_response.response_json["pagination"] == {
        "current_page": 1,
        "next_page": None,
        "rows_per_page": 20,
    }


def test_statement_returns_transfer_principal_for_target() -> None:
    source_account_key = open_funded_account_via_api(
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
    persisted_transaction = transfer_response.response_json

    statement_response = _get_statement(target_account_key)

    assert statement_response.response_status == 200
    assert statement_response.response_json["data"] == [
        {
            "transaction_key": persisted_transaction["transaction_key"],
            "transaction_type": "TRANSFER",
            "entry_type": "PRINCIPAL",
            "direction": "CREDIT",
            "amount_cents": 50_000,
            "balance_after_cents": 50_000,
            "counterparty_account_key": source_account_key,
            "created_at": persisted_transaction["created_at"],
        }
    ]


def test_statement_uses_financial_transaction_timestamp(
    api_database_engine: Engine,
) -> None:
    # Cenário de persistência legítimo: back-date de transaction_entry
    # (created_at divergente do financial_transaction) só é produzível via
    # SQL. A conta é preparada por API; o SQL fica restrito ao back-date.
    account_key = open_funded_account_via_api()
    deposit_response = send_deposit(account_key, uuid4(), amount_cents=50_000)

    assert deposit_response.response_status == 201
    transaction_key = UUID(deposit_response.response_json["transaction_key"])
    different_entry_timestamp = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with api_database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE transaction_entry
                SET created_at = :created_at
                WHERE transaction_id = (
                    SELECT id
                    FROM financial_transaction
                    WHERE transaction_key = :transaction_key
                )
                """
            ),
            {
                "created_at": different_entry_timestamp,
                "transaction_key": transaction_key,
            },
        )

    statement_response = _get_statement(account_key)

    assert statement_response.response_status == 200
    item = statement_response.response_json["data"][0]
    assert item["created_at"] == deposit_response.response_json["created_at"]
    assert item["created_at"] != different_entry_timestamp.isoformat().replace(
        "+00:00", "Z"
    )
