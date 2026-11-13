from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    open_funded_account_via_api,
    send_deposit,
    send_transfer,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def _get_statement(
    account_key: str,
    *,
    page: int,
    limit: int,
    order_by: str = "asc",
):
    return ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={
            "page": str(page),
            "limit": str(limit),
            "order_by": order_by,
        },
    )


def test_statement_paginates_real_history_with_limit_plus_one() -> None:
    account_key = open_funded_account_via_api()
    transaction_keys = []
    for amount_cents in (1_000, 2_000, 3_000, 4_000, 5_000):
        response = send_deposit(account_key, uuid4(), amount_cents=amount_cents)
        assert response.response_status == 201
        transaction_keys.append(response.response_json["transaction_key"])

    page_1 = _get_statement(account_key, page=1, limit=2)
    page_2 = _get_statement(account_key, page=2, limit=2)
    page_3 = _get_statement(account_key, page=3, limit=2)

    assert page_1.response_status == 200
    assert page_2.response_status == 200
    assert page_3.response_status == 200
    assert len(page_1.response_json["data"]) == 2
    assert len(page_2.response_json["data"]) == 2
    assert len(page_3.response_json["data"]) == 1
    assert page_1.response_json["pagination"] == {
        "current_page": 1,
        "next_page": 2,
        "rows_per_page": 2,
    }
    assert page_2.response_json["pagination"] == {
        "current_page": 2,
        "next_page": 3,
        "rows_per_page": 2,
    }
    assert page_3.response_json["pagination"] == {
        "current_page": 3,
        "next_page": None,
        "rows_per_page": 2,
    }

    returned_keys = [
        item["transaction_key"]
        for response in (page_1, page_2, page_3)
        for item in response.response_json["data"]
    ]
    assert returned_keys == transaction_keys


def test_statement_returns_empty_page_beyond_end() -> None:
    account_key = open_funded_account_via_api()
    response = send_deposit(account_key, uuid4(), amount_cents=1_000)
    assert response.response_status == 201

    statement_response = _get_statement(account_key, page=999, limit=20)

    assert statement_response.response_status == 200
    assert statement_response.response_json == {
        "data": [],
        "pagination": {
            "current_page": 999,
            "next_page": None,
            "rows_per_page": 20,
        },
    }


def test_statement_can_split_transfer_principal_and_fee_between_pages(
) -> None:
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

    principal_page = _get_statement(source_account_key, page=1, limit=1)
    fee_page = _get_statement(source_account_key, page=2, limit=1)

    assert principal_page.response_status == 200
    assert fee_page.response_status == 200
    assert [item["entry_type"] for item in principal_page.response_json["data"]] == [
        "PRINCIPAL"
    ]
    assert principal_page.response_json["pagination"]["next_page"] == 2
    assert [item["entry_type"] for item in fee_page.response_json["data"]] == [
        "FEE"
    ]
    assert fee_page.response_json["pagination"]["next_page"] is None


def test_statement_read_does_not_change_financial_state(
    api_database_engine: Engine,
) -> None:
    # Persistência legítima: prova que a leitura do extrato (R08) não altera
    # nenhuma linha. A conta é preparada por API; o SQL fica restrito à
    # comparação antes/depois do estado persistido.
    account_key = open_funded_account_via_api()
    deposit_response = send_deposit(account_key, uuid4(), amount_cents=50_000)
    assert deposit_response.response_status == 201

    def read_state() -> dict:
        with api_database_engine.connect() as connection:
            account = connection.execute(
                text(
                    """
                    SELECT balance_cents, updated_at
                    FROM account
                    WHERE account_key = :account_key
                    """
                ),
                {"account_key": UUID(account_key)},
            ).mappings().one()
            financial_rows = connection.execute(
                text(
                    """
                    SELECT financial_transaction.id AS transaction_id,
                           transaction_entry.id AS entry_id
                    FROM transaction_entry
                    JOIN financial_transaction
                      ON financial_transaction.id =
                         transaction_entry.transaction_id
                    JOIN account ON account.id = transaction_entry.account_id
                    WHERE account.account_key = :account_key
                    ORDER BY financial_transaction.id, transaction_entry.id
                    """
                ),
                {"account_key": UUID(account_key)},
            ).mappings().all()
            return {
                "account": dict(account),
                "financial_rows": [dict(row) for row in financial_rows],
            }

    state_before = read_state()
    statement_response = _get_statement(account_key, page=1, limit=20)
    state_after = read_state()

    assert statement_response.response_status == 200
    assert state_after == state_before
