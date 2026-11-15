from datetime import datetime, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    open_funded_account_via_api,
    send_deposit,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def _get_statement(account_key: str, **query_params: str):
    return ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params=query_params,
    )


def _set_client_timezone(
    api_database_engine: Engine,
    account_key: str,
    timezone_name: str,
) -> None:
    with api_database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE client
                SET timezone = :timezone_name
                WHERE id = (
                    SELECT client_id FROM account WHERE account_key = :account_key
                )
                """
            ),
            {
                "timezone_name": timezone_name,
                "account_key": UUID(account_key),
            },
        )


def _create_deposit_at(
    api_database_engine: Engine,
    account_key: str,
    amount_cents: int,
    created_at: datetime,
    *,
    entry_created_at: datetime | None = None,
) -> str:
    response = send_deposit(account_key, uuid4(), amount_cents=amount_cents)
    assert response.response_status == 201
    transaction_key = response.response_json["transaction_key"]
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
        if entry_created_at is not None:
            connection.execute(
                text(
                    """
                    UPDATE transaction_entry
                    SET created_at = :entry_created_at
                    WHERE transaction_id = (
                        SELECT id FROM financial_transaction
                        WHERE transaction_key = :transaction_key
                    )
                    """
                ),
                {
                    "entry_created_at": entry_created_at,
                    "transaction_key": UUID(transaction_key),
                },
            )
    return transaction_key


@pytest.mark.parametrize("date_param", ["date_from", "date_to"])
@pytest.mark.parametrize(
    "invalid_date",
    ["2026-02-30", "2026-13-01", "2026-00-10"],
)
def test_statement_rejects_impossible_civil_dates(
    date_param: str,
    invalid_date: str,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "GET",
        f"/account/{account_key}/transactions",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        query_params={date_param: invalid_date},
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000001"


def test_statement_applies_date_from_in_client_timezone(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Sao_Paulo"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)

    before_key = _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 11, 23, 30, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    at_start_key = _create_deposit_at(
        api_database_engine,
        account_key,
        2_000,
        datetime(2026, 10, 12, 0, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    after_key = _create_deposit_at(
        api_database_engine,
        account_key,
        3_000,
        datetime(2026, 10, 13, 0, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )

    response = _get_statement(
        account_key,
        date_from="2026-10-12",
        order_by="asc",
    )

    assert response.response_status == 200
    returned_keys = [item["transaction_key"] for item in response.response_json["data"]]
    assert returned_keys == [at_start_key, after_key]
    assert before_key not in returned_keys


def test_statement_applies_inclusive_date_to_with_exclusive_upper_bound(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Sao_Paulo"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)

    older_key = _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 11, 12, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    end_of_day_key = _create_deposit_at(
        api_database_engine,
        account_key,
        2_000,
        datetime(2026, 10, 12, 23, 59, 59, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    upper_bound_key = _create_deposit_at(
        api_database_engine,
        account_key,
        3_000,
        datetime(2026, 10, 13, 0, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )

    response = _get_statement(
        account_key,
        date_to="2026-10-12",
        order_by="asc",
    )

    assert response.response_status == 200
    returned_keys = [item["transaction_key"] for item in response.response_json["data"]]
    assert returned_keys == [older_key, end_of_day_key]
    assert upper_bound_key not in returned_keys


def test_statement_filters_a_complete_local_day(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Sao_Paulo"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)

    before_key = _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 11, 23, 59, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    start_key = _create_deposit_at(
        api_database_engine,
        account_key,
        2_000,
        datetime(2026, 10, 12, 0, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    middle_key = _create_deposit_at(
        api_database_engine,
        account_key,
        3_000,
        datetime(2026, 10, 12, 12, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    end_key = _create_deposit_at(
        api_database_engine,
        account_key,
        4_000,
        datetime(2026, 10, 12, 23, 59, 59, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    upper_bound_key = _create_deposit_at(
        api_database_engine,
        account_key,
        5_000,
        datetime(2026, 10, 13, 0, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )

    response = _get_statement(
        account_key,
        date_from="2026-10-12",
        date_to="2026-10-12",
        order_by="desc",
    )

    assert response.response_status == 200
    returned_keys = [item["transaction_key"] for item in response.response_json["data"]]
    assert returned_keys == [end_key, middle_key, start_key]
    assert before_key not in returned_keys
    assert upper_bound_key not in returned_keys


def test_statement_rejects_inverted_date_range() -> None:
    account_key = open_funded_account_via_api()

    response = _get_statement(
        account_key,
        date_from="2026-10-13",
        date_to="2026-10-12",
    )

    assert response.response_status == 422
    assert response.response_json["code"] == "TRX0005"


def test_statement_uses_manaus_timezone_at_local_day_boundary(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Manaus"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)

    previous_local_day_key = _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 11, 23, 30, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    requested_local_day_key = _create_deposit_at(
        api_database_engine,
        account_key,
        2_000,
        datetime(2026, 10, 12, 0, 30, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )

    response = _get_statement(
        account_key,
        date_from="2026-10-12",
        date_to="2026-10-12",
    )

    assert response.response_status == 200
    returned_keys = [item["transaction_key"] for item in response.response_json["data"]]
    assert returned_keys == [requested_local_day_key]
    assert previous_local_day_key not in returned_keys


def test_statement_date_filter_uses_financial_transaction_timestamp(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Sao_Paulo"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)
    transaction_key = _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 12, 12, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
        entry_created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    response = _get_statement(
        account_key,
        date_from="2026-10-12",
        date_to="2026-10-12",
    )

    assert response.response_status == 200
    assert [item["transaction_key"] for item in response.response_json["data"]] == [
        transaction_key
    ]


def test_statement_filters_before_applying_pagination(
    api_database_engine: Engine,
) -> None:
    timezone_name = "America/Sao_Paulo"
    client_timezone = ZoneInfo(timezone_name)
    account_key = open_funded_account_via_api()
    _set_client_timezone(api_database_engine, account_key, timezone_name)
    _create_deposit_at(
        api_database_engine,
        account_key,
        1_000,
        datetime(2026, 10, 11, 12, 0, tzinfo=client_timezone).astimezone(
            timezone.utc
        ),
    )
    expected_keys = [
        _create_deposit_at(
            api_database_engine,
            account_key,
            amount_cents,
            datetime(2026, 10, 12, hour, 0, tzinfo=client_timezone).astimezone(
                timezone.utc
            ),
        )
        for amount_cents, hour in ((2_000, 8), (3_000, 12), (4_000, 16))
    ]

    page_1 = _get_statement(
        account_key,
        date_from="2026-10-12",
        date_to="2026-10-12",
        order_by="asc",
        page="1",
        limit="2",
    )
    page_2 = _get_statement(
        account_key,
        date_from="2026-10-12",
        date_to="2026-10-12",
        order_by="asc",
        page="2",
        limit="2",
    )

    assert page_1.response_status == 200
    assert page_2.response_status == 200
    assert [item["transaction_key"] for item in page_1.response_json["data"]] == expected_keys[:2]
    assert [item["transaction_key"] for item in page_2.response_json["data"]] == expected_keys[2:]
    assert page_1.response_json["pagination"]["next_page"] == 2
    assert page_2.response_json["pagination"]["next_page"] is None
