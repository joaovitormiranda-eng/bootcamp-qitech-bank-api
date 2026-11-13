"""Pricing PF/PJ aplicado ao fluxo real de TRANSFER (black-box via HTTP)."""

from uuid import uuid4

import pytest

from tests.integration.transaction.support import (
    get_account_via_api,
    list_statement_via_api,
    open_funded_account_via_api,
    send_transfer,
)


@pytest.mark.parametrize(
    ("source_type", "target_type", "expected_fee_cents"),
    [
        ("INDIVIDUAL", "INDIVIDUAL", 250),
        ("INDIVIDUAL", "COMPANY", 250),
        ("COMPANY", "INDIVIDUAL", 500),
        ("COMPANY", "COMPANY", 500),
    ],
)
def test_transfer_fee_depends_only_on_source_client_type(
    source_type: str,
    target_type: str,
    expected_fee_cents: int,
) -> None:
    amount_cents = 50_000
    initial_source_balance = 100_000
    source_key = open_funded_account_via_api(
        client_type=source_type,
        balance_cents=initial_source_balance,
    )
    target_key = open_funded_account_via_api(client_type=target_type)
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        amount_cents,
    )

    assert response.response_status == 201
    assert response.response_json["fee_cents"] == expected_fee_cents

    source_entries = list_statement_via_api(
        source_key,
        query_params={"order_by": "asc"},
    )["data"]
    # Ordem estável do lançamento: PRINCIPAL antes da FEE na origem.
    assert [entry["entry_type"] for entry in source_entries] == [
        "PRINCIPAL",
        "FEE",
    ]
    fee_entry = source_entries[1]
    assert fee_entry["direction"] == "DEBIT"
    assert fee_entry["entry_type"] == "FEE"
    assert fee_entry["amount_cents"] == expected_fee_cents

    source_account = get_account_via_api(source_key)
    target_account = get_account_via_api(target_key)
    assert source_account["balance_cents"] == (
        initial_source_balance - amount_cents - expected_fee_cents
    )
    assert target_account["balance_cents"] == amount_cents


@pytest.mark.parametrize(
    ("source_type", "amount_cents", "expected_fee_cents"),
    [
        ("INDIVIDUAL", 1_000, 50),
        ("INDIVIDUAL", 50_000, 250),
        ("INDIVIDUAL", 1_000_000, 1_000),
        ("INDIVIDUAL", 20_100, 101),
        ("COMPANY", 1_000, 100),
        ("COMPANY", 50_000, 500),
        ("COMPANY", 1_000_000, 1_500),
        ("COMPANY", 20_050, 201),
    ],
    ids=[
        "individual-floor",
        "individual-percentage",
        "individual-cap",
        "individual-half-up",
        "company-floor",
        "company-percentage",
        "company-cap",
        "company-half-up",
    ],
)
def test_transfer_persists_source_pricing_profile_fee(
    source_type: str,
    amount_cents: int,
    expected_fee_cents: int,
) -> None:
    initial_source_balance = amount_cents + expected_fee_cents + 10_000
    source_key = open_funded_account_via_api(
        client_type=source_type,
        balance_cents=initial_source_balance,
    )
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        amount_cents,
    )

    assert response.response_status == 201
    assert response.response_json["fee_cents"] == expected_fee_cents

    source_entries = list_statement_via_api(
        source_key,
        query_params={"order_by": "asc"},
    )["data"]
    assert len(source_entries) == 2
    assert [entry["entry_type"] for entry in source_entries] == [
        "PRINCIPAL",
        "FEE",
    ]
    assert source_entries[1]["entry_type"] == "FEE"
    assert source_entries[1]["amount_cents"] == expected_fee_cents

    source_account = get_account_via_api(source_key)
    target_account = get_account_via_api(target_key)
    assert source_account["balance_cents"] == (
        initial_source_balance - amount_cents - expected_fee_cents
    )
    assert target_account["balance_cents"] == amount_cents
