from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    create_account,
    get_account_via_api,
    list_statement_via_api,
    open_funded_account_via_api,
    read_deposit_state,
    read_request_state,
    send_deposit,
    set_account_status,
)


BIGINT_MAX = 9_223_372_036_854_775_807


@pytest.mark.parametrize("invalid_amount", [0, -1])
def test_deposit_rejects_amount_below_minimum(
    invalid_amount: int,
) -> None:
    account_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_deposit(
        account_key,
        idempotency_key,
        invalid_amount,
    )

    assert response.response_status == 422
    assert response.response_json["code"] == "TRX0004"
    assert get_account_via_api(account_key)["balance_cents"] == 0
    assert list_statement_via_api(account_key)["data"] == []


def test_deposit_rejects_amount_above_bigint() -> None:
    account_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_deposit(
        account_key,
        idempotency_key,
        BIGINT_MAX + 1,
    )

    assert response.response_status == 422
    assert response.response_json["code"] == "TRX0004"
    assert get_account_via_api(account_key)["balance_cents"] == 0
    assert list_statement_via_api(account_key)["data"] == []


def test_deposit_rejects_balance_overflow(
    api_database_engine: Engine,
) -> None:
    # A starting balance of BIGINT_MAX-10 is unreachable through API deposits
    # (the overflow guard rejects any deposit that would reach it), so the
    # near-overflow pre-state and its persistence check stay on SQL.
    initial_balance = BIGINT_MAX - 10
    account_key = create_account(
        api_database_engine,
        balance_cents=initial_balance,
    )
    idempotency_key = uuid4()

    response = send_deposit(account_key, idempotency_key, 11)
    state = read_deposit_state(
        api_database_engine,
        account_key,
        idempotency_key,
    )

    assert response.response_status == 422
    assert response.response_json["code"] == "TRX0004"
    assert state["balance_cents"] == initial_balance
    assert state["transactions"] == []
    assert state["entries"] == []


def test_deposit_returns_account_not_found_without_persisting(
    api_database_engine: Engine,
) -> None:
    # The account intentionally does not exist, so there is no R05/R08
    # projection to assert against; the "nothing persisted" guarantee keeps
    # the read-only request-state SQL probe.
    missing_account_key = str(uuid4())
    idempotency_key = uuid4()

    response = send_deposit(missing_account_key, idempotency_key)
    state = read_request_state(api_database_engine, idempotency_key)

    assert response.response_status == 404
    assert response.response_json["code"] == "ACC0001"
    assert state["transactions"] == []
    assert state["entries"] == []


@pytest.mark.parametrize("account_status", ["INACTIVE", "CLOSED"])
def test_deposit_rejects_new_operation_for_non_active_account(
    api_database_engine: Engine,
    account_status: str,
) -> None:
    # An INACTIVE/CLOSED account cannot be arranged as a starting state
    # through the public API (R04 always opens an ACTIVE account), so the
    # pre-state and persistence check stay on SQL.
    account_key = create_account(
        api_database_engine,
        status=account_status,
    )
    idempotency_key = uuid4()

    response = send_deposit(account_key, idempotency_key)
    state = read_deposit_state(
        api_database_engine,
        account_key,
        idempotency_key,
    )

    assert response.response_status == 409
    assert response.response_json["code"] == "ACC0005"
    assert state["balance_cents"] == 0
    assert state["status"] == account_status
    assert state["transactions"] == []
    assert state["entries"] == []


def test_failed_deposit_does_not_consume_idempotency_key(
    api_database_engine: Engine,
) -> None:
    # Requires an INACTIVE starting state that is later flipped to ACTIVE;
    # neither the INACTIVE pre-state nor the in-place status change is
    # reachable through the public API, so SQL setup/verification stays.
    account_key = create_account(api_database_engine, status="INACTIVE")
    idempotency_key = uuid4()

    rejected_response = send_deposit(account_key, idempotency_key)
    state_after_rejection = read_deposit_state(
        api_database_engine,
        account_key,
        idempotency_key,
    )
    assert rejected_response.response_status == 409
    assert rejected_response.response_json["code"] == "ACC0005"
    assert state_after_rejection["transactions"] == []
    assert state_after_rejection["entries"] == []

    set_account_status(api_database_engine, account_key, "ACTIVE")
    accepted_response = send_deposit(account_key, idempotency_key)
    final_state = read_deposit_state(
        api_database_engine,
        account_key,
        idempotency_key,
    )

    assert accepted_response.response_status == 201
    assert final_state["balance_cents"] == 50_000
    assert len(final_state["transactions"]) == 1
    assert len(final_state["entries"]) == 1
