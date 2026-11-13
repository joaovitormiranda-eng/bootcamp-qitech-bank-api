"""Idempotência sequencial e replay histórico da TRANSFER (black-box)."""

from uuid import uuid4

from tests.integration.transaction.support import (
    get_account_via_api,
    list_statement_via_api,
    open_funded_account_via_api,
    send_transfer,
)
from tests.utils import INTERNAL_TOKEN
from tests.utils.requisition import ClientRequisition


def test_transfer_replays_original_transaction_without_new_movement() -> None:
    source_key = open_funded_account_via_api(balance_cents=100_000)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    original_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
    )
    replay_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
    )

    assert original_response.response_status == 201
    assert replay_response.response_status == 201
    assert replay_response.response_json == original_response.response_json
    assert replay_response.response_json["fee_cents"] == 250

    assert get_account_via_api(source_key)["balance_cents"] == 49_750
    assert get_account_via_api(target_key)["balance_cents"] == 50_000

    # Nenhum movimento adicional: origem mantém PRINCIPAL+FEE e destino o
    # único CREDIT, mesmo após o replay.
    source_entries = list_statement_via_api(source_key)["data"]
    target_entries = list_statement_via_api(target_key)["data"]
    assert {entry["entry_type"] for entry in source_entries} == {
        "PRINCIPAL",
        "FEE",
    }
    assert len(source_entries) == 2
    assert len(target_entries) == 1
    assert {
        entry["transaction_key"]
        for entry in source_entries + target_entries
    } == {original_response.response_json["transaction_key"]}


def test_transfer_rejects_same_key_for_different_intention() -> None:
    source_key = open_funded_account_via_api(balance_cents=100_000)
    target_key = open_funded_account_via_api()
    idempotency_key = uuid4()

    original_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        50_000,
    )
    conflict_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        60_000,
    )

    assert original_response.response_status == 201
    assert conflict_response.response_status == 409
    assert conflict_response.response_json["code"] == "TRX0003"

    assert get_account_via_api(source_key)["balance_cents"] == 49_750
    assert get_account_via_api(target_key)["balance_cents"] == 50_000

    source_entries = list_statement_via_api(source_key)["data"]
    target_entries = list_statement_via_api(target_key)["data"]
    assert len(source_entries) == 2
    assert len(target_entries) == 1


def test_transfer_replay_survives_real_r06_closure_but_new_operation_does_not(
) -> None:
    source_key = open_funded_account_via_api(balance_cents=50_250)
    target_key = open_funded_account_via_api()
    original_key = uuid4()

    original_response = send_transfer(
        source_key,
        target_key,
        original_key,
    )
    assert original_response.response_status == 201
    assert get_account_via_api(source_key)["balance_cents"] == 0
    assert get_account_via_api(target_key)["balance_cents"] == 50_000

    close_response = ClientRequisition.send(
        "PATCH",
        f"/account/{source_key}",
        headers={"INTERNAL-TOKEN": INTERNAL_TOKEN},
        payload={
            "status": "CLOSED",
            "reason": "Encerramento após transferência R07",
        },
    )
    assert close_response.response_status == 200
    assert close_response.response_json == {
        "account_key": source_key,
        "status": "CLOSED",
    }

    replay_response = send_transfer(
        source_key,
        target_key,
        original_key,
    )

    assert replay_response.response_status == 201
    assert replay_response.response_json == original_response.response_json
    assert replay_response.response_json["fee_cents"] == 250

    source_after_replay = get_account_via_api(source_key)
    assert source_after_replay["status"] == "CLOSED"
    assert source_after_replay["balance_cents"] == 0
    assert get_account_via_api(target_key)["balance_cents"] == 50_000

    source_entries = list_statement_via_api(source_key)["data"]
    target_entries = list_statement_via_api(target_key)["data"]
    assert len(source_entries) == 2
    assert len(target_entries) == 1
    assert {
        entry["transaction_key"]
        for entry in source_entries + target_entries
    } == {original_response.response_json["transaction_key"]}

    new_key = uuid4()
    new_response = send_transfer(
        source_key,
        target_key,
        new_key,
    )

    assert new_response.response_status == 409
    assert new_response.response_json["code"] == "ACC0005"

    new_source = get_account_via_api(source_key)
    assert new_source["status"] == "CLOSED"
    assert new_source["balance_cents"] == 0
    assert get_account_via_api(target_key)["balance_cents"] == 50_000

    # Nenhuma nova movimentação foi criada pela operação rejeitada.
    source_entries_after = list_statement_via_api(source_key)["data"]
    target_entries_after = list_statement_via_api(target_key)["data"]
    assert len(source_entries_after) == 2
    assert len(target_entries_after) == 1
    assert {
        entry["transaction_key"]
        for entry in source_entries_after + target_entries_after
    } == {original_response.response_json["transaction_key"]}
