from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine

from tests.utils import INTERNAL_TOKEN, RandomGenerator
from tests.utils.requisition import ClientRequisition


TRANSACTION_RESPONSE_FIELDS = {
    "transaction_key",
    "transaction_type",
    "account_key",
    "counterparty_account_key",
    "amount_cents",
    "fee_cents",
    "created_at",
}


def create_account(
    api_database_engine: Engine,
    *,
    client_type: str = "INDIVIDUAL",
    status: str = "ACTIVE",
    balance_cents: int = 0,
) -> str:
    client_key = uuid4()
    account_key = uuid4()
    email = f"r07.transaction.{uuid4()}@example.com"
    created_at = datetime.now(timezone.utc)
    client_status = "ACTIVE" if status == "ACTIVE" else "INACTIVE"

    with api_database_engine.begin() as connection:
        client_id = connection.execute(
            text(
                """
                INSERT INTO client (
                    client_key, client_type, email, timezone, status_id,
                    created_at, updated_at
                ) VALUES (
                    :client_key, :client_type, :email, 'America/Sao_Paulo',
                    (SELECT id FROM client_status
                     WHERE enumerator = :client_status),
                    :created_at, :created_at
                )
                RETURNING id
                """
            ),
            {
                "client_key": client_key,
                "client_type": client_type,
                "email": email,
                "client_status": client_status,
                "created_at": created_at,
            },
        ).scalar_one()
        if client_type == "INDIVIDUAL":
            document = "".join(
                character
                for character in RandomGenerator.generate_cpf()
                if character.isdigit()
            )
            connection.execute(
                text(
                    """
                    INSERT INTO individual_client (
                        client_id, cpf, full_name, birth_date
                    ) VALUES (
                        :client_id, :document,
                        'Cliente R07 Transaction', '1990-05-17'
                    )
                    """
                ),
                {"client_id": client_id, "document": document},
            )
        else:
            document = "".join(
                character
                for character in RandomGenerator.generate_cnpj()
                if character.isdigit()
            )
            connection.execute(
                text(
                    """
                    INSERT INTO company_client (
                        client_id, cnpj, legal_name, trade_name
                    ) VALUES (
                        :client_id, :document,
                        'Empresa R07 Transaction Ltda.',
                        'Empresa R07 Transaction'
                    )
                    """
                ),
                {"client_id": client_id, "document": document},
            )
        connection.execute(
            text(
                """
                INSERT INTO account (
                    account_key, client_id, status_id, balance_cents,
                    created_at, updated_at
                ) VALUES (
                    :account_key, :client_id,
                    (SELECT id FROM account_status WHERE enumerator = :status),
                    :balance_cents, :created_at, :created_at
                )
                """
            ),
            {
                "account_key": account_key,
                "client_id": client_id,
                "status": status,
                "balance_cents": balance_cents,
                "created_at": created_at,
            },
        )

    return str(account_key)


def send_deposit(
    account_key: str,
    idempotency_key: UUID | str | None,
    amount_cents: int = 50_000,
):
    headers = {"INTERNAL-TOKEN": INTERNAL_TOKEN}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = str(idempotency_key)

    return ClientRequisition.send(
        "POST",
        f"/account/{account_key}/transaction",
        headers=headers,
        payload={
            "transaction_type": "DEPOSIT",
            "amount_cents": amount_cents,
        },
    )


def send_transfer(
    source_account_key: str,
    target_account_key: str,
    idempotency_key: UUID | str,
    amount_cents: int = 50_000,
):
    return ClientRequisition.send(
        "POST",
        f"/account/{source_account_key}/transaction",
        headers={
            "INTERNAL-TOKEN": INTERNAL_TOKEN,
            "Idempotency-Key": str(idempotency_key),
        },
        payload={
            "transaction_type": "TRANSFER",
            "target_account_key": target_account_key,
            "amount_cents": amount_cents,
        },
    )


def read_transfer_state(
    api_database_engine: Engine,
    source_account_key: str,
    target_account_key: str,
    idempotency_key: UUID,
) -> dict:
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        account_rows = connection.execute(
            text(
                """
                SELECT account.account_key, account.balance_cents,
                       account.updated_at,
                       account_status.enumerator AS status
                FROM account
                JOIN account_status ON account_status.id = account.status_id
                WHERE account.account_key IN (
                    :source_account_key,
                    :target_account_key
                )
                """
            ),
            {
                "source_account_key": UUID(source_account_key),
                "target_account_key": UUID(target_account_key),
            },
        ).mappings().all()
        transactions = connection.execute(
            text(
                """
                SELECT financial_transaction.id,
                       financial_transaction.transaction_key,
                       financial_transaction.request_control_key,
                       financial_transaction.request_hash,
                       transaction_type.enumerator AS transaction_type,
                       financial_transaction.created_at
                FROM financial_transaction
                JOIN transaction_type
                  ON transaction_type.id = financial_transaction.transaction_type_id
                WHERE request_control_key = :request_control_key
                ORDER BY financial_transaction.id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()
        entries = connection.execute(
            text(
                """
                SELECT entry.id, entry.transaction_id, account.account_key,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents, entry.balance_after_cents,
                       entry.created_at
                FROM transaction_entry AS entry
                JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                JOIN account ON account.id = entry.account_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type ON entry_type.id = entry.entry_type_id
                WHERE transaction.request_control_key = :request_control_key
                ORDER BY entry.id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()

    accounts = {
        str(account["account_key"]): account for account in account_rows
    }
    return {
        "source": accounts.get(source_account_key),
        "target": accounts.get(target_account_key),
        "transactions": transactions,
        "entries": entries,
    }


def read_deposit_state(
    api_database_engine: Engine,
    account_key: str,
    idempotency_key: UUID,
) -> dict:
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        account = connection.execute(
            text(
                """
                SELECT account.id, account.balance_cents, account.updated_at,
                       account_status.enumerator AS status
                FROM account
                JOIN account_status ON account_status.id = account.status_id
                WHERE account_key = :account_key
                """
            ),
            {"account_key": UUID(account_key)},
        ).mappings().one()
        transactions = connection.execute(
            text(
                """
                SELECT id, transaction_key, request_control_key, request_hash
                FROM financial_transaction
                WHERE request_control_key = :request_control_key
                ORDER BY id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()
        entries = connection.execute(
            text(
                """
                SELECT entry.transaction_id,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents
                FROM transaction_entry AS entry
                JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type ON entry_type.id = entry.entry_type_id
                WHERE transaction.request_control_key = :request_control_key
                ORDER BY entry.id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()

    return {
        "balance_cents": account["balance_cents"],
        "updated_at": account["updated_at"],
        "status": account["status"],
        "transactions": transactions,
        "entries": entries,
    }


def read_request_state(
    api_database_engine: Engine,
    idempotency_key: UUID,
) -> dict:
    with api_database_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        transactions = connection.execute(
            text(
                """
                SELECT id, transaction_key, request_control_key, request_hash
                FROM financial_transaction
                WHERE request_control_key = :request_control_key
                ORDER BY id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()
        entries = connection.execute(
            text(
                """
                SELECT entry.transaction_id,
                       transaction_direction.enumerator AS direction,
                       entry_type.enumerator AS entry_type,
                       entry.amount_cents
                FROM transaction_entry AS entry
                JOIN financial_transaction AS transaction
                  ON transaction.id = entry.transaction_id
                JOIN transaction_direction
                  ON transaction_direction.id = entry.direction_id
                JOIN entry_type ON entry_type.id = entry.entry_type_id
                WHERE transaction.request_control_key = :request_control_key
                ORDER BY entry.id
                """
            ),
            {"request_control_key": idempotency_key},
        ).mappings().all()

    return {
        "transactions": transactions,
        "entries": entries,
    }


def set_account_status(
    api_database_engine: Engine,
    account_key: str,
    status: str,
) -> None:
    with api_database_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE account
                SET status_id = (
                    SELECT id FROM account_status WHERE enumerator = :status
                )
                WHERE account_key = :account_key
                """
            ),
            {
                "account_key": UUID(account_key),
                "status": status,
            },
        )
