"""Contrato físico das operações e movimentações financeiras."""

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from tests.integration.database.assertions import (
    assert_columns_and_primary_key,
    assert_foreign_keys,
    assert_index,
    assert_unique,
)
from tests.integration.database.builders import create_account, create_transaction, insert_entry


class TestFinancialTransactionSchema:
    """Identidade, tipo e chave de controle das operações financeiras."""

    def test_columns_and_primary_key(self, schema_engine):
        """As chaves são UUID e o hash da requisição ocupa 64 caracteres.

        P1-D/COD-06: o tipo de operação é a FK `transaction_type_id`.
        """
        assert_columns_and_primary_key(
            schema_engine,
            "financial_transaction",
            {
                "id": ("bigint", None, "NO"),
                "transaction_key": ("uuid", None, "NO"),
                "request_control_key": ("uuid", None, "NO"),
                "request_hash": ("character", 64, "NO"),
                "transaction_type_id": ("bigint", None, "NO"),
                "created_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_transaction_type_foreign_key_is_restricted(self, schema_engine):
        """transaction_type_id referencia a lookup sem exclusão em cascata."""
        assert_foreign_keys(
            schema_engine,
            "financial_transaction",
            {("transaction_type_id", "transaction_type", "id", "RESTRICT")},
        )

    @pytest.mark.parametrize("column_name", ["transaction_key", "request_control_key"])
    def test_business_key_is_unique(self, schema_engine, column_name):
        """Cada chave pública/de controle tem uma constraint UNIQUE própria."""
        assert_unique(schema_engine, "financial_transaction", column_name)

    @pytest.mark.parametrize("transaction_type", ["DEPOSIT", "TRANSFER"])
    def test_accepts_approved_transaction_type(self, db_connection, transaction_type):
        """DEPOSIT e TRANSFER são os dois tipos aceitos pelo schema v1.2."""
        transaction_id = create_transaction(db_connection, transaction_type=transaction_type)
        assert transaction_id > 0

    def test_rejects_unknown_transaction_type(self, db_connection):
        """WITHDRAW não está na lookup; a FK rejeita o id inexistente (23503)."""
        missing_type_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM transaction_type")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO financial_transaction (
                        transaction_key, request_control_key, request_hash,
                        transaction_type_id, created_at
                    )
                    VALUES (
                        :transaction_key, :request_control_key, :request_hash,
                        :transaction_type_id, NOW()
                    )
                """),
                {
                    "transaction_key": str(uuid4()),
                    "request_control_key": str(uuid4()),
                    "request_hash": "0" * 64,
                    "transaction_type_id": missing_type_id,
                },
            )
        assert error.value.orig.pgcode == "23503"  # FK violation

    def test_request_control_key_is_globally_unique(self, db_connection):
        """Uma chave de idempotência não pode ser reutilizada em outro tipo."""
        request_control_key = str(uuid4())
        create_transaction(db_connection, request_control_key=request_control_key)
        with pytest.raises(IntegrityError) as error:
            create_transaction(
                db_connection,
                transaction_type="TRANSFER",
                request_control_key=request_control_key,
            )
        assert error.value.orig.pgcode == "23505"  # UNIQUE violation


class TestTransactionEntrySchema:
    """Lançamentos positivos ligados à operação e à conta afetada."""

    def test_columns_and_primary_key(self, schema_engine):
        """Valor e saldo posterior são BIGINT; data possui fuso horário.

        P1-D/COD-05: a entry ganha a chave pública `entry_key` (UUID), mantendo
        `id` como PK interna.
        P1-D/COD-06: `direction` e `entry_type` viram FKs `*_id`.
        """
        assert_columns_and_primary_key(
            schema_engine,
            "transaction_entry",
            {
                "id": ("bigint", None, "NO"),
                "entry_key": ("uuid", None, "NO"),
                "transaction_id": ("bigint", None, "NO"),
                "account_id": ("bigint", None, "NO"),
                "direction_id": ("bigint", None, "NO"),
                "entry_type_id": ("bigint", None, "NO"),
                "amount_cents": ("bigint", None, "NO"),
                "balance_after_cents": ("bigint", None, "NO"),
                "created_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_entry_key_is_unique(self, schema_engine):
        """A chave pública da entry tem constraint UNIQUE própria (COD-05)."""
        assert_unique(schema_engine, "transaction_entry", "entry_key")

    def test_foreign_keys_are_restricted(self, schema_engine):
        """Lançamento exige operação, conta, direção e natureza, sem cascata."""
        assert_foreign_keys(
            schema_engine,
            "transaction_entry",
            {
                ("transaction_id", "financial_transaction", "id", "RESTRICT"),
                ("account_id", "account", "id", "RESTRICT"),
                ("direction_id", "transaction_direction", "id", "RESTRICT"),
                ("entry_type_id", "entry_type", "id", "RESTRICT"),
            },
        )

    @pytest.mark.parametrize(
        ("index_name", "columns"),
        [
            ("idx_transaction_entry_account", ["account_id"]),
            ("idx_transaction_entry_transaction", ["transaction_id"]),
        ],
    )
    def test_statement_indexes_are_non_unique(
        self,
        schema_engine,
        index_name,
        columns,
    ):
        """O extrato localiza entries por conta e por transacao."""
        assert_index(
            schema_engine,
            "transaction_entry",
            index_name,
            columns,
        )
        index = next(
            item
            for item in inspect(schema_engine).get_indexes(
                "transaction_entry",
                schema="public",
            )
            if item["name"] == index_name
        )
        assert index["unique"] is False

    def test_accepts_positive_credit(self, db_connection):
        """Crédito PRINCIPAL de valor positivo é persistível."""
        account_id = create_account(db_connection)
        _set_balance(db_connection, account_id, 1)
        transaction_id = create_transaction(db_connection)
        entry_id = insert_entry(
            db_connection, account_id=account_id, transaction_id=transaction_id
        )
        assert entry_id > 0

    def test_accepts_debit_fee(self, db_connection):
        """Débito de tarifa pode ser registrado com saldo final válido."""
        account_id = create_account(db_connection)
        _set_balance(db_connection, account_id, 9)
        transaction_id = create_transaction(db_connection, transaction_type="TRANSFER")
        entry_id = insert_entry(
            db_connection,
            account_id=account_id,
            transaction_id=transaction_id,
            direction="DEBIT",
            entry_type="FEE",
            amount_cents=1,
            balance_after_cents=9,
        )
        assert entry_id > 0

    @pytest.mark.parametrize(
        "invalid_entry",
        [
            pytest.param({"amount_cents": 0}, id="amount_zero"),
            pytest.param({"balance_after_cents": -1}, id="negative_balance"),
        ],
    )
    def test_rejects_invalid_values(self, db_connection, invalid_entry):
        """CHECKs recusam valores monetários fora do domínio (amount/saldo)."""
        account_id = create_account(db_connection)
        _set_balance(db_connection, account_id, 1)
        transaction_id = create_transaction(db_connection)
        with pytest.raises(IntegrityError) as error:
            insert_entry(
                db_connection,
                account_id=account_id,
                transaction_id=transaction_id,
                **invalid_entry,
            )
        assert error.value.orig.pgcode == "23514"

    def test_rejects_unknown_direction(self, db_connection):
        """P1-D/COD-06: direção fora da lookup dispara violação de FK (23503)."""
        account_id = create_account(db_connection)
        _set_balance(db_connection, account_id, 1)
        transaction_id = create_transaction(db_connection)
        missing_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM transaction_direction")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO transaction_entry (
                        entry_key, transaction_id, account_id, direction_id,
                        entry_type_id, amount_cents, balance_after_cents, created_at
                    )
                    VALUES (
                        :entry_key, :transaction_id, :account_id, :missing_id,
                        (SELECT id FROM entry_type WHERE enumerator = 'PRINCIPAL'),
                        1, 1, NOW()
                    )
                """),
                {
                    "entry_key": str(uuid4()),
                    "transaction_id": transaction_id,
                    "account_id": account_id,
                    "missing_id": missing_id,
                },
            )
        assert error.value.orig.pgcode == "23503"  # FK violation

    def test_rejects_unknown_entry_type(self, db_connection):
        """P1-D/COD-06: natureza fora da lookup dispara violação de FK (23503)."""
        account_id = create_account(db_connection)
        _set_balance(db_connection, account_id, 1)
        transaction_id = create_transaction(db_connection)
        missing_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM entry_type")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO transaction_entry (
                        entry_key, transaction_id, account_id, direction_id,
                        entry_type_id, amount_cents, balance_after_cents, created_at
                    )
                    VALUES (
                        :entry_key, :transaction_id, :account_id,
                        (SELECT id FROM transaction_direction WHERE enumerator = 'CREDIT'),
                        :missing_id, 1, 1, NOW()
                    )
                """),
                {
                    "entry_key": str(uuid4()),
                    "transaction_id": transaction_id,
                    "account_id": account_id,
                    "missing_id": missing_id,
                },
            )
        assert error.value.orig.pgcode == "23503"  # FK violation


def _set_balance(connection, account_id, balance_cents):
    """Prepara um saldo coerente para o cenário de lançamento."""
    connection.execute(
        text("UPDATE account SET balance_cents = :balance WHERE id = :id"),
        {"balance": balance_cents, "id": account_id},
    )
