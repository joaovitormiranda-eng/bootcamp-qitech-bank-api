"""Validações estruturais, de domínio e limites da TRANSFER."""

from uuid import uuid4

import pytest
from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    create_account,
    get_account_via_api,
    list_statement_via_api,
    open_funded_account_via_api,
    read_transfer_state,
    send_transfer,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


BIGINT_MAX = 9_223_372_036_854_775_807


def _assert_error(response, status: int, code: str) -> None:
    assert response.response_status == status
    assert response.response_json["code"] == code


@pytest.mark.parametrize(
    "payload",
    [
        {"transaction_type": "TRANSFER", "amount_cents": 50_000},
        {
            "transaction_type": "TRANSFER",
            "target_account_key": "not-a-uuid",
            "amount_cents": 50_000,
        },
        {
            "transaction_type": "TRANSFER",
            "target_account_key": str(uuid4()),
            "amount_cents": 50_000,
            "unexpected": True,
        },
    ],
    ids=["missing-target", "invalid-target", "extra-property"],
)
def test_transfer_rejects_structurally_invalid_body(
    payload: dict,
) -> None:
    account_key = open_funded_account_via_api()

    response = ClientRequisition.send(
        "POST",
        f"/account/{account_key}/transaction",
        headers={
            "INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Idempotency-Key": str(uuid4()),
        },
        payload=payload,
    )

    _assert_error(response, 400, "QIT000001")


@pytest.mark.parametrize("invalid_amount", [999, 0])
def test_transfer_rejects_amount_below_minimum(
    invalid_amount: int,
) -> None:
    source_key = open_funded_account_via_api(balance_cents=100_000)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        invalid_amount,
    )

    _assert_error(response, 422, "TRX0004")
    assert get_account_via_api(source_key)["balance_cents"] == 100_000
    assert get_account_via_api(target_key)["balance_cents"] == 0
    assert list_statement_via_api(source_key)["data"] == []
    assert list_statement_via_api(target_key)["data"] == []


def test_transfer_rejects_self_transfer_without_consuming_key() -> None:
    account_key = open_funded_account_via_api(balance_cents=100_000)
    idempotency_key = uuid4()

    response = send_transfer(
        account_key,
        account_key,
        idempotency_key,
    )

    _assert_error(response, 409, "TRX0002")
    assert get_account_via_api(account_key)["balance_cents"] == 100_000
    assert list_statement_via_api(account_key)["data"] == []


def test_transfer_returns_source_account_not_found(
    api_database_engine: Engine,
) -> None:
    # The source account intentionally does not exist, so there is no R05/R08
    # projection to assert "source is None" against; keep the SQL probe while
    # the live target is still verified below.
    source_key = str(uuid4())
    target_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 404, "ACC0001")
    assert state["source"] is None
    assert state["target"]["balance_cents"] == 0
    assert state["transactions"] == []
    assert state["entries"] == []


def test_transfer_returns_target_account_not_found(
    api_database_engine: Engine,
) -> None:
    # The target account intentionally does not exist, so there is no R05/R08
    # projection to assert "target is None" against; keep the SQL probe while
    # the live source is still verified below.
    source_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    target_key = str(uuid4())
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 404, "ACC0001")
    assert state["source"]["balance_cents"] == 100_000
    assert state["target"] is None
    assert state["transactions"] == []
    assert state["entries"] == []


@pytest.mark.parametrize("status", ["INACTIVE", "CLOSED"])
def test_transfer_rejects_non_active_source(
    api_database_engine: Engine,
    status: str,
) -> None:
    # An INACTIVE/CLOSED source cannot be arranged through the public API
    # (R04 always opens an ACTIVE account), so the pre-state and persistence
    # check stay on SQL.
    initial_balance = 100_000 if status == "INACTIVE" else 0
    source_key = create_account(
        api_database_engine,
        status=status,
        balance_cents=initial_balance,
    )
    target_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 409, "ACC0005")
    assert state["source"]["balance_cents"] == initial_balance
    assert state["target"]["balance_cents"] == 0
    assert state["transactions"] == []
    assert state["entries"] == []


@pytest.mark.parametrize("status", ["INACTIVE", "CLOSED"])
def test_transfer_rejects_non_active_target(
    api_database_engine: Engine,
    status: str,
) -> None:
    # An INACTIVE/CLOSED target cannot be arranged through the public API
    # (R04 always opens an ACTIVE account), so the pre-state and persistence
    # check stay on SQL.
    source_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    target_key = create_account(api_database_engine, status=status)
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 409, "ACC0005")
    assert state["source"]["balance_cents"] == 100_000
    assert state["target"]["balance_cents"] == 0
    assert state["transactions"] == []
    assert state["entries"] == []


def test_transfer_rejects_insufficient_balance() -> None:
    source_key = open_funded_account_via_api(balance_cents=50_249)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)

    _assert_error(response, 422, "TRX0001")
    assert get_account_via_api(source_key)["balance_cents"] == 50_249
    assert get_account_via_api(target_key)["balance_cents"] == 0
    assert list_statement_via_api(source_key)["data"] == []
    assert list_statement_via_api(target_key)["data"] == []


def test_transfer_accepts_exact_amount_plus_fee_balance() -> None:
    source_key = open_funded_account_via_api(balance_cents=50_250)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_transfer(source_key, target_key, idempotency_key)

    assert response.response_status == 201
    assert response.response_json["fee_cents"] == 250
    assert get_account_via_api(source_key)["balance_cents"] == 0
    assert get_account_via_api(target_key)["balance_cents"] == 50_000
    # Exactly one transaction producing the two source-side entries
    # (PRINCIPAL + FEE); the third ledger entry is the target CREDIT, proven
    # by the target balance above.
    source_entries = list_statement_via_api(
        source_key,
        query_params={"order_by": "asc"},
    )["data"]
    assert [entry["entry_type"] for entry in source_entries] == [
        "PRINCIPAL",
        "FEE",
    ]
    target_entries = list_statement_via_api(target_key)["data"]
    assert len(target_entries) == 1
    assert target_entries[0]["entry_type"] == "PRINCIPAL"


def test_transfer_rejects_amount_above_bigint() -> None:
    source_key = open_funded_account_via_api(balance_cents=100_000)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        BIGINT_MAX + 1,
    )

    _assert_error(response, 422, "TRX0004")
    assert get_account_via_api(source_key)["balance_cents"] == 100_000
    assert get_account_via_api(target_key)["balance_cents"] == 0
    assert list_statement_via_api(source_key)["data"] == []
    assert list_statement_via_api(target_key)["data"] == []


def test_transfer_rejects_amount_plus_fee_above_bigint(
    api_database_engine: Engine,
) -> None:
    # A source balance of BIGINT_MAX is unreachable through API deposits
    # (the overflow guard rejects it), so the near-overflow pre-state and its
    # persistence check stay on SQL.
    source_key = create_account(
        api_database_engine,
        balance_cents=BIGINT_MAX,
    )
    target_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        BIGINT_MAX,
    )
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 422, "TRX0004")
    assert state["source"]["balance_cents"] == BIGINT_MAX
    assert state["target"]["balance_cents"] == 0
    assert state["transactions"] == []
    assert state["entries"] == []


def test_transfer_rejects_target_balance_overflow(
    api_database_engine: Engine,
) -> None:
    # A target balance of BIGINT_MAX-500 is unreachable through API deposits
    # (the overflow guard rejects it), so the near-overflow pre-state and its
    # persistence check stay on SQL.
    source_key = create_account(
        api_database_engine,
        balance_cents=2_000,
    )
    target_key = create_account(
        api_database_engine,
        balance_cents=BIGINT_MAX - 500,
    )
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        1_000,
    )
    state = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    _assert_error(response, 422, "TRX0004")
    assert state["source"]["balance_cents"] == 2_000
    assert state["target"]["balance_cents"] == BIGINT_MAX - 500
    assert state["transactions"] == []
    assert state["entries"] == []
