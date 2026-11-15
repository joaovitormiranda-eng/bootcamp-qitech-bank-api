"""Contrato físico de ACCOUNT, status e histórico."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.database.assertions import (
    assert_columns_and_primary_key,
    assert_foreign_keys,
    assert_index,
    assert_unique,
)
from tests.integration.database.builders import create_account, create_client


class TestAccountStatusSchema:
    """Domínio fechado de status disponível para contas."""

    def test_expected_seeds(self, schema_engine):
        """O bootstrap oferece exatamente ACTIVE, INACTIVE e CLOSED."""
        with schema_engine.connect() as connection:
            statuses = connection.execute(
                text("SELECT enumerator FROM account_status")
            ).scalars().all()
        assert set(statuses) == {"ACTIVE", "INACTIVE", "CLOSED"}

    def test_columns_and_primary_key(self, schema_engine):
        """A tabela de domínio tem ID BIGINT e enumerador único obrigatório."""
        assert_columns_and_primary_key(
            schema_engine,
            "account_status",
            {"id": ("bigint", None, "NO"), "enumerator": ("character varying", 20, "NO")},
            ["id"],
        )
        assert_unique(schema_engine, "account_status", "enumerator")

    def test_rejects_unknown_status(self, db_connection):
        """O CHECK impede a persistência de um status de conta inventado."""
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("INSERT INTO account_status (enumerator) VALUES ('UNKNOWN')")
            )
        assert error.value.orig.pgcode == "23514"


class TestAccountSchema:
    """Uma conta por cliente, com status atual e saldo não negativo."""

    def test_columns_and_primary_key(self, schema_engine):
        """A estrutura exige UUID, saldo BIGINT e timestamps com fuso."""
        assert_columns_and_primary_key(
            schema_engine,
            "account",
            {
                "id": ("bigint", None, "NO"),
                "account_key": ("uuid", None, "NO"),
                "client_id": ("bigint", None, "NO"),
                "status_id": ("bigint", None, "NO"),
                "balance_cents": ("bigint", None, "NO"),
                "created_at": ("timestamp with time zone", None, "NO"),
                "updated_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_foreign_keys_are_restricted(self, schema_engine):
        """Cliente e status são referências obrigatórias sem exclusão em cascata."""
        assert_foreign_keys(
            schema_engine,
            "account",
            {
                ("client_id", "client", "id", "RESTRICT"),
                ("status_id", "account_status", "id", "RESTRICT"),
            },
        )

    @pytest.mark.parametrize("column_name", ["account_key", "client_id"])
    def test_business_key_is_unique(self, schema_engine, column_name):
        """A chave pública e o cliente têm restrições UNIQUE independentes."""
        assert_unique(schema_engine, "account", column_name)

    def test_status_index(self, schema_engine):
        """A busca por status de conta tem o índice aprovado no ERD."""
        assert_index(schema_engine, "account", "idx_account_status", ["status_id"])

    def test_balance_starts_at_zero(self, db_connection):
        """Uma conta nova recebe saldo zero quando o INSERT o omite."""
        account_id = create_account(db_connection)
        balance = db_connection.execute(
            text("SELECT balance_cents FROM account WHERE id = :id"), {"id": account_id}
        ).scalar_one()
        assert balance == 0

    def test_rejects_negative_balance(self, db_connection):
        """O CHECK impede atualização do saldo para valor negativo."""
        account_id = create_account(db_connection)
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("UPDATE account SET balance_cents = -1 WHERE id = :id"),
                {"id": account_id},
            )
        assert error.value.orig.pgcode == "23514"

    def test_client_cannot_have_second_account(self, db_connection):
        """UNIQUE(client_id) impõe no máximo uma conta por cliente."""
        client_id = create_client(db_connection)
        create_account(db_connection, client_id=client_id)
        with pytest.raises(IntegrityError) as error:
            create_account(db_connection, client_id=client_id)
        assert error.value.orig.pgcode == "23505"  # UNIQUE violation


class TestAccountStatusEventSchema:
    """Histórico auditável das mudanças de status de conta."""

    def test_columns_and_primary_key(self, schema_engine):
        """Evento inicial permite origem nula; destino e ator são obrigatórios.

        P1-D/COD-06: o ator é normalizado como FK `actor_type_id`.
        """
        assert_columns_and_primary_key(
            schema_engine,
            "account_status_event",
            {
                "id": ("bigint", None, "NO"),
                "account_id": ("bigint", None, "NO"),
                "from_status_id": ("bigint", None, "YES"),
                "to_status_id": ("bigint", None, "NO"),
                "actor_type_id": ("bigint", None, "NO"),
                "reason": ("character varying", 500, "YES"),
                "created_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_foreign_keys_are_restricted(self, schema_engine):
        """Conta, status e ator referenciados não são apagados em cascata."""
        assert_foreign_keys(
            schema_engine,
            "account_status_event",
            {
                ("account_id", "account", "id", "RESTRICT"),
                ("from_status_id", "account_status", "id", "RESTRICT"),
                ("to_status_id", "account_status", "id", "RESTRICT"),
                ("actor_type_id", "actor_type", "id", "RESTRICT"),
            },
        )

    def test_history_index(self, schema_engine):
        """O índice apoia a leitura cronológica do histórico por conta."""
        assert_index(
            schema_engine,
            "account_status_event",
            "idx_account_status_event_history",
            ["account_id", "created_at", "id"],
        )

    def test_accepts_initial_system_event(self, db_connection):
        """SYSTEM registra o primeiro status sem status anterior."""
        account_id = create_account(db_connection)
        event_id = _insert_account_event(db_connection, account_id, actor_type="SYSTEM")
        assert event_id > 0

    def test_accepts_internal_actor(self, db_connection):
        """INTERNAL pode registrar uma transição com origem e destino."""
        account_id = create_account(db_connection)
        event_id = _insert_account_event(
            db_connection,
            account_id,
            actor_type="INTERNAL",
            from_status="ACTIVE",
            to_status="INACTIVE",
        )
        assert event_id > 0

    def test_rejects_unknown_actor(self, db_connection):
        """Atores fora da lookup não entram no histórico (FK, não CHECK).

        P1-D/COD-06: `actor_type_id` inexistente dispara violação de FK (23503).
        """
        account_id = create_account(db_connection)
        missing_actor_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM actor_type")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO account_status_event (
                        account_id, from_status_id, to_status_id,
                        actor_type_id, created_at
                    )
                    VALUES (
                        :account_id, NULL,
                        (SELECT id FROM account_status WHERE enumerator = 'ACTIVE'),
                        :actor_type_id, NOW()
                    )
                """),
                {"account_id": account_id, "actor_type_id": missing_actor_id},
            )
        assert error.value.orig.pgcode == "23503"  # FK violation


def _insert_account_event(connection, account_id, *, actor_type, from_status=None, to_status="ACTIVE"):
    """Insere um evento resolvendo status e ator para seus IDs de lookup."""
    return connection.execute(
        text("""
            INSERT INTO account_status_event (
                account_id, from_status_id, to_status_id, actor_type_id, created_at
            )
            VALUES (
                :account_id,
                (SELECT id FROM account_status WHERE enumerator = :from_status),
                (SELECT id FROM account_status WHERE enumerator = :to_status),
                (SELECT id FROM actor_type WHERE enumerator = :actor_type),
                NOW()
            )
            RETURNING id
        """),
        {
            "account_id": account_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_type": actor_type,
        },
    ).scalar_one()
