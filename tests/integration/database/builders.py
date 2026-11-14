"""Linhas pai mínimas para exercitar FKs sem passar pela API HTTP."""

from uuid import uuid4

from sqlalchemy import text


def create_client(connection, *, status="ACTIVE", client_type="INDIVIDUAL", email=None):
    """Insere um cliente válido e devolve o ID; `email` permite testar UNIQUE.

    `client_type` é resolvido para a FK `client_type_id` via a lookup
    `client_type`; um valor fora do domínio não encontra lookup e dispara a
    violação de FK (23503), que os testes de contrato verificam.
    """
    client_key = str(uuid4())
    return connection.execute(
        text("""
            INSERT INTO client (
                client_key, client_type_id, email, timezone, status_id,
                created_at, updated_at
            )
            VALUES (
                :client_key,
                (SELECT id FROM client_type WHERE enumerator = :client_type),
                :email, 'America/Sao_Paulo',
                (SELECT id FROM client_status WHERE enumerator = :status),
                NOW(), NOW()
            )
            RETURNING id
        """),
        {
            "client_key": client_key,
            "client_type": client_type,
            "email": email or f"{client_key}@example.test",
            "status": status,
        },
    ).scalar_one()


def create_account(connection, *, client_id=None):
    """Insere uma conta ACTIVE; cria o cliente pai quando ele não é fornecido."""
    if client_id is None:
        client_id = create_client(connection)
    return connection.execute(
        text("""
            INSERT INTO account (
                account_key, client_id, status_id, created_at, updated_at
            )
            VALUES (
                :account_key, :client_id,
                (SELECT id FROM account_status WHERE enumerator = 'ACTIVE'),
                NOW(), NOW()
            )
            RETURNING id
        """),
        {"account_key": str(uuid4()), "client_id": client_id},
    ).scalar_one()


def create_transaction(connection, *, transaction_type="DEPOSIT", request_control_key=None):
    """Insere uma operação válida, com chave de controle opcional para colisões.

    `transaction_type` é resolvido para a FK `transaction_type_id`.
    """
    return connection.execute(
        text("""
            INSERT INTO financial_transaction (
                transaction_key, request_control_key, request_hash,
                transaction_type_id, created_at
            )
            VALUES (
                :transaction_key, :request_control_key, :request_hash,
                (SELECT id FROM transaction_type WHERE enumerator = :transaction_type),
                NOW()
            )
            RETURNING id
        """),
        {
            "transaction_key": str(uuid4()),
            "request_control_key": request_control_key or str(uuid4()),
            "request_hash": "0" * 64,
            "transaction_type": transaction_type,
        },
    ).scalar_one()


def insert_entry(
    connection,
    *,
    transaction_id,
    account_id,
    direction="CREDIT",
    entry_type="PRINCIPAL",
    amount_cents=1,
    balance_after_cents=1,
):
    """Insere um lançamento com valores padrão válidos e devolve seu ID.

    `direction` e `entry_type` são resolvidos para as FKs `direction_id` e
    `entry_type_id`; `entry_key` recebe um UUID público próprio.
    """
    return connection.execute(
        text("""
            INSERT INTO transaction_entry (
                entry_key, transaction_id, account_id, direction_id, entry_type_id,
                amount_cents, balance_after_cents, created_at
            )
            VALUES (
                :entry_key, :transaction_id, :account_id,
                (SELECT id FROM transaction_direction WHERE enumerator = :direction),
                (SELECT id FROM entry_type WHERE enumerator = :entry_type),
                :amount_cents, :balance_after_cents, NOW()
            )
            RETURNING id
        """),
        {
            "entry_key": str(uuid4()),
            "transaction_id": transaction_id,
            "account_id": account_id,
            "direction": direction,
            "entry_type": entry_type,
            "amount_cents": amount_cents,
            "balance_after_cents": balance_after_cents,
        },
    ).scalar_one()
