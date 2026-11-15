-- =====================================================================
-- Tabelas de lookup (enumerações normalizadas) — padrão (id, enumerator).
-- P1-D/COD-06: substituem os CHECK IN (...) textuais por integridade
-- referencial. A representação textual externa continua sendo o
-- `enumerator`, resolvido pela camada ORM/repositories.
-- =====================================================================

CREATE TABLE client_status (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_client_status_enumerator
        CHECK (enumerator IN ('PENDING', 'ACTIVE', 'REJECTED', 'INACTIVE'))
);

INSERT INTO client_status (enumerator) VALUES
    ('PENDING'),
    ('ACTIVE'),
    ('REJECTED'),
    ('INACTIVE');

CREATE TABLE account_status (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_account_status_enumerator
        CHECK (enumerator IN ('ACTIVE', 'INACTIVE', 'CLOSED'))
);

INSERT INTO account_status (enumerator) VALUES
    ('ACTIVE'),
    ('INACTIVE'),
    ('CLOSED');

CREATE TABLE client_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_client_type_enumerator
        CHECK (enumerator IN ('INDIVIDUAL', 'COMPANY'))
);

INSERT INTO client_type (enumerator) VALUES
    ('INDIVIDUAL'),
    ('COMPANY');

CREATE TABLE transaction_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_transaction_type_enumerator
        CHECK (enumerator IN ('DEPOSIT', 'TRANSFER'))
);

INSERT INTO transaction_type (enumerator) VALUES
    ('DEPOSIT'),
    ('TRANSFER');

CREATE TABLE transaction_direction (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(10) NOT NULL UNIQUE,
    CONSTRAINT ck_transaction_direction_enumerator
        CHECK (enumerator IN ('DEBIT', 'CREDIT'))
);

INSERT INTO transaction_direction (enumerator) VALUES
    ('DEBIT'),
    ('CREDIT');

CREATE TABLE entry_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_entry_type_enumerator
        CHECK (enumerator IN ('PRINCIPAL', 'FEE'))
);

INSERT INTO entry_type (enumerator) VALUES
    ('PRINCIPAL'),
    ('FEE');

CREATE TABLE actor_type (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    enumerator VARCHAR(20) NOT NULL UNIQUE,
    CONSTRAINT ck_actor_type_enumerator
        CHECK (enumerator IN ('SYSTEM', 'INTERNAL'))
);

INSERT INTO actor_type (enumerator) VALUES
    ('SYSTEM'),
    ('INTERNAL');

-- =====================================================================
-- Cadastro e ciclo de vida do cliente.
-- =====================================================================

CREATE TABLE client (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    client_key UUID NOT NULL UNIQUE,
    client_type_id BIGINT NOT NULL REFERENCES client_type(id) ON DELETE RESTRICT,
    email VARCHAR(254) NOT NULL UNIQUE,
    timezone VARCHAR(64) NOT NULL,
    status_id BIGINT NOT NULL REFERENCES client_status(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_client_status ON client (status_id);
CREATE INDEX idx_client_type ON client (client_type_id);

-- Especialização PF: client_id é simultaneamente PK e FK (vínculo 1:1).
-- P1-D/COD-05: desenho preservado (ver docs/P1D-DATABASE-AUDIT.md §2.2).
CREATE TABLE individual_client (
    client_id BIGINT PRIMARY KEY REFERENCES client(id) ON DELETE RESTRICT,
    cpf VARCHAR(11) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    birth_date DATE NOT NULL
);

-- Especialização PJ: client_id é simultaneamente PK e FK (vínculo 1:1).
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
    actor_type_id BIGINT NOT NULL REFERENCES actor_type(id) ON DELETE RESTRICT,
    reason VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_client_status_event_history
    ON client_status_event (client_id, created_at, id);

-- =====================================================================
-- Contas, histórico e movimentações financeiras.
-- =====================================================================

CREATE TABLE account (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_key UUID NOT NULL UNIQUE,
    client_id BIGINT NOT NULL UNIQUE REFERENCES client(id) ON DELETE RESTRICT,
    status_id BIGINT NOT NULL REFERENCES account_status(id) ON DELETE RESTRICT,
    balance_cents BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT ck_balance_cents
        CHECK (balance_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_account_status ON account (status_id);

CREATE TABLE account_status_event (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    from_status_id BIGINT REFERENCES account_status(id) ON DELETE RESTRICT,
    to_status_id BIGINT NOT NULL REFERENCES account_status(id) ON DELETE RESTRICT,
    actor_type_id BIGINT NOT NULL REFERENCES actor_type(id) ON DELETE RESTRICT,
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
    transaction_type_id BIGINT NOT NULL REFERENCES transaction_type(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_financial_transaction_type
    ON financial_transaction (transaction_type_id);

CREATE TABLE transaction_entry (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entry_key UUID NOT NULL UNIQUE,
    transaction_id BIGINT NOT NULL REFERENCES financial_transaction(id) ON DELETE RESTRICT,
    account_id BIGINT NOT NULL REFERENCES account(id) ON DELETE RESTRICT,
    direction_id BIGINT NOT NULL REFERENCES transaction_direction(id) ON DELETE RESTRICT,
    entry_type_id BIGINT NOT NULL REFERENCES entry_type(id) ON DELETE RESTRICT,
    amount_cents BIGINT NOT NULL,
    CONSTRAINT ck_transaction_entry_amount_cents
        CHECK (amount_cents > 0),
    balance_after_cents BIGINT NOT NULL,
    CONSTRAINT ck_transaction_entry_balance_after_cents
        CHECK (balance_after_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_transaction_entry_account
    ON transaction_entry (account_id);

CREATE INDEX idx_transaction_entry_transaction
    ON transaction_entry (transaction_id);

CREATE INDEX idx_transaction_entry_direction
    ON transaction_entry (direction_id);

CREATE INDEX idx_transaction_entry_entry_type
    ON transaction_entry (entry_type_id);
