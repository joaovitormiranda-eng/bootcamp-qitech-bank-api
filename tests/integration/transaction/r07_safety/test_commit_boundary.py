"""Fronteira de commit da R07 (COD-11): um único commit persiste a unidade.

Estes testes são aditivos e específicos da fronteira de commit: afirmam
resultados OBSERVÁVEIS (status/corpo HTTP + contagem de linhas via os
helpers read_*), de modo que falhariam se o commit fosse movido para o
middleware, duplicado ou removido. Não enfraquecem nem duplicam as
asserções dos demais testes de r07_safety.
"""

from uuid import uuid4

from sqlalchemy.engine import Engine

from tests.integration.transaction.support import (
    create_account,
    read_deposit_state,
    read_transfer_state,
    send_deposit,
    send_transfer,
)


def test_successful_deposit_commits_exactly_one_transaction_and_entry(
    api_database_engine: Engine,
) -> None:
    account_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    response = send_deposit(account_key, idempotency_key)
    state = read_deposit_state(
        api_database_engine,
        account_key,
        idempotency_key,
    )

    # COD-11: o commit público único persistiu exatamente uma transação e
    # um lançamento com o saldo final committado.
    assert response.response_status == 201
    assert state["balance_cents"] == 50_000
    assert len(state["transactions"]) == 1
    assert len(state["entries"]) == 1
    assert str(state["transactions"][0]["transaction_key"]) == (
        response.response_json["transaction_key"]
    )
    entry = state["entries"][0]
    assert entry["direction"] == "CREDIT"
    assert entry["entry_type"] == "PRINCIPAL"
    assert entry["amount_cents"] == 50_000


def test_successful_transfer_commits_exactly_one_transaction_and_three_entries(
    api_database_engine: Engine,
) -> None:
    source_key = create_account(
        api_database_engine,
        balance_cents=100_000,
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

    # COD-11: um único commit persiste a unidade inteira (principal + fee +
    # crédito do destino) com os saldos finais. PF 0,50% de 50_000 = 250.
    assert response.response_status == 201
    assert response.response_json["fee_cents"] == 250
    assert state["source"]["balance_cents"] == 49_750
    assert state["target"]["balance_cents"] == 50_000
    assert len(state["transactions"]) == 1
    assert len(state["entries"]) == 3
    assert str(state["transactions"][0]["transaction_key"]) == (
        response.response_json["transaction_key"]
    )
    assert [
        (
            str(entry["account_key"]),
            entry["direction"],
            entry["entry_type"],
            entry["amount_cents"],
            entry["balance_after_cents"],
        )
        for entry in state["entries"]
    ] == [
        (source_key, "DEBIT", "PRINCIPAL", 50_000, 50_000),
        (source_key, "DEBIT", "FEE", 250, 49_750),
        (target_key, "CREDIT", "PRINCIPAL", 50_000, 50_000),
    ]


def test_idempotent_replay_returns_same_body_and_commits_no_new_work(
    api_database_engine: Engine,
) -> None:
    source_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    target_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    original_response = send_transfer(source_key, target_key, idempotency_key)
    state_before_replay = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    replay_response = send_transfer(source_key, target_key, idempotency_key)
    state_after_replay = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    # COD-11: o caminho de replay reusa a transação original e NÃO comita
    # trabalho novo; o corpo 201 é idêntico e nada é adicionado ao banco.
    assert original_response.response_status == 201
    assert replay_response.response_status == 201
    assert replay_response.response_json == original_response.response_json
    assert len(state_before_replay["transactions"]) == 1
    assert len(state_before_replay["entries"]) == 3
    assert len(state_after_replay["transactions"]) == (
        len(state_before_replay["transactions"])
    )
    assert len(state_after_replay["entries"]) == (
        len(state_before_replay["entries"])
    )
    assert state_after_replay["source"]["balance_cents"] == 49_750
    assert state_after_replay["target"]["balance_cents"] == 50_000
    assert state_after_replay["source"]["updated_at"] == (
        state_before_replay["source"]["updated_at"]
    )
    assert state_after_replay["target"]["updated_at"] == (
        state_before_replay["target"]["updated_at"]
    )


def test_incompatible_key_reuse_returns_409_and_persists_no_new_work(
    api_database_engine: Engine,
) -> None:
    source_key = create_account(
        api_database_engine,
        balance_cents=100_000,
    )
    target_key = create_account(api_database_engine)
    other_target_key = create_account(api_database_engine)
    idempotency_key = uuid4()

    original_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        amount_cents=50_000,
    )
    state_before_conflict = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    # Reuso incompatível da mesma Idempotency-Key: valor diferente.
    amount_conflict_response = send_transfer(
        source_key,
        target_key,
        idempotency_key,
        amount_cents=60_000,
    )
    # Reuso incompatível da mesma Idempotency-Key: destino diferente.
    target_conflict_response = send_transfer(
        source_key,
        other_target_key,
        idempotency_key,
        amount_cents=50_000,
    )
    state_after_conflict = read_transfer_state(
        api_database_engine,
        source_key,
        target_key,
        idempotency_key,
    )

    # COD-11: um conflito de intenção é rejeitado com 409 e NÃO comita nada
    # novo; a transação original permanece intacta.
    assert original_response.response_status == 201
    assert amount_conflict_response.response_status == 409
    assert amount_conflict_response.response_json["code"] == "TRX0003"
    assert target_conflict_response.response_status == 409
    assert target_conflict_response.response_json["code"] == "TRX0003"
    assert len(state_after_conflict["transactions"]) == (
        len(state_before_conflict["transactions"])
    ) == 1
    assert len(state_after_conflict["entries"]) == (
        len(state_before_conflict["entries"])
    ) == 3
    assert state_after_conflict["source"]["balance_cents"] == 49_750
    assert state_after_conflict["target"]["balance_cents"] == 50_000
