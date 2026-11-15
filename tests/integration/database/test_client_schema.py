"""Contrato físico de CLIENT, perfis PF/PJ e histórico de status."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.integration.database.assertions import (
    assert_columns_and_primary_key,
    assert_foreign_keys,
    assert_index,
    assert_unique,
)
from tests.integration.database.builders import create_client


class TestClientStatusSchema:
    """Domínio fechado de status disponível para o cadastro de clientes."""

    def test_expected_seeds(self, schema_engine):
        """O bootstrap oferece exatamente os quatro status aprovados."""
        with schema_engine.connect() as connection:
            statuses = connection.execute(
                text("SELECT enumerator FROM client_status")
            ).scalars().all()
        assert set(statuses) == {"PENDING", "ACTIVE", "REJECTED", "INACTIVE"}

    def test_columns_and_primary_key(self, schema_engine):
        """A tabela de domínio tem ID BIGINT e enumerador único obrigatório."""
        assert_columns_and_primary_key(
            schema_engine,
            "client_status",
            {"id": ("bigint", None, "NO"), "enumerator": ("character varying", 20, "NO")},
            ["id"],
        )
        assert_unique(schema_engine, "client_status", "enumerator")

    def test_rejects_unknown_status(self, db_connection):
        """O CHECK impede que um status fora do domínio seja persistido."""
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("INSERT INTO client_status (enumerator) VALUES ('UNKNOWN')")
            )
        assert error.value.orig.pgcode == "23514"


class TestClientSchema:
    """Identidade do cliente, tipo PF/PJ e vínculo com o status atual."""

    def test_columns_and_primary_key(self, schema_engine):
        """Tipos, nulidade e PK de client correspondem ao ERD v1.2.

        P1-D/COD-06: o tipo de cliente é normalizado como FK `client_type_id`
        para a lookup `client_type` (em vez de VARCHAR + CHECK).
        """
        assert_columns_and_primary_key(
            schema_engine,
            "client",
            {
                "id": ("bigint", None, "NO"),
                "client_key": ("uuid", None, "NO"),
                "client_type_id": ("bigint", None, "NO"),
                "email": ("character varying", 254, "NO"),
                "timezone": ("character varying", 64, "NO"),
                "status_id": ("bigint", None, "NO"),
                "created_at": ("timestamp with time zone", None, "NO"),
                "updated_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_foreign_keys_are_restricted(self, schema_engine):
        """status_id e client_type_id referenciam suas lookups sem cascata."""
        assert_foreign_keys(
            schema_engine,
            "client",
            {
                ("status_id", "client_status", "id", "RESTRICT"),
                ("client_type_id", "client_type", "id", "RESTRICT"),
            },
        )

    def test_client_type_index(self, schema_engine):
        """A busca por tipo de cliente tem o índice aprovado no ERD v1.2."""
        assert_index(schema_engine, "client", "idx_client_type", ["client_type_id"])

    @pytest.mark.parametrize("column_name", ["client_key", "email"])
    def test_business_key_is_unique(self, schema_engine, column_name):
        """client_key e email têm restrições UNIQUE independentes."""
        assert_unique(schema_engine, "client", column_name)

    def test_status_index(self, schema_engine):
        """A busca por status tem o índice aprovado no ERD."""
        assert_index(schema_engine, "client", "idx_client_status", ["status_id"])

    def test_rejects_unknown_client_type(self, db_connection):
        """Somente os tipos presentes na lookup são aceitos (FK, não CHECK).

        P1-D/COD-06: a integridade do tipo passa a ser referencial. Inserir um
        `client_type_id` inexistente dispara a violação de FK (23503).
        """
        from uuid import uuid4

        missing_type_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM client_type")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO client (
                        client_key, client_type_id, email, timezone, status_id,
                        created_at, updated_at
                    )
                    VALUES (
                        :client_key, :client_type_id, :email, 'America/Sao_Paulo',
                        (SELECT id FROM client_status WHERE enumerator = 'PENDING'),
                        NOW(), NOW()
                    )
                """),
                {
                    "client_key": str(uuid4()),
                    "client_type_id": missing_type_id,
                    "email": f"{uuid4()}@example.test",
                },
            )
        assert error.value.orig.pgcode == "23503"  # FK violation

    def test_email_cannot_be_reused(self, db_connection):
        """Dois clientes diferentes não podem compartilhar o mesmo e-mail."""
        email = "shared@example.test"
        create_client(db_connection, email=email)
        with pytest.raises(IntegrityError) as error:
            create_client(db_connection, email=email)
        assert error.value.orig.pgcode == "23505"


class TestIndividualClientSchema:
    """Perfil PF dependente de client, identificado por CPF único."""

    def test_columns_and_primary_key(self, schema_engine):
        """client_id é simultaneamente PK e identificador do perfil PF."""
        assert_columns_and_primary_key(
            schema_engine,
            "individual_client",
            {
                "client_id": ("bigint", None, "NO"),
                "cpf": ("character varying", 11, "NO"),
                "full_name": ("character varying", 200, "NO"),
                "birth_date": ("date", None, "NO"),
            },
            ["client_id"],
        )

    def test_client_foreign_key_is_restricted(self, schema_engine):
        """O perfil PF depende de um cliente e impede exclusão em cascata."""
        assert_foreign_keys(
            schema_engine,
            "individual_client",
            {("client_id", "client", "id", "RESTRICT")},
        )

    def test_cpf_is_unique(self, schema_engine):
        """O catálogo declara CPF único em individual_client."""
        assert_unique(schema_engine, "individual_client", "cpf")

    def test_cpf_cannot_be_reused(self, db_connection):
        """A constraint rejeita o mesmo CPF em dois perfis PF."""
        first_client_id = create_client(db_connection)
        second_client_id = create_client(db_connection)
        insert = text("""
            INSERT INTO individual_client (client_id, cpf, full_name, birth_date)
            VALUES (:client_id, '52998224725', 'Pessoa Teste', '1990-01-01')
        """)
        db_connection.execute(insert, {"client_id": first_client_id})
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(insert, {"client_id": second_client_id})
        assert error.value.orig.pgcode == "23505"


class TestCompanyClientSchema:
    """Perfil PJ dependente de client, identificado por CNPJ único."""

    def test_columns_and_primary_key(self, schema_engine):
        """O perfil PJ exige razão social e permite nome fantasia ausente."""
        assert_columns_and_primary_key(
            schema_engine,
            "company_client",
            {
                "client_id": ("bigint", None, "NO"),
                "cnpj": ("character varying", 14, "NO"),
                "legal_name": ("character varying", 200, "NO"),
                "trade_name": ("character varying", 200, "YES"),
            },
            ["client_id"],
        )

    def test_client_foreign_key_is_restricted(self, schema_engine):
        """O perfil PJ depende de um cliente e impede exclusão em cascata."""
        assert_foreign_keys(
            schema_engine,
            "company_client",
            {("client_id", "client", "id", "RESTRICT")},
        )

    def test_cnpj_is_unique(self, schema_engine):
        """O catálogo declara CNPJ único em company_client."""
        assert_unique(schema_engine, "company_client", "cnpj")

    def test_cnpj_cannot_be_reused(self, db_connection):
        """A constraint rejeita o mesmo CNPJ em dois perfis PJ."""
        first_client_id = create_client(db_connection, client_type="COMPANY")
        second_client_id = create_client(db_connection, client_type="COMPANY")
        insert = text("""
            INSERT INTO company_client (client_id, cnpj, legal_name)
            VALUES (:client_id, '12345678901234', 'Empresa Teste')
        """)
        db_connection.execute(insert, {"client_id": first_client_id})
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(insert, {"client_id": second_client_id})
        assert error.value.orig.pgcode == "23505"

    def test_trade_name_can_be_null(self, db_connection):
        """Uma empresa pode nascer sem nome fantasia, conforme o ERD."""
        client_id = create_client(db_connection, client_type="COMPANY", status="PENDING")
        trade_name = db_connection.execute(
            text("""
                INSERT INTO company_client (client_id, cnpj, legal_name, trade_name)
                VALUES (:client_id, '12345678901234', 'Empresa Teste', NULL)
                RETURNING trade_name
            """),
            {"client_id": client_id},
        ).scalar_one()
        assert trade_name is None


class TestClientStatusEventSchema:
    """Histórico auditável das mudanças de status de cliente."""

    def test_columns_and_primary_key(self, schema_engine):
        """Evento inicial permite origem nula; destino e ator são obrigatórios.

        P1-D/COD-06: o ator é normalizado como FK `actor_type_id`.
        """
        assert_columns_and_primary_key(
            schema_engine,
            "client_status_event",
            {
                "id": ("bigint", None, "NO"),
                "client_id": ("bigint", None, "NO"),
                "from_status_id": ("bigint", None, "YES"),
                "to_status_id": ("bigint", None, "NO"),
                "actor_type_id": ("bigint", None, "NO"),
                "reason": ("character varying", 500, "YES"),
                "created_at": ("timestamp with time zone", None, "NO"),
            },
            ["id"],
        )

    def test_foreign_keys_are_restricted(self, schema_engine):
        """Cliente, status e ator referenciados não são apagados em cascata."""
        assert_foreign_keys(
            schema_engine,
            "client_status_event",
            {
                ("client_id", "client", "id", "RESTRICT"),
                ("from_status_id", "client_status", "id", "RESTRICT"),
                ("to_status_id", "client_status", "id", "RESTRICT"),
                ("actor_type_id", "actor_type", "id", "RESTRICT"),
            },
        )

    def test_history_index(self, schema_engine):
        """O índice ordena consultas do histórico por cliente e momento."""
        assert_index(
            schema_engine,
            "client_status_event",
            "idx_client_status_event_history",
            ["client_id", "created_at", "id"],
        )

    def test_accepts_initial_system_event(self, db_connection):
        """SYSTEM registra o primeiro status sem status anterior."""
        client_id = create_client(db_connection, status="PENDING")
        event_id = _insert_client_event(db_connection, client_id, actor_type="SYSTEM")
        assert event_id > 0

    def test_accepts_internal_actor(self, db_connection):
        """INTERNAL pode registrar uma transição com origem e destino."""
        client_id = create_client(db_connection, status="ACTIVE")
        event_id = _insert_client_event(
            db_connection, client_id, actor_type="INTERNAL", from_status="PENDING", to_status="ACTIVE"
        )
        assert event_id > 0

    def test_rejects_unknown_actor(self, db_connection):
        """Atores fora da lookup não entram no histórico (FK, não CHECK).

        P1-D/COD-06: `actor_type_id` inexistente dispara violação de FK (23503).
        """
        client_id = create_client(db_connection, status="PENDING")
        missing_actor_id = db_connection.execute(
            text("SELECT COALESCE(MAX(id), 0) + 999 FROM actor_type")
        ).scalar_one()
        with pytest.raises(IntegrityError) as error:
            db_connection.execute(
                text("""
                    INSERT INTO client_status_event (
                        client_id, from_status_id, to_status_id,
                        actor_type_id, created_at
                    )
                    VALUES (
                        :client_id, NULL,
                        (SELECT id FROM client_status WHERE enumerator = 'PENDING'),
                        :actor_type_id, NOW()
                    )
                """),
                {"client_id": client_id, "actor_type_id": missing_actor_id},
            )
        assert error.value.orig.pgcode == "23503"  # FK violation


class TestClientTypeLookupSchema:
    """Tabela de lookup do tipo de cliente (P1-D/COD-06)."""

    def test_expected_seeds(self, schema_engine):
        """O bootstrap oferece exatamente INDIVIDUAL e COMPANY."""
        with schema_engine.connect() as connection:
            values = connection.execute(
                text("SELECT enumerator FROM client_type")
            ).scalars().all()
        assert set(values) == {"INDIVIDUAL", "COMPANY"}

    def test_columns_and_primary_key(self, schema_engine):
        """A lookup tem ID BIGINT e enumerador único obrigatório."""
        assert_columns_and_primary_key(
            schema_engine,
            "client_type",
            {"id": ("bigint", None, "NO"), "enumerator": ("character varying", 20, "NO")},
            ["id"],
        )
        assert_unique(schema_engine, "client_type", "enumerator")


def _insert_client_event(connection, client_id, *, actor_type, from_status=None, to_status="PENDING"):
    """Insere um evento resolvendo status e ator para seus IDs de lookup."""
    return connection.execute(
        text("""
            INSERT INTO client_status_event (
                client_id, from_status_id, to_status_id, actor_type_id, created_at
            )
            VALUES (
                :client_id,
                (SELECT id FROM client_status WHERE enumerator = :from_status),
                (SELECT id FROM client_status WHERE enumerator = :to_status),
                (SELECT id FROM actor_type WHERE enumerator = :actor_type),
                NOW()
            )
            RETURNING id
        """),
        {
            "client_id": client_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_type": actor_type,
        },
    ).scalar_one()
