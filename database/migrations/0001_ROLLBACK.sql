-- =====================================================================
-- Rollback estrutural da migração 0001 (P1-D).
-- ---------------------------------------------------------------------
-- Reverte o schema alvo (lookups + FK + entry_key) para o schema textual
-- antigo (VARCHAR + CHECK IN, transaction_entry sem entry_key).
--
-- É LOSSLESS para os dados de negócio porque o enumerator textual é
-- reconstruído a partir da própria lookup (mesmo texto). O entry_key, por
-- ser um identificador introduzido na 0001, é descartado no rollback — isto
-- é intencional e seguro, pois ele não é referenciado por nenhuma FK.
--
-- RECOMENDAÇÃO: em produção/ambientes persistentes, PREFIRA restaurar do
-- pg_dump feito antes da 0001. Use este script apenas quando o restore do
-- backup não for viável e a reversão estrutural for suficiente.
--
-- Uso:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/migrations/0001_ROLLBACK.sql
-- =====================================================================

BEGIN;

-- client.client_type_id → client.client_type (VARCHAR + CHECK)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='client' AND column_name='client_type_id'
    ) THEN
        ALTER TABLE client ADD COLUMN client_type VARCHAR(20);
        UPDATE client c SET client_type = ct.enumerator
            FROM client_type ct WHERE ct.id = c.client_type_id;
        ALTER TABLE client ALTER COLUMN client_type SET NOT NULL;
        ALTER TABLE client ADD CONSTRAINT ck_client_type
            CHECK (client_type IN ('INDIVIDUAL','COMPANY'));
        ALTER TABLE client DROP CONSTRAINT IF EXISTS client_client_type_id_fkey;
        DROP INDEX IF EXISTS idx_client_type;
        ALTER TABLE client DROP COLUMN client_type_id;
    END IF;
END $$;

-- financial_transaction.transaction_type_id → transaction_type (VARCHAR + CHECK)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='financial_transaction' AND column_name='transaction_type_id'
    ) THEN
        ALTER TABLE financial_transaction ADD COLUMN transaction_type VARCHAR(20);
        UPDATE financial_transaction f SET transaction_type = tt.enumerator
            FROM transaction_type tt WHERE tt.id = f.transaction_type_id;
        ALTER TABLE financial_transaction ALTER COLUMN transaction_type SET NOT NULL;
        ALTER TABLE financial_transaction ADD CONSTRAINT ck_financial_transaction_type
            CHECK (transaction_type IN ('DEPOSIT','TRANSFER'));
        ALTER TABLE financial_transaction DROP CONSTRAINT IF EXISTS financial_transaction_transaction_type_id_fkey;
        DROP INDEX IF EXISTS idx_financial_transaction_type;
        ALTER TABLE financial_transaction DROP COLUMN transaction_type_id;
    END IF;
END $$;

-- transaction_entry: direction_id/entry_type_id → texto + CHECK; remove entry_key
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='transaction_entry' AND column_name='direction_id'
    ) THEN
        ALTER TABLE transaction_entry ADD COLUMN direction VARCHAR(10);
        UPDATE transaction_entry e SET direction = d.enumerator
            FROM transaction_direction d WHERE d.id = e.direction_id;
        ALTER TABLE transaction_entry ALTER COLUMN direction SET NOT NULL;
        ALTER TABLE transaction_entry ADD CONSTRAINT ck_transaction_entry_direction
            CHECK (direction IN ('DEBIT','CREDIT'));
        ALTER TABLE transaction_entry DROP CONSTRAINT IF EXISTS transaction_entry_direction_id_fkey;
        DROP INDEX IF EXISTS idx_transaction_entry_direction;
        ALTER TABLE transaction_entry DROP COLUMN direction_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='transaction_entry' AND column_name='entry_type_id'
    ) THEN
        ALTER TABLE transaction_entry ADD COLUMN entry_type VARCHAR(20);
        UPDATE transaction_entry e SET entry_type = et.enumerator
            FROM entry_type et WHERE et.id = e.entry_type_id;
        ALTER TABLE transaction_entry ALTER COLUMN entry_type SET NOT NULL;
        ALTER TABLE transaction_entry ADD CONSTRAINT ck_transaction_entry_type
            CHECK (entry_type IN ('PRINCIPAL','FEE'));
        ALTER TABLE transaction_entry DROP CONSTRAINT IF EXISTS transaction_entry_entry_type_id_fkey;
        DROP INDEX IF EXISTS idx_transaction_entry_entry_type;
        ALTER TABLE transaction_entry DROP COLUMN entry_type_id;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='transaction_entry' AND column_name='entry_key'
    ) THEN
        ALTER TABLE transaction_entry DROP CONSTRAINT IF EXISTS transaction_entry_entry_key_key;
        ALTER TABLE transaction_entry DROP COLUMN entry_key;
    END IF;
END $$;

-- *_status_event.actor_type_id → actor_type (VARCHAR + CHECK)
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['client_status_event','account_status_event']
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name=tbl AND column_name='actor_type_id'
        ) THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN actor_type VARCHAR(20);', tbl);
            EXECUTE format(
                'UPDATE %1$I e SET actor_type = a.enumerator
                 FROM actor_type a WHERE a.id = e.actor_type_id;', tbl);
            EXECUTE format('ALTER TABLE %I ALTER COLUMN actor_type SET NOT NULL;', tbl);
            EXECUTE format(
                'ALTER TABLE %1$I ADD CONSTRAINT ck_%1$s_actor_type
                 CHECK (actor_type IN (''SYSTEM'',''INTERNAL''));', tbl);
            EXECUTE format('ALTER TABLE %1$I DROP CONSTRAINT IF EXISTS %1$s_actor_type_id_fkey;', tbl);
            EXECUTE format('ALTER TABLE %I DROP COLUMN actor_type_id;', tbl);
        END IF;
    END LOOP;
END $$;

-- As tabelas de lookup introduzidas pela 0001 são removidas por último,
-- depois que nenhuma FK as referencia mais.
DROP TABLE IF EXISTS client_type;
DROP TABLE IF EXISTS transaction_type;
DROP TABLE IF EXISTS transaction_direction;
DROP TABLE IF EXISTS entry_type;
DROP TABLE IF EXISTS actor_type;

COMMIT;
