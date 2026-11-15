"""Consistência das tabelas de lookup normalizadas (P1-D/COD-06).

Verifica que o bootstrap limpo (`database/database.sql`) instala as cinco
lookups novas no padrão aprovado (id BIGINT PK, enumerator UNIQUE), com os
valores de referência determinísticos e sem duplicatas, e que as colunas FK
das tabelas de domínio referenciam essas lookups com ON DELETE RESTRICT.
"""

import pytest
from sqlalchemy import text

from tests.integration.database.assertions import (
    assert_columns_and_primary_key,
    assert_unique,
)


LOOKUPS = {
    "client_type": ({"INDIVIDUAL", "COMPANY"}, 20),
    "transaction_type": ({"DEPOSIT", "TRANSFER"}, 20),
    "transaction_direction": ({"DEBIT", "CREDIT"}, 10),
    "entry_type": ({"PRINCIPAL", "FEE"}, 20),
    "actor_type": ({"SYSTEM", "INTERNAL"}, 20),
}


class TestLookupTableContracts:
    """Cada lookup segue o mesmo contrato físico de client_status/account_status."""

    @pytest.mark.parametrize("table_name", sorted(LOOKUPS))
    def test_columns_and_primary_key(self, schema_engine, table_name):
        """Lookup tem id BIGINT PK e enumerator VARCHAR NOT NULL."""
        _, max_length = LOOKUPS[table_name]
        assert_columns_and_primary_key(
            schema_engine,
            table_name,
            {
                "id": ("bigint", None, "NO"),
                "enumerator": ("character varying", max_length, "NO"),
            },
            ["id"],
        )

    @pytest.mark.parametrize("table_name", sorted(LOOKUPS))
    def test_enumerator_is_unique(self, schema_engine, table_name):
        """O enumerator de cada lookup é único (impede valores duplicados)."""
        assert_unique(schema_engine, table_name, "enumerator")

    @pytest.mark.parametrize("table_name", sorted(LOOKUPS))
    def test_deterministic_reference_values(self, schema_engine, table_name):
        """O seed instala exatamente os valores de referência do domínio."""
        expected_values, _ = LOOKUPS[table_name]
        with schema_engine.connect() as connection:
            values = connection.execute(
                text(f"SELECT enumerator FROM {table_name}")  # noqa: S608 (nome fixo)
            ).scalars().all()
        assert set(values) == expected_values
        # Sem duplicatas: contagem total == contagem distinta.
        assert len(values) == len(set(values))


class TestLookupForeignKeys:
    """As colunas FK de domínio referenciam as lookups com RESTRICT."""

    def test_domain_tables_point_to_lookups(self, schema_engine):
        """Toda FK *_id de enum aponta para a lookup correta sem cascata."""
        from sqlalchemy import inspect

        inspector = inspect(schema_engine)
        expected = {
            "client": {("client_type_id", "client_type")},
            "financial_transaction": {("transaction_type_id", "transaction_type")},
            "transaction_entry": {
                ("direction_id", "transaction_direction"),
                ("entry_type_id", "entry_type"),
            },
            "client_status_event": {("actor_type_id", "actor_type")},
            "account_status_event": {("actor_type_id", "actor_type")},
        }
        for table_name, wanted in expected.items():
            fks = inspector.get_foreign_keys(table_name, schema="public")
            found = {
                (fk["constrained_columns"][0], fk["referred_table"])
                for fk in fks
            }
            restrict = {
                (fk["constrained_columns"][0], fk["referred_table"])
                for fk in fks
                if fk.get("options", {}).get("ondelete") == "RESTRICT"
            }
            assert wanted <= found, f"{table_name}: FK ausente {wanted - found}"
            assert wanted <= restrict, f"{table_name}: FK sem ON DELETE RESTRICT"
