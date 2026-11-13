"""Seguran?a transacional da R07: cen?rios organizados por comportamento."""

from .support import *


def test_sequential_deposits_record_each_historical_balance(
    api_database_engine: Engine,
) -> None:
    account_key = create_account(api_database_engine)
    first_key = uuid4()
    second_key = uuid4()

    first_response = send_deposit(account_key, first_key, amount_cents=50_000)
    second_response = send_deposit(account_key, second_key, amount_cents=20_000)

    assert first_response.response_status == 201
    assert second_response.response_status == 201

    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        account_balance = connection.execute(
            text(
                """
                SELECT balance_cents
                FROM account
                WHERE account_key = :account_key
                """
            ),
            {"account_key": UUID(account_key)},
        ).scalar_one()
        entries = connection.execute(
            text(
                """
                SELECT transaction.request_control_key,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents, entry.balance_after_cents
                FROM transaction_entry AS entry
                JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type
                  ON entry_type.id = entry.entry_type_id
                WHERE transaction.request_control_key IN (
                    :first_key,
                    :second_key
                )
                ORDER BY entry.id
                """
            ),
            {"first_key": first_key, "second_key": second_key},
        ).mappings().all()

    assert account_balance == 70_000
    assert [
        (
            entry["request_control_key"],
            entry["direction"],
            entry["entry_type"],
            entry["amount_cents"],
            entry["balance_after_cents"],
        )
        for entry in entries
    ] == [
        (first_key, "CREDIT", "PRINCIPAL", 50_000, 50_000),
        (second_key, "CREDIT", "PRINCIPAL", 20_000, 70_000),
    ]
    assert entries[-1]["balance_after_cents"] == account_balance
