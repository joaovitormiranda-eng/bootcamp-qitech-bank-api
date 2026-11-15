-- =====================================================================
-- Migração P1-D — 0001_cod05_cod06_lookup_and_entry_key
-- ---------------------------------------------------------------------
-- Evolui um banco JÁ POPULADO do schema antigo (enums textuais com CHECK e
-- transaction_entry sem chave pública) para o schema alvo:
--   COD-06: tabelas de lookup (client_type, transaction_type,
--           transaction_direction, entry_type, actor_type) + FKs.
--   COD-05: transaction_entry.entry_key (UUID público, backfill determinístico).
--
-- Propriedades:
--   * Transação única + ON_ERROR_STOP → ROLLBACK total em qualquer erro.
--   * Idempotente: reexecutar não duplica lookups nem recria colunas.
--   * Backfill sem perda: o enumerator textual vira FK para o MESMO texto.
--   * Verificações de pré-condição e de integridade pós-migração (falham
--     explicitamente via RAISE EXCEPTION, nunca perda silenciosa).
--
-- PRÉ-REQUISITO OPERACIONAL: faça um pg_dump completo ANTES de aplicar isto
-- em qualquer ambiente não-efêmero (ver 0001_ROLLBACK.sql e o AUDIT §9).
--
-- Uso:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql
-- =====================================================================

BEGIN;

-- Requerido para gen_random_uuid() no backfill de entry_key.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- 0. Pré-condições
-- ---------------------------------------------------------------------
DO $$
BEGIN
    -- O banco precisa ter o schema de domínio instalado.
    IF to_regclass('public.client') IS NULL
       OR to_regclass('public.transaction_entry') IS NULL THEN
        RAISE EXCEPTION
            'Pré-condição falhou: tabelas de domínio ausentes; nada a migrar.';
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 1. Tabelas de lookup (idempotente: IF NOT EXISTS + seed ON CONFLICT)
--    Garante contra duplicação de valores quando a migração é repetida.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS client_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_client_type_enumerator
        CHECK (enumerator IN ('INDIVIDUAL', 'COMPANY'))
);
INSERT INTO client_type (enumerator) VALUES ('INDIVIDUAL'), ('COMPANY')
    ON CONFLICT (enumerator) DO NOTHING;

CREATE TABLE IF NOT EXISTS transaction_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_transaction_type_enumerator
        CHECK (enumerator IN ('DEPOSIT', 'TRANSFER'))
);
INSERT INTO transaction_type (enumerator) VALUES ('DEPOSIT'), ('TRANSFER')
    ON CONFLICT (enumerator) DO NOTHING;

CREATE TABLE IF NOT EXISTS transaction_direction (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(10) NOT NULL UNIQUE,
    CONSTRAINT ck_transaction_direction_enumerator
        CHECK (enumerator IN ('DEBIT', 'CREDIT'))
);
INSERT INTO transaction_direction (enumerator) VALUES ('DEBIT'), ('CREDIT')
    ON CONFLICT (enumerator) DO NOTHING;

CREATE TABLE IF NOT EXISTS entry_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_entry_type_enumerator
        CHECK (enumerator IN ('PRINCIPAL', 'FEE'))
);
INSERT INTO entry_type (enumerator) VALUES ('PRINCIPAL'), ('FEE')
    ON CONFLICT (enumerator) DO NOTHING;

CREATE TABLE IF NOT EXISTS actor_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_actor_type_enumerator
        CHECK (enumerator IN ('SYSTEM', 'INTERNAL'))
);
INSERT INTO actor_type (enumerator) VALUES ('SYSTEM'), ('INTERNAL')
    ON CONFLICT (enumerator) DO NOTHING;

-- ---------------------------------------------------------------------
-- 2. client.client_type  →  client.client_type_id (FK)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'client'
          AND column_name = 'client_type'
    ) THEN
        -- Pré-condição de backfill: todo texto existente tem lookup.
        IF EXISTS (
            SELECT 1 FROM client c
            LEFT JOIN client_type ct ON ct.enumerator = c.client_type
            WHERE ct.id IS NULL
        ) THEN
            RAISE EXCEPTION
                'Backfill client_type: valor textual sem lookup correspondente.';
        END IF;

        ALTER TABLE client ADD COLUMN client_type_id BIGINT;
        UPDATE client c
            SET client_type_id = ct.id
            FROM client_type ct
            WHERE ct.enumerator = c.client_type;

        IF EXISTS (SELECT 1 FROM client WHERE client_type_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill client_type incompleto: há NULL em client_type_id.';
        END IF;

        ALTER TABLE client ALTER COLUMN client_type_id SET NOT NULL;
        ALTER TABLE client
            ADD CONSTRAINT client_client_type_id_fkey
            FOREIGN KEY (client_type_id) REFERENCES client_type(id) ON DELETE RESTRICT;
        ALTER TABLE client DROP CONSTRAINT IF EXISTS ck_client_type;
        ALTER TABLE client DROP COLUMN client_type;
        CREATE INDEX IF NOT EXISTS idx_client_type ON client (client_type_id);
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 3. financial_transaction.transaction_type → transaction_type_id (FK)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'financial_transaction'
          AND column_name = 'transaction_type'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM financial_transaction f
            LEFT JOIN transaction_type tt ON tt.enumerator = f.transaction_type
            WHERE tt.id IS NULL
        ) THEN
            RAISE EXCEPTION
                'Backfill transaction_type: valor textual sem lookup correspondente.';
        END IF;

        ALTER TABLE financial_transaction ADD COLUMN transaction_type_id BIGINT;
        UPDATE financial_transaction f
            SET transaction_type_id = tt.id
            FROM transaction_type tt
            WHERE tt.enumerator = f.transaction_type;

        IF EXISTS (SELECT 1 FROM financial_transaction WHERE transaction_type_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill transaction_type incompleto.';
        END IF;

        ALTER TABLE financial_transaction ALTER COLUMN transaction_type_id SET NOT NULL;
        ALTER TABLE financial_transaction
            ADD CONSTRAINT financial_transaction_transaction_type_id_fkey
            FOREIGN KEY (transaction_type_id) REFERENCES transaction_type(id) ON DELETE RESTRICT;
        ALTER TABLE financial_transaction DROP CONSTRAINT IF EXISTS ck_financial_transaction_type;
        ALTER TABLE financial_transaction DROP COLUMN transaction_type;
        CREATE INDEX IF NOT EXISTS idx_financial_transaction_type
            ON financial_transaction (transaction_type_id);
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 4. transaction_entry.direction → direction_id, entry_type → entry_type_id,
--    + entry_key UUID (backfill determinístico por linha).
-- ---------------------------------------------------------------------
DO $$
BEGIN
    -- 4a. direction_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'transaction_entry'
          AND column_name = 'direction'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM transaction_entry e
            LEFT JOIN transaction_direction d ON d.enumerator = e.direction
            WHERE d.id IS NULL
        ) THEN
            RAISE EXCEPTION 'Backfill direction: valor textual sem lookup.';
        END IF;

        ALTER TABLE transaction_entry ADD COLUMN direction_id BIGINT;
        UPDATE transaction_entry e
            SET direction_id = d.id
            FROM transaction_direction d
            WHERE d.enumerator = e.direction;

        IF EXISTS (SELECT 1 FROM transaction_entry WHERE direction_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill direction incompleto.';
        END IF;

        ALTER TABLE transaction_entry ALTER COLUMN direction_id SET NOT NULL;
        ALTER TABLE transaction_entry
            ADD CONSTRAINT transaction_entry_direction_id_fkey
            FOREIGN KEY (direction_id) REFERENCES transaction_direction(id) ON DELETE RESTRICT;
        ALTER TABLE transaction_entry DROP CONSTRAINT IF EXISTS ck_transaction_entry_direction;
        ALTER TABLE transaction_entry DROP COLUMN direction;
        CREATE INDEX IF NOT EXISTS idx_transaction_entry_direction
            ON transaction_entry (direction_id);
    END IF;

    -- 4b. entry_type_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'transaction_entry'
          AND column_name = 'entry_type'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM transaction_entry e
            LEFT JOIN entry_type et ON et.enumerator = e.entry_type
            WHERE et.id IS NULL
        ) THEN
            RAISE EXCEPTION 'Backfill entry_type: valor textual sem lookup.';
        END IF;

        ALTER TABLE transaction_entry ADD COLUMN entry_type_id BIGINT;
        UPDATE transaction_entry e
            SET entry_type_id = et.id
            FROM entry_type et
            WHERE et.enumerator = e.entry_type;

        IF EXISTS (SELECT 1 FROM transaction_entry WHERE entry_type_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill entry_type incompleto.';
        END IF;

        ALTER TABLE transaction_entry ALTER COLUMN entry_type_id SET NOT NULL;
        ALTER TABLE transaction_entry
            ADD CONSTRAINT transaction_entry_entry_type_id_fkey
            FOREIGN KEY (entry_type_id) REFERENCES entry_type(id) ON DELETE RESTRICT;
        ALTER TABLE transaction_entry DROP CONSTRAINT IF EXISTS ck_transaction_entry_type;
        ALTER TABLE transaction_entry DROP COLUMN entry_type;
        CREATE INDEX IF NOT EXISTS idx_transaction_entry_entry_type
            ON transaction_entry (entry_type_id);
    END IF;

    -- 4c. entry_key (COD-05) — adiciona, backfilla com UUID por linha, torna
    --     NOT NULL e UNIQUE. A chave interna id (PK) é preservada intacta.
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'transaction_entry'
          AND column_name = 'entry_key'
    ) THEN
        ALTER TABLE transaction_entry ADD COLUMN entry_key UUID;
        UPDATE transaction_entry SET entry_key = gen_random_uuid()
            WHERE entry_key IS NULL;

        IF EXISTS (SELECT 1 FROM transaction_entry WHERE entry_key IS NULL) THEN
            RAISE EXCEPTION 'Backfill entry_key incompleto.';
        END IF;

        ALTER TABLE transaction_entry ALTER COLUMN entry_key SET NOT NULL;
        ALTER TABLE transaction_entry
            ADD CONSTRAINT transaction_entry_entry_key_key UNIQUE (entry_key);
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 5. actor_type em client_status_event e account_status_event
--    (blocos explícitos por tabela — mais legível e sem DO aninhado).
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'client_status_event'
          AND column_name = 'actor_type'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM client_status_event e
            LEFT JOIN actor_type a ON a.enumerator = e.actor_type
            WHERE a.id IS NULL
        ) THEN
            RAISE EXCEPTION 'Backfill actor_type (client_status_event): valor sem lookup.';
        END IF;

        ALTER TABLE client_status_event ADD COLUMN actor_type_id BIGINT;
        UPDATE client_status_event e
            SET actor_type_id = a.id
            FROM actor_type a WHERE a.enumerator = e.actor_type;

        IF EXISTS (SELECT 1 FROM client_status_event WHERE actor_type_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill actor_type (client_status_event) incompleto.';
        END IF;

        ALTER TABLE client_status_event ALTER COLUMN actor_type_id SET NOT NULL;
        ALTER TABLE client_status_event
            ADD CONSTRAINT client_status_event_actor_type_id_fkey
            FOREIGN KEY (actor_type_id) REFERENCES actor_type(id) ON DELETE RESTRICT;
        ALTER TABLE client_status_event
            DROP CONSTRAINT IF EXISTS ck_client_status_event_actor_type;
        ALTER TABLE client_status_event DROP COLUMN actor_type;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'account_status_event'
          AND column_name = 'actor_type'
    ) THEN
        IF EXISTS (
            SELECT 1 FROM account_status_event e
            LEFT JOIN actor_type a ON a.enumerator = e.actor_type
            WHERE a.id IS NULL
        ) THEN
            RAISE EXCEPTION 'Backfill actor_type (account_status_event): valor sem lookup.';
        END IF;

        ALTER TABLE account_status_event ADD COLUMN actor_type_id BIGINT;
        UPDATE account_status_event e
            SET actor_type_id = a.id
            FROM actor_type a WHERE a.enumerator = e.actor_type;

        IF EXISTS (SELECT 1 FROM account_status_event WHERE actor_type_id IS NULL) THEN
            RAISE EXCEPTION 'Backfill actor_type (account_status_event) incompleto.';
        END IF;

        ALTER TABLE account_status_event ALTER COLUMN actor_type_id SET NOT NULL;
        ALTER TABLE account_status_event
            ADD CONSTRAINT account_status_event_actor_type_id_fkey
            FOREIGN KEY (actor_type_id) REFERENCES actor_type(id) ON DELETE RESTRICT;
        ALTER TABLE account_status_event
            DROP CONSTRAINT IF EXISTS ck_account_status_event_actor_type;
        ALTER TABLE account_status_event DROP COLUMN actor_type;
    END IF;
END $$;

-- ---------------------------------------------------------------------
-- 6. Validação de integridade pós-migração (falha explícita)
-- ---------------------------------------------------------------------
DO $$
BEGIN
    -- Nenhuma FK nova pode estar nula.
    IF EXISTS (SELECT 1 FROM client WHERE client_type_id IS NULL)
       OR EXISTS (SELECT 1 FROM financial_transaction WHERE transaction_type_id IS NULL)
       OR EXISTS (SELECT 1 FROM transaction_entry
                  WHERE direction_id IS NULL OR entry_type_id IS NULL OR entry_key IS NULL)
       OR EXISTS (SELECT 1 FROM client_status_event WHERE actor_type_id IS NULL)
       OR EXISTS (SELECT 1 FROM account_status_event WHERE actor_type_id IS NULL) THEN
        RAISE EXCEPTION 'Validação pós-migração: FK/entry_key nulo encontrado.';
    END IF;

    -- entry_key totalmente único (uma chave por lançamento).
    IF (SELECT count(*) FROM transaction_entry)
       <> (SELECT count(DISTINCT entry_key) FROM transaction_entry) THEN
        RAISE EXCEPTION 'Validação pós-migração: entry_key duplicado.';
    END IF;

    -- Lookups sem duplicata de enumerator (reforça idempotência).
    IF (SELECT count(*) FROM client_type) <> (SELECT count(DISTINCT enumerator) FROM client_type)
       OR (SELECT count(*) FROM transaction_type) <> (SELECT count(DISTINCT enumerator) FROM transaction_type)
       OR (SELECT count(*) FROM transaction_direction) <> (SELECT count(DISTINCT enumerator) FROM transaction_direction)
       OR (SELECT count(*) FROM entry_type) <> (SELECT count(DISTINCT enumerator) FROM entry_type)
       OR (SELECT count(*) FROM actor_type) <> (SELECT count(DISTINCT enumerator) FROM actor_type) THEN
        RAISE EXCEPTION 'Validação pós-migração: lookup com enumerator duplicado.';
    END IF;
END $$;

COMMIT;
