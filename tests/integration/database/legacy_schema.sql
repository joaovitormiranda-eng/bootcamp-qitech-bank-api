-- =====================================================================
-- Schema LEGADO (pré-P1-D), usado SOMENTE pelo teste de migração populada.
-- Reproduz o estado do banco antes da normalização COD-05/COD-06:
--   * enums como VARCHAR + CHECK IN (...)
--   * transaction_entry sem entry_key
-- A migração database/migrations/0001_*.sql deve levar este schema (já
-- populado) ao schema alvo de database/database.sql sem perda de dados.
-- Este arquivo NÃO é usado pelo bootstrap da aplicação.
-- =====================================================================

CREATE TABLE client_status (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_client_status_enumerator
        CHECK (enumerator IN ('PENDING', 'ACTIVE', 'REJECTED', 'INACTIVE'))
);
INSERT INTO client_status (enumerator) VALUES
    ('PENDING'), ('ACTIVE'), ('REJECTED'), ('INACTIVE');

CREATE TABLE account_status (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_account_status_enumerator
        CHECK (enumerator IN ('ACTIVE', 'INACTIVE', 'CLOSED'))
);
INSERT INTO account_status (enumerator) VALUES
    ('ACTIVE'), ('INACTIVE'), ('CLOSED');

CREATE TABLE client (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_key UUID NOT NULL UNIQUE,
    client_type VARCHAR(20) NOT NULL,
    CONSTRAINT ck_client_type
        CHECK (client_type IN ('INDIVIDUAL', 'COMPANY')),
    email VARCHAR(254) NOT NULL UNIQUE,
    timezone VARCHAR(64) NOT NULL,
    status_id BIGINT NOT NULL REFERENCES client_status(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_client_status ON client (status_id);

CREATE TABLE individual_client (
    client_id BIGINT PRIMARY KEY REFERENCES client(id) ON DELETE RESTRICT,
    cpf VARCHAR(11) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    birth_date DATE NOT NULL
);

CREATE TABLE company_client (
    client_id BIGINT PRIMARY KEY REFERENCES client(id) ON DELETE RESTRICT,
    cnpj VARCHAR(14) NOT NULL UNIQUE,
    legal_name VARCHAR(200) NOT NULL,
    trade_name VARCHAR(200)
);

CREATE TABLE client_status_event (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_id BIGINT NOT NULL REFERENCES client(id) ON DELETE RESTRICT,
    from_status_id BIGINT REFERENCES client_status(id) ON DELETE RESTRICT,
    to_status_id BIGINT NOT NULL REFERENCES client_status(id) ON DELETE RESTRICT,
    actor_type VARCHAR(20) NOT NULL,
    CONSTRAINT ck_client_status_event_actor_type
        CHECK (actor_type IN ('SYSTEM', 'INTERNAL')),
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_client_status_event_history
    ON client_status_event (client_id, created_at, id);

CREATE TABLE account (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_key UUID NOT NULL UNIQUE,
    client_id BIGINT NOT NULL UNIQUE REFERENCES client(id) ON DELETE RESTRICT,
    status_id BIGINT NOT NULL REFERENCES account_status(id) ON DELETE RESTRICT,
    balance_cents BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT ck_balance_cents CHECK (balance_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_account_status ON account (status_id);

CREATE TABLE account_status_event (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    from_status_id BIGINT REFERENCES account_status(id) ON DELETE RESTRICT,
    to_status_id BIGINT NOT NULL REFERENCES account_status(id) ON DELETE RESTRICT,
    actor_type VARCHAR(20) NOT NULL,
    CONSTRAINT ck_account_status_event_actor_type
        CHECK (actor_type IN ('SYSTEM', 'INTERNAL')),
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_account_status_event_history
    ON account_status_event (account_id, created_at, id);

CREATE TABLE financial_transaction (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_key UUID NOT NULL UNIQUE,
    request_control_key UUID NOT NULL UNIQUE,
    request_hash CHAR(64) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    CONSTRAINT ck_financial_transaction_type
        CHECK (transaction_type IN ('DEPOSIT', 'TRANSFER')),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE transaction_entry (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id BIGINT NOT NULL REFERENCES financial_transaction(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    direction VARCHAR(10) NOT NULL,
    CONSTRAINT ck_transaction_entry_direction
        CHECK (direction IN ('DEBIT', 'CREDIT')),
    entry_type VARCHAR(20) NOT NULL,
    CONSTRAINT ck_transaction_entry_type
        CHECK (entry_type IN ('PRINCIPAL', 'FEE')),
    amount_cents BIGINT NOT NULL,
    CONSTRAINT ck_transaction_entry_amount_cents CHECK (amount_cents > 0),
    balance_after_cents BIGINT NOT NULL,
    CONSTRAINT ck_transaction_entry_balance_after_cents CHECK (balance_after_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_transaction_entry_account ON transaction_entry (account_id);
CREATE INDEX idx_transaction_entry_transaction ON transaction_entry (transaction_id);
