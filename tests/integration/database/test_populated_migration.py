"""Migração em banco POPULADO (P1-D/COD-05/COD-06) — requisito crítico.

Não basta alterar database/database.sql e passar num banco vazio. Este teste
monta o schema LEGADO (pré-P1-D) num banco EFÊMERO DEDICADO, popula com
registros representativos (PF/PJ, contas, saldos, históricos, depósitos,
transferências, lançamentos, chaves de idempotência), aplica a migração
versionada `database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql` e
compara os dados ANTES e DEPOIS: contagem e identidade dos registros, valores
monetários, hashes e relacionamentos.

Isolamento físico: o banco efêmero é criado no MESMO cluster descartável
apontado por TEST_DATABASE_URL (cujo nome termina em `_test`), com um nome
derivado e único. Nunca toca o cluster da API (DATABASE_URL). A criação/queda
do banco e o reset são operações de limpeza legítimas, como o DROP SCHEMA já
sancionado em tests/utils/db_utils.py.
"""

from os import environ
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, make_url, text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEGACY_SCHEMA = (
    Path(__file__).resolve().parent / "legacy_schema.sql"
).read_text()
MIGRATION_SQL = (
    PROJECT_ROOT
    / "database"
    / "migrations"
    / "0001_cod05_cod06_lookup_and_entry_key.sql"
).read_text()

# Valores monetários representativos (centavos inteiros) para comparação exata.
PF_DEPOSIT = 100_000
PF_TRANSFER_PRINCIPAL = 40_000
PF_TRANSFER_FEE = 200  # 0,50% de 40000 = 200 (dentro de [50, 1000]).
PJ_DEPOSIT = 500_000


def _admin_url() -> str:
    """URL de um banco administrativo no cluster descartável `_test`."""
    raw = environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.skip("TEST_DATABASE_URL não definido; migração populada não pode rodar.")
    url = make_url(raw)
    if not url.database or not url.database.endswith("_test"):
        pytest.fail("TEST_DATABASE_URL deve apontar para um cluster `_test`.")
    return raw


@pytest.fixture
def ephemeral_database():
    """Cria e destrói um banco efêmero dedicado no cluster `_test`."""
    admin_raw = _admin_url()
    admin_url = make_url(admin_raw)
    ephemeral_name = f"{admin_url.database}_mig_{uuid4().hex[:12]}"
    ephemeral_url = admin_url.set(database=ephemeral_name)

    admin_engine = create_engine(admin_raw, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{ephemeral_name}"')
    except Exception:  # noqa: BLE001 — ambiente sem banco: pula de forma honesta.
        admin_engine.dispose()
        pytest.skip(
            "Não foi possível criar o banco efêmero (cluster de teste indisponível)."
        )

    engine = create_engine(str(ephemeral_url))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %(name)s AND pid <> pg_backend_pid()",
                {"name": ephemeral_name},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{ephemeral_name}"')
        admin_engine.dispose()


def _install_legacy_and_seed(engine):
    """Instala o schema legado e popula dados representativos."""
    with engine.begin() as connection:
        connection.exec_driver_sql(LEGACY_SCHEMA)

    data = {}
    with engine.begin() as connection:
        # --- Cliente PF ACTIVE com conta e histórico ---
        pf_key = uuid4()
        pf_id = connection.execute(
            text("""
                INSERT INTO client (client_key, client_type, email, timezone,
                    status_id, created_at, updated_at)
                VALUES (:k, 'INDIVIDUAL', :email, 'America/Sao_Paulo',
                    (SELECT id FROM client_status WHERE enumerator='ACTIVE'),
                    NOW(), NOW())
                RETURNING id
            """),
            {"k": pf_key, "email": f"pf-{pf_key}@example.test"},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO individual_client (client_id, cpf, full_name, birth_date)
                VALUES (:cid, '52998224725', 'Pessoa Fisica Teste', '1990-01-01')
            """),
            {"cid": pf_id},
        )
        connection.execute(
            text("""
                INSERT INTO client_status_event (client_id, from_status_id,
                    to_status_id, actor_type, reason, created_at)
                VALUES
                (:cid, NULL,
                 (SELECT id FROM client_status WHERE enumerator='PENDING'),
                 'SYSTEM', NULL, NOW()),
                (:cid, (SELECT id FROM client_status WHERE enumerator='PENDING'),
                 (SELECT id FROM client_status WHERE enumerator='ACTIVE'),
                 'INTERNAL', 'aprovado', NOW())
            """),
            {"cid": pf_id},
        )

        # --- Cliente PJ ACTIVE com conta ---
        pj_key = uuid4()
        pj_id = connection.execute(
            text("""
                INSERT INTO client (client_key, client_type, email, timezone,
                    status_id, created_at, updated_at)
                VALUES (:k, 'COMPANY', :email, 'America/Sao_Paulo',
                    (SELECT id FROM client_status WHERE enumerator='ACTIVE'),
                    NOW(), NOW())
                RETURNING id
            """),
            {"k": pj_key, "email": f"pj-{pj_key}@example.test"},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO company_client (client_id, cnpj, legal_name, trade_name)
                VALUES (:cid, '11222333000181', 'Empresa Teste Ltda', NULL)
            """),
            {"cid": pj_id},
        )
        connection.execute(
            text("""
                INSERT INTO client_status_event (client_id, from_status_id,
                    to_status_id, actor_type, reason, created_at)
                VALUES (:cid, NULL,
                 (SELECT id FROM client_status WHERE enumerator='PENDING'),
                 'SYSTEM', NULL, NOW())
            """),
            {"cid": pj_id},
        )

        # --- Contas (PF e PJ), saldo final após as operações abaixo ---
        pf_account_key = uuid4()
        pf_balance = PF_DEPOSIT - PF_TRANSFER_PRINCIPAL - PF_TRANSFER_FEE
        pf_account_id = connection.execute(
            text("""
                INSERT INTO account (account_key, client_id, status_id,
                    balance_cents, created_at, updated_at)
                VALUES (:k, :cid,
                    (SELECT id FROM account_status WHERE enumerator='ACTIVE'),
                    :bal, NOW(), NOW())
                RETURNING id
            """),
            {"k": pf_account_key, "cid": pf_id, "bal": pf_balance},
        ).scalar_one()

        pj_account_key = uuid4()
        pj_balance = PJ_DEPOSIT + PF_TRANSFER_PRINCIPAL
        pj_account_id = connection.execute(
            text("""
                INSERT INTO account (account_key, client_id, status_id,
                    balance_cents, created_at, updated_at)
                VALUES (:k, :cid,
                    (SELECT id FROM account_status WHERE enumerator='ACTIVE'),
                    :bal, NOW(), NOW())
                RETURNING id
            """),
            {"k": pj_account_key, "cid": pj_id, "bal": pj_balance},
        ).scalar_one()

        for account_id in (pf_account_id, pj_account_id):
            connection.execute(
                text("""
                    INSERT INTO account_status_event (account_id, from_status_id,
                        to_status_id, actor_type, reason, created_at)
                    VALUES (:aid, NULL,
                     (SELECT id FROM account_status WHERE enumerator='ACTIVE'),
                     'SYSTEM', NULL, NOW())
                """),
                {"aid": account_id},
            )

        # --- Depósito PF (idempotência + lançamento principal) ---
        pf_deposit_key = uuid4()
        pf_deposit_rck = uuid4()
        pf_deposit_hash = "a" * 64
        pf_deposit_txn = connection.execute(
            text("""
                INSERT INTO financial_transaction (transaction_key,
                    request_control_key, request_hash, transaction_type, created_at)
                VALUES (:k, :rck, :h, 'DEPOSIT', NOW())
                RETURNING id
            """),
            {"k": pf_deposit_key, "rck": pf_deposit_rck, "h": pf_deposit_hash},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO transaction_entry (transaction_id, account_id,
                    direction, entry_type, amount_cents, balance_after_cents, created_at)
                VALUES (:tid, :aid, 'CREDIT', 'PRINCIPAL', :amt, :amt, NOW())
            """),
            {"tid": pf_deposit_txn, "aid": pf_account_id, "amt": PF_DEPOSIT},
        )

        # --- Depósito PJ ---
        pj_deposit_key = uuid4()
        pj_deposit_rck = uuid4()
        pj_deposit_hash = "b" * 64
        pj_deposit_txn = connection.execute(
            text("""
                INSERT INTO financial_transaction (transaction_key,
                    request_control_key, request_hash, transaction_type, created_at)
                VALUES (:k, :rck, :h, 'DEPOSIT', NOW())
                RETURNING id
            """),
            {"k": pj_deposit_key, "rck": pj_deposit_rck, "h": pj_deposit_hash},
        ).scalar_one()
        connection.execute(
            text("""
                INSERT INTO transaction_entry (transaction_id, account_id,
                    direction, entry_type, amount_cents, balance_after_cents, created_at)
                VALUES (:tid, :aid, 'CREDIT', 'PRINCIPAL', :amt, :amt, NOW())
            """),
            {"tid": pj_deposit_txn, "aid": pj_account_id, "amt": PJ_DEPOSIT},
        )

        # --- Transferência PF -> PJ (principal + tarifa na origem, crédito no destino) ---
        transfer_key = uuid4()
        transfer_rck = uuid4()
        transfer_hash = "c" * 64
        transfer_txn = connection.execute(
            text("""
                INSERT INTO financial_transaction (transaction_key,
                    request_control_key, request_hash, transaction_type, created_at)
                VALUES (:k, :rck, :h, 'TRANSFER', NOW())
                RETURNING id
            """),
            {"k": transfer_key, "rck": transfer_rck, "h": transfer_hash},
        ).scalar_one()
        after_principal = PF_DEPOSIT - PF_TRANSFER_PRINCIPAL
        after_fee = after_principal - PF_TRANSFER_FEE
        connection.execute(
            text("""
                INSERT INTO transaction_entry (transaction_id, account_id,
                    direction, entry_type, amount_cents, balance_after_cents, created_at)
                VALUES
                (:tid, :src, 'DEBIT', 'PRINCIPAL', :principal, :after_principal, NOW()),
                (:tid, :src, 'DEBIT', 'FEE', :fee, :after_fee, NOW()),
                (:tid, :dst, 'CREDIT', 'PRINCIPAL', :principal, :dst_after, NOW())
            """),
            {
                "tid": transfer_txn,
                "src": pf_account_id,
                "dst": pj_account_id,
                "principal": PF_TRANSFER_PRINCIPAL,
                "fee": PF_TRANSFER_FEE,
                "after_principal": after_principal,
                "after_fee": after_fee,
                "dst_after": PJ_DEPOSIT + PF_TRANSFER_PRINCIPAL,
            },
        )

        data.update(
            pf_balance=pf_balance,
            pj_balance=pj_balance,
            pf_deposit_hash=pf_deposit_hash,
            pj_deposit_hash=pj_deposit_hash,
            transfer_hash=transfer_hash,
            pf_deposit_rck=str(pf_deposit_rck),
            transfer_rck=str(transfer_rck),
        )
    return data


def _snapshot(engine):
    """Captura um retrato dos dados de negócio comparável antes/depois."""
    with engine.connect() as connection:
        counts = {
            table: connection.execute(
                text(f"SELECT count(*) FROM {table}")  # noqa: S608 (nome fixo)
            ).scalar_one()
            for table in (
                "client", "individual_client", "company_client",
                "client_status_event", "account", "account_status_event",
                "financial_transaction", "transaction_entry",
            )
        }
        # Tipos de cliente por client_key (identidade + texto do tipo).
        client_types = dict(
            connection.execute(
                text("""
                    SELECT c.client_key::text, ct.enumerator
                    FROM client c
                    JOIN client_type ct ON ct.id = c.client_type_id
                    ORDER BY c.id
                """) if _has_lookup(connection) else text("""
                    SELECT client_key::text, client_type FROM client ORDER BY id
                """)
            ).all()
        )
        # Saldos por account_key.
        balances = dict(
            connection.execute(
                text("SELECT account_key::text, balance_cents FROM account ORDER BY id")
            ).all()
        )
        # Hashes e tipos de transação por transaction_key.
        if _has_lookup(connection):
            txns = {
                row[0]: (row[1], row[2])
                for row in connection.execute(
                    text("""
                        SELECT f.transaction_key::text, f.request_hash, tt.enumerator
                        FROM financial_transaction f
                        JOIN transaction_type tt ON tt.id = f.transaction_type_id
                        ORDER BY f.id
                    """)
                ).all()
            }
        else:
            txns = {
                row[0]: (row[1], row[2])
                for row in connection.execute(
                    text("""
                        SELECT transaction_key::text, request_hash, transaction_type
                        FROM financial_transaction ORDER BY id
                    """)
                ).all()
            }
        # Lançamentos por (transaction_key, direction, entry_type, amount, balance_after).
        if _has_lookup(connection):
            entries = connection.execute(
                text("""
                    SELECT f.transaction_key::text, d.enumerator, et.enumerator,
                           e.amount_cents, e.balance_after_cents, a.account_key::text
                    FROM transaction_entry e
                    JOIN financial_transaction f ON f.id = e.transaction_id
                    JOIN transaction_direction d ON d.id = e.direction_id
                    JOIN entry_type et ON et.id = e.entry_type_id
                    JOIN account a ON a.id = e.account_id
                    ORDER BY e.id
                """)
            ).all()
        else:
            entries = connection.execute(
                text("""
                    SELECT f.transaction_key::text, e.direction, e.entry_type,
                           e.amount_cents, e.balance_after_cents, a.account_key::text
                    FROM transaction_entry e
                    JOIN financial_transaction f ON f.id = e.transaction_id
                    JOIN account a ON a.id = e.account_id
                    ORDER BY e.id
                """)
            ).all()
    return {
        "counts": counts,
        "client_types": client_types,
        "balances": balances,
        "txns": txns,
        "entries": [tuple(row) for row in entries],
    }


def _has_lookup(connection) -> bool:
    """Detecta se o schema já está migrado (coluna client_type_id existe)."""
    return connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='client'
                  AND column_name='client_type_id'
            )
        """)
    ).scalar_one()


def _run_migration(engine):
    """Aplica a migração versionada exatamente como o `psql -f` faria.

    O script gerencia sua própria transação (BEGIN; ... COMMIT;), então a
    conexão roda em AUTOCOMMIT para não aninhar transações. Qualquer
    RAISE EXCEPTION interna aborta o COMMIT e propaga o erro.
    """
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    with autocommit_engine.connect() as connection:
        connection.exec_driver_sql(MIGRATION_SQL)


class TestPopulatedMigration:
    """A migração evolui um banco populado sem perder dados nem identidade."""

    def test_migration_preserves_data_and_normalizes_schema(self, ephemeral_database):
        """Antes/depois: contagem, identidade, dinheiro, hashes e relações batem."""
        seed = _install_legacy_and_seed(ephemeral_database)
        before = _snapshot(ephemeral_database)

        _run_migration(ephemeral_database)
        after = _snapshot(ephemeral_database)

        # 1. Contagem de registros preservada em toda tabela de negócio.
        assert after["counts"] == before["counts"]

        # 2. Identidade e tipo textual dos clientes preservados.
        assert after["client_types"] == before["client_types"]

        # 3. Valores monetários (saldos) idênticos.
        assert after["balances"] == before["balances"]

        # 4. Hashes e tipos de transação idênticos.
        assert after["txns"] == before["txns"]

        # 5. Lançamentos (direção, natureza, valor, saldo, conta) idênticos.
        assert after["entries"] == before["entries"]

        # 6. O schema ficou normalizado: as lookups existem e as colunas
        #    textuais antigas sumiram.
        with ephemeral_database.connect() as connection:
            assert _has_lookup(connection) is True
            legacy_columns = connection.execute(
                text("""
                    SELECT count(*) FROM information_schema.columns
                    WHERE table_schema='public' AND (
                        (table_name='client' AND column_name='client_type') OR
                        (table_name='financial_transaction' AND column_name='transaction_type') OR
                        (table_name='transaction_entry' AND column_name IN ('direction','entry_type')) OR
                        (table_name IN ('client_status_event','account_status_event')
                         AND column_name='actor_type')
                    )
                """)
            ).scalar_one()
            assert legacy_columns == 0

            # 7. entry_key foi criado, é total e único (COD-05).
            total, distinct, nulls = connection.execute(
                text("""
                    SELECT count(*), count(DISTINCT entry_key),
                           count(*) FILTER (WHERE entry_key IS NULL)
                    FROM transaction_entry
                """)
            ).one()
            assert nulls == 0
            assert total == distinct == before["counts"]["transaction_entry"]

    def test_migration_is_idempotent(self, ephemeral_database):
        """Reexecutar a migração não duplica lookups nem altera os dados."""
        _install_legacy_and_seed(ephemeral_database)
        _run_migration(ephemeral_database)
        first = _snapshot(ephemeral_database)

        # Segunda aplicação: deve ser um no-op seguro.
        _run_migration(ephemeral_database)
        second = _snapshot(ephemeral_database)

        assert second == first
        with ephemeral_database.connect() as connection:
            for table in (
                "client_type", "transaction_type", "transaction_direction",
                "entry_type", "actor_type",
            ):
                total, distinct = connection.execute(
                    text(
                        f"SELECT count(*), count(DISTINCT enumerator) FROM {table}"  # noqa: S608
                    )
                ).one()
                assert total == distinct, f"lookup {table} duplicou valores"
