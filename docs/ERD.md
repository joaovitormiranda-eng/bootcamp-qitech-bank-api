# Modelo de Dados (ERD) — BaaS Simplificado

**Bootcamp QI Tech 2026**

**Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Versão:** 3.0 · schema atual com 15 tabelas · versão original de 12/10/2026

**Documentos relacionados:** [RFC](RFC.md) · [RFC em PDF](RFC.pdf) · [Rotas](ROTAS.md) · [Fluxos](FLUXOS.md) · [Arquitetura](ARQUITETURA.md) · [Migrações](MIGRACOES.md) · [Esquema PostgreSQL](../database/database.sql)

**Fonte autoritativa:** o DDL executável em [`database/database.sql`](../database/database.sql). O DBML da [Seção 6](#6-especificação-dbml-complementar) reproduz o mesmo schema. O [modelo no dbdiagram.io](https://dbdiagram.io/d/ERD-bootcamp-QItech-6abc58be5869425612d24fa6) foi criado na entrega original, antes da normalização das enumerações; trate-o como referência histórica, não como o modelo atual.

## 1. Visão geral

O **BaaS Simplificado** utiliza PostgreSQL para persistir os dados cadastrais de pessoas físicas (PF) e jurídicas (PJ), o ciclo de vida de clientes e contas e as movimentações financeiras. O modelo atende ao escopo brasileiro do produto, com valores monetários em **BRL**, representados por inteiros em centavos.

A estrutura contém **15 tabelas**: **8 de domínio** e **7 de lookup**, organizadas em quatro grupos:

| Grupo | Entidades | Responsabilidade |
|---|---|---|
| Cadastro | `client`, `individual_client`, `company_client`, `client_status_event` | Identidade PF/PJ, estado cadastral e histórico de transições |
| Contas | `account`, `account_status_event` | Conta vinculada ao cliente, saldo e histórico de estados |
| Financeiro | `financial_transaction`, `transaction_entry` | Operações, idempotência e lançamentos que compõem o extrato |
| Lookup (enumerações) | `client_status`, `account_status`, `client_type`, `transaction_type`, `transaction_direction`, `entry_type`, `actor_type` | Valores enumerados normalizados `(id, enumerator)` referenciados por `FOREIGN KEY` |

> **Evolução em relação à entrega original.** O schema de 12/10/2026 tinha 10
> tabelas: as lookups `client_status` e `account_status` já existiam, mas
> `client.client_type`, `financial_transaction.transaction_type`,
> `transaction_entry.direction`, `transaction_entry.entry_type` e os
> `*_status_event.actor_type` eram colunas `VARCHAR` com `CHECK IN (...)`. O
> schema atual acrescenta as cinco lookups restantes e troca essas colunas por
> FKs `*_id` (`client_type_id`, `transaction_type_id`, `direction_id`,
> `entry_type_id`, `actor_type_id`). A API continua expondo o texto do
> `enumerator`, resolvido pelos models e repositories. `transaction_entry`
> ganhou a chave pública `entry_key UUID NOT NULL UNIQUE`; `id BIGINT` continua
> sendo a PK usada em locks e na ordenação do extrato. As especializações
> `individual_client` e `company_client` mantêm `client_id` como PK e FK (vínculo
> 1:1 com `client`). Bancos criados com o schema anterior evoluem pela migração
> versionada descrita em [MIGRACOES.md](MIGRACOES.md).

Para manter os relacionamentos legíveis, a representação Mermaid é dividida em **dois diagramas complementares**, com uma visão separada das tabelas de lookup. A tabela `client` é repetida de forma resumida no segundo desenho apenas para estabelecer a ligação entre cadastro e contas; existe uma única tabela `client` no banco.

## 2. Diagramas de entidade-relacionamento

### 2.1 Cadastro, perfis PF/PJ e estados do cliente

```mermaid
%%{init: {"theme":"dark", "themeVariables":{"background":"#0b1524","primaryColor":"#152b3d","primaryTextColor":"#f1f5f9","primaryBorderColor":"#38bdf8","lineColor":"#75aaff","textColor":"#f1f5f9","mainBkg":"#152b3d","secondaryColor":"#152b3d","tertiaryColor":"#152b3d","edgeLabelBackground":"#152b3d","fontFamily":"Arial","fontSize":"13px"}, "er":{"fill":"#152b3d","stroke":"#38bdf8","fontSize":13,"entityPadding":12,"nodeSpacing":70,"rankSpacing":78}}}%%
erDiagram
    direction TB

    CLIENT_STATUS ||--o{ CLIENT : "estado atual"
    CLIENT_TYPE ||--o{ CLIENT : "tipo PF/PJ"
    CLIENT ||--o| INDIVIDUAL_CLIENT : "perfil PF"
    CLIENT ||--o| COMPANY_CLIENT : "perfil PJ"
    CLIENT ||--o{ CLIENT_STATUS_EVENT : "historico"
    CLIENT_STATUS ||--o{ CLIENT_STATUS_EVENT : "status do evento"
    ACTOR_TYPE ||--o{ CLIENT_STATUS_EVENT : "ator do evento"

    CLIENT_STATUS {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    CLIENT_TYPE {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    ACTOR_TYPE {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    CLIENT {
        BIGINT id PK
        UUID client_key UK
        BIGINT client_type_id FK
        VARCHAR email UK
        VARCHAR timezone
        BIGINT status_id FK
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    INDIVIDUAL_CLIENT {
        BIGINT client_id PK,FK
        VARCHAR cpf UK
        VARCHAR full_name
        DATE birth_date
    }

    COMPANY_CLIENT {
        BIGINT client_id PK,FK
        VARCHAR cnpj UK
        VARCHAR legal_name
        VARCHAR trade_name "nullable"
    }

    CLIENT_STATUS_EVENT {
        BIGINT id PK
        BIGINT client_id FK
        BIGINT from_status_id FK "nullable no evento inicial"
        BIGINT to_status_id FK
        BIGINT actor_type_id FK
        VARCHAR reason "nullable conforme transicao"
        TIMESTAMPTZ created_at
    }
```

> Observação: `CLIENT_STATUS` aparece ligada a `CLIENT` (estado atual) e a
> `CLIENT_STATUS_EVENT` (via `from_status_id`/`to_status_id`). A lookup
> `CLIENT_TYPE` substitui a antiga coluna textual `client.client_type`, e
> `ACTOR_TYPE` substitui `client_status_event.actor_type`.

### 2.2 Contas, estados e movimentações financeiras

```mermaid
%%{init: {"theme":"dark", "themeVariables":{"background":"#0b1524","primaryColor":"#152b3d","primaryTextColor":"#f1f5f9","primaryBorderColor":"#38bdf8","lineColor":"#75aaff","textColor":"#f1f5f9","mainBkg":"#152b3d","secondaryColor":"#152b3d","tertiaryColor":"#152b3d","edgeLabelBackground":"#152b3d","fontFamily":"Arial","fontSize":"13px"}, "er":{"fill":"#152b3d","stroke":"#38bdf8","fontSize":13,"entityPadding":12,"nodeSpacing":70,"rankSpacing":78}}}%%
erDiagram
    direction TB

    CLIENT ||--o| ACCOUNT : "conta unica"
    ACCOUNT_STATUS ||--o{ ACCOUNT : "estado atual"
    ACCOUNT ||--o{ ACCOUNT_STATUS_EVENT : "historico"
    ACCOUNT_STATUS ||--o{ ACCOUNT_STATUS_EVENT : "status do evento"
    ACTOR_TYPE ||--o{ ACCOUNT_STATUS_EVENT : "ator do evento"
    ACCOUNT ||--o{ TRANSACTION_ENTRY : "lancamentos"
    FINANCIAL_TRANSACTION ||--|{ TRANSACTION_ENTRY : "efeitos"
    TRANSACTION_TYPE ||--o{ FINANCIAL_TRANSACTION : "tipo da operacao"
    TRANSACTION_DIRECTION ||--o{ TRANSACTION_ENTRY : "direcao"
    ENTRY_TYPE ||--o{ TRANSACTION_ENTRY : "natureza"

    CLIENT {
        BIGINT id PK
        UUID client_key UK
    }

    ACCOUNT_STATUS {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    ACTOR_TYPE {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    TRANSACTION_TYPE {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    TRANSACTION_DIRECTION {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    ENTRY_TYPE {
        BIGINT id PK
        VARCHAR enumerator UK
    }

    ACCOUNT {
        BIGINT id PK
        UUID account_key UK
        BIGINT client_id FK,UK
        BIGINT status_id FK
        BIGINT balance_cents
        TIMESTAMPTZ created_at
        TIMESTAMPTZ updated_at
    }

    ACCOUNT_STATUS_EVENT {
        BIGINT id PK
        BIGINT account_id FK
        BIGINT from_status_id FK "nullable no evento inicial"
        BIGINT to_status_id FK
        BIGINT actor_type_id FK
        VARCHAR reason "nullable conforme transicao"
        TIMESTAMPTZ created_at
    }

    FINANCIAL_TRANSACTION {
        BIGINT id PK
        UUID transaction_key UK
        UUID request_control_key UK
        CHAR request_hash
        BIGINT transaction_type_id FK
        TIMESTAMPTZ created_at
    }

    TRANSACTION_ENTRY {
        BIGINT id PK
        UUID entry_key UK
        BIGINT transaction_id FK
        BIGINT account_id FK
        BIGINT direction_id FK
        BIGINT entry_type_id FK
        BIGINT amount_cents
        BIGINT balance_after_cents
        TIMESTAMPTZ created_at
    }
```

**Legenda:** `PK` = chave primária; `FK` = chave estrangeira; `UK` = restrição de unicidade. A notação `||--o|` representa no máximo um registro dependente por entidade principal; `||--o{` representa zero ou muitos. Nos históricos, `from_status_id` e `to_status_id` referenciam a respectiva tabela de estados; a associação foi reunida visualmente para simplificar a leitura, sem eliminar as chaves do esquema físico.

## 3. Relacionamentos e cardinalidades

| Relacionamento | Cardinalidade e regra de integridade |
|---|---|
| `client_status → client` | Cada cliente possui um estado atual; um estado pode estar associado a vários clientes. |
| `client → individual_client` | No máximo um perfil PF por cliente, via `client_id` como PK e FK. |
| `client → company_client` | No máximo um perfil PJ por cliente, via `client_id` como PK e FK. |
| `client → client_status_event` | Um cliente pode possuir vários eventos de transição cadastral. |
| `client_status → client_status_event` | `to_status_id` obrigatório; `from_status_id` opcional para o evento inicial. |
| `client → account` | Zero ou uma conta por cliente, garantido por `UNIQUE(account.client_id)`. |
| `account_status → account` | Cada conta possui um estado atual; um estado pode estar associado a várias contas. |
| `account → account_status_event` | Uma conta pode possuir vários eventos de alteração de estado. |
| `account_status → account_status_event` | `to_status_id` obrigatório; `from_status_id` opcional para o evento inicial. |
| `account → transaction_entry` | Uma conta pode possuir vários lançamentos de débito ou crédito. |
| `financial_transaction → transaction_entry` | Cada lançamento pertence a uma operação; uma operação confirmada registra seus efeitos na mesma transação do banco. |
| `client_type → client` | `client.client_type_id` referencia a lookup; tipo PF/PJ por FK, não por texto. |
| `transaction_type → financial_transaction` | `financial_transaction.transaction_type_id` referencia a lookup (`DEPOSIT`/`TRANSFER`). |
| `transaction_direction → transaction_entry` | `transaction_entry.direction_id` referencia a lookup (`DEBIT`/`CREDIT`). |
| `entry_type → transaction_entry` | `transaction_entry.entry_type_id` referencia a lookup (`PRINCIPAL`/`FEE`). |
| `actor_type → *_status_event` | `actor_type_id` em ambos os históricos referencia a lookup (`SYSTEM`/`INTERNAL`). |

A separação entre `individual_client` e `company_client` atende à especialização PF/PJ definida por `client.client_type_id` (FK para `client_type`). A aplicação mantém **um perfil compatível com o tipo de cliente** durante a criação cadastral. Todas as FKs usam `ON DELETE RESTRICT`.

## 4. Integridade e regras de negócio

### 4.1 Clientes e contas

- **Identificadores:** chaves internas `BIGINT` e identificadores públicos `UUID` (`client_key`, `account_key`, `transaction_key` e `transaction_entry.entry_key`, este último adicionado pela migração `0001`).
- **Cadastro:** CPF, CNPJ e email possuem restrições de unicidade; dados obrigatórios são definidos por `NOT NULL` e pela validação de domínio. O email é normalizado antes da persistência.
- **Perfis:** clientes `INDIVIDUAL` possuem os dados de CPF, nome e nascimento; clientes `COMPANY` possuem CNPJ e razão social, com nome fantasia opcional. Para PF, aplica-se a idade mínima de 18 anos.
- **Fuso horário:** `client.timezone` armazena um identificador IANA de referência do cliente, utilizado para interpretar filtros por datas civis.
- **Estados do cliente:** `PENDING`, `ACTIVE`, `REJECTED` e `INACTIVE`; alterações registram estado anterior, novo estado, ator, motivo quando aplicável e data/hora.
- **Conta:** um cliente ativo pode abrir uma conta; a conta é criada `ACTIVE`, com saldo inicial de zero. Seus estados possíveis são `ACTIVE`, `INACTIVE` e `CLOSED`.
- **Saldo:** `account.balance_cents` é um `BIGINT` com `DEFAULT 0` e `CHECK (balance_cents >= 0)`. A conta encerrada não é reaberta e a abertura de outra conta para o mesmo cliente é impedida pela unicidade de `client_id`.

### 4.2 Operações financeiras e extrato

- `financial_transaction` identifica a operação financeira (`DEPOSIT` ou `TRANSFER`) e armazena a chave de idempotência recebida no header HTTP `Idempotency-Key` como `request_control_key`, única no banco, com `request_hash` para distinguir a intenção da requisição.
- `transaction_entry` registra cada lançamento por conta, sua direção (`DEBIT` ou `CREDIT`), natureza (`PRINCIPAL` ou `FEE`), valor e saldo resultante.
- Os valores são representados em **centavos**, sem uso de ponto flutuante: `amount_cents > 0` e `balance_after_cents >= 0` são garantidos por restrições `CHECK`.
- **Depósito:** registra um crédito principal na conta destinatária.
- **Transferência interna:** registra débito principal na origem, débito da tarifa na origem e crédito principal no destino. A tarifa de transferência é calculada pela aplicação de acordo com o tipo do cliente de origem: PF — 0,50% (mínimo 50 e máximo 1.000 centavos); PJ — 1,00% (mínimo 100 e máximo 1.500 centavos), com arredondamento `HALF_UP`.
- **Atomicidade:** registros financeiros e atualizações de saldo pertencem à mesma transação PostgreSQL. Em caso de falha, ocorre `ROLLBACK`, evitando efeitos parciais.
- **Concorrência:** o processamento de movimentações utiliza bloqueios de linha e ordenação consistente de aquisição dos bloqueios nas contas envolvidas.
- **Extrato (R08):** consulta os lançamentos associados à conta e às respectivas operações, com paginação e filtros por data; a interpretação das datas considera o fuso horário cadastrado do cliente. Principal e tarifa são apresentados como lançamentos distintos.

### 4.3 Restrições e índices do PostgreSQL

O esquema combina `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `NOT NULL`, `CHECK` e `ON DELETE RESTRICT` para preservar as relações e impedir estados incompatíveis com as restrições físicas. As regras de transição, especialização exclusiva PF/PJ, ordem dos lançamentos e processamento idempotente são coordenadas pela camada de aplicação dentro das transações de banco.

Além dos índices de suporte criados pelas chaves primárias e pelas restrições de unicidade (incluindo `transaction_entry.entry_key`), a estrutura define explicitamente **10 índices** em `database/database.sql`:

| Índice | Tabela e colunas | Finalidade |
|---|---|---|
| `idx_client_status` | `client(status_id)` | Consulta por estado cadastral |
| `idx_client_type` | `client(client_type_id)` | Suporte à FK de tipo PF/PJ |
| `idx_client_status_event_history` | `client_status_event(client_id, created_at, id)` | Consulta ordenada do histórico do cliente |
| `idx_account_status` | `account(status_id)` | Consulta por estado da conta |
| `idx_account_status_event_history` | `account_status_event(account_id, created_at, id)` | Consulta ordenada do histórico da conta |
| `idx_financial_transaction_type` | `financial_transaction(transaction_type_id)` | Suporte à FK de tipo de operação |
| `idx_transaction_entry_account` | `transaction_entry(account_id)` | Extrato R08 por conta |
| `idx_transaction_entry_transaction` | `transaction_entry(transaction_id)` | Junção lançamento↔operação |
| `idx_transaction_entry_direction` | `transaction_entry(direction_id)` | Suporte à FK de direção |
| `idx_transaction_entry_entry_type` | `transaction_entry(entry_type_id)` | Suporte à FK de natureza |

> Os índices `idx_transaction_entry_account` e `idx_transaction_entry_transaction` sustentam a consulta de extrato (R08), que filtra por `account_id` e junta `financial_transaction`.

## 5. Decisões de modelagem e alternativas

As decisões abaixo priorizam **integridade transacional, clareza do domínio e simplicidade operacional** para o escopo do bootcamp. Cada alternativa representa um desenho tecnicamente possível e evidencia a razão da escolha adotada.

| Decisão adotada | Alternativa | Vantagens da escolha | Trade-off |
|---|---|---|---|
| Entidade `client` com tabelas especializadas PF/PJ | Uma única tabela com campos de ambos os perfis | Evita colunas de perfis incompatíveis e mantém dados comuns centralizados | A exclusividade do perfil exige regra de aplicação |
| Estado atual + tabela de eventos | Apenas o estado atual ou event sourcing integral | Leituras diretas do estado e rastreabilidade das transições | Estado e evento precisam ser gravados atomicamente |
| Uma conta por cliente, com `UNIQUE(client_id)` | Múltiplas contas por cliente | Regra assegurada também sob concorrência | Ampliação futura exige revisão do relacionamento |
| Saldo atual em `account` + lançamentos históricos | Recalcular o saldo a cada consulta | Consultas de saldo eficientes com histórico detalhado | Exige atualização conjunta de saldo e lançamentos |
| Operação financeira + lançamentos por conta | Uma linha isolada por transferência ou ledger contábil completo | Representa efeitos de depósito, transferência e tarifa de forma clara | Não pretende substituir um ledger bancário de partidas dobradas |
| `BIGINT` em centavos | `FLOAT` para valores monetários | Elimina imprecisões típicas de ponto flutuante | A unidade monetária é controlada pela aplicação |
| Chave idempotente persistida e única + hash da requisição | Deduplicação apenas em memória | Segurança diante de retentativas e reinicialização do serviço | Exige armazenamento durável da intenção |
| Bloqueios de linha e transações PostgreSQL | Apenas leitura e verificação prévia de saldo | Coordena movimentações concorrentes e evita atualizações perdidas | Necessita controle da ordem e duração dos bloqueios |
| Fuso IANA explícito no cadastro | Inferir fuso por localização | Interpretação previsível das datas financeiras | Requer validação do valor informado |

## 6. Especificação DBML complementar

A representação abaixo permite reproduzir o modelo em ferramentas de visualização como o `dbdiagram.io`, com os tipos, identificadores, unicidades, índices e referências adotados na estrutura do banco. O **DDL PostgreSQL em [`database/database.sql`](../database/database.sql)** permanece como especificação executável do esquema.

```dbml
// Lookups (enumerações normalizadas) — padrão (id, enumerator).
Table client_status {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'PENDING, ACTIVE, REJECTED ou INACTIVE']
}

Table client_type {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'INDIVIDUAL ou COMPANY']
}

Table transaction_type {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'DEPOSIT ou TRANSFER']
}

Table transaction_direction {
  id bigint [pk, increment, not null]
  enumerator varchar(10) [not null, unique, note: 'DEBIT ou CREDIT']
}

Table entry_type {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'PRINCIPAL ou FEE']
}

Table actor_type {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'SYSTEM ou INTERNAL']
}

Table client {
  id bigint [pk, increment, not null]
  client_key uuid [not null, unique, note: 'Identificador publico']
  client_type_id bigint [not null, note: 'FK -> client_type (antes VARCHAR client_type)']
  email varchar(254) [not null, unique, note: 'Trim + lowercase']
  timezone varchar(64) [not null, note: 'Timezone IANA de referencia do produto, informado pelo Partner Backend; D0 Brasil']
  status_id bigint [not null]
  created_at timestamptz [not null]
  updated_at timestamptz [not null]

  indexes {
    status_id [name: 'idx_client_status']
    client_type_id [name: 'idx_client_type']
  }
}

Table individual_client {
  client_id bigint [pk, not null]
  cpf varchar(11) [not null, unique, note: 'Somente digitos']
  full_name varchar(200) [not null]
  birth_date date [not null, note: 'Idade minima de 18 anos por regra do produto D0']
}

Table company_client {
  client_id bigint [pk, not null]
  cnpj varchar(14) [not null, unique, note: 'Somente digitos']
  legal_name varchar(200) [not null]
  trade_name varchar(200) [note: 'Opcional']
}

Table client_status_event {
  id bigint [pk, increment, not null]
  client_id bigint [not null]
  from_status_id bigint [note: 'NULL somente no evento inicial']
  to_status_id bigint [not null]
  actor_type_id bigint [not null, note: 'FK -> actor_type (antes VARCHAR actor_type)']
  reason varchar(500) [note: 'Obrigatorio conforme a transicao']
  created_at timestamptz [not null]

  indexes {
    (client_id, created_at, id) [name: 'idx_client_status_event_history']
  }
}

Table account_status {
  id bigint [pk, increment, not null]
  enumerator varchar(20) [not null, unique, note: 'ACTIVE, INACTIVE ou CLOSED']
}

Table account {
  id bigint [pk, increment, not null]
  account_key uuid [not null, unique, note: 'Identificador publico']
  client_id bigint [not null, unique, note: 'No maximo uma conta por cliente durante toda a vida']
  status_id bigint [not null]
  balance_cents bigint [not null, default: 0, note: 'CHECK balance_cents >= 0']
  created_at timestamptz [not null]
  updated_at timestamptz [not null]

  indexes {
    status_id [name: 'idx_account_status']
  }
}

Table account_status_event {
  id bigint [pk, increment, not null]
  account_id bigint [not null]
  from_status_id bigint [note: 'NULL somente no evento inicial']
  to_status_id bigint [not null]
  actor_type_id bigint [not null, note: 'FK -> actor_type (antes VARCHAR actor_type)']
  reason varchar(500) [note: 'Obrigatorio conforme a transicao']
  created_at timestamptz [not null]

  indexes {
    (account_id, created_at, id) [name: 'idx_account_status_event_history']
  }
}

Table financial_transaction {
  id bigint [pk, increment, not null]
  transaction_key uuid [not null, unique, note: 'Identificador publico da operacao']
  request_control_key uuid [not null, unique, note: 'UNIQUE global; identidade idempotente da intencao (Idempotency-Key)']
  request_hash char(64) [not null, note: 'SHA-256 da intencao normalizada']
  transaction_type_id bigint [not null, note: 'FK -> transaction_type (antes VARCHAR transaction_type)']
  created_at timestamptz [not null]

  indexes {
    transaction_type_id [name: 'idx_financial_transaction_type']
  }
}

Table transaction_entry {
  id bigint [pk, increment, not null]
  entry_key uuid [not null, unique, note: 'Chave publica do lancamento']
  transaction_id bigint [not null]
  account_id bigint [not null]
  direction_id bigint [not null, note: 'FK -> transaction_direction (antes VARCHAR direction)']
  entry_type_id bigint [not null, note: 'FK -> entry_type (antes VARCHAR entry_type)']
  amount_cents bigint [not null, note: 'CHECK amount_cents > 0']
  balance_after_cents bigint [not null, note: 'CHECK balance_after_cents >= 0; saldo imediatamente apos esta entry']
  created_at timestamptz [not null, note: 'Timestamp tecnico da row']

  indexes {
    account_id [name: 'idx_transaction_entry_account']
    transaction_id [name: 'idx_transaction_entry_transaction']
    direction_id [name: 'idx_transaction_entry_direction']
    entry_type_id [name: 'idx_transaction_entry_entry_type']
  }
}

Ref: client.status_id > client_status.id [delete: restrict]
Ref: client.client_type_id > client_type.id [delete: restrict]

Ref: individual_client.client_id > client.id [delete: restrict]
Ref: company_client.client_id > client.id [delete: restrict]

Ref: client_status_event.client_id > client.id [delete: restrict]
Ref: client_status_event.from_status_id > client_status.id [delete: restrict]
Ref: client_status_event.to_status_id > client_status.id [delete: restrict]
Ref: client_status_event.actor_type_id > actor_type.id [delete: restrict]

Ref: account.client_id > client.id [delete: restrict]
Ref: account.status_id > account_status.id [delete: restrict]

Ref: account_status_event.account_id > account.id [delete: restrict]
Ref: account_status_event.from_status_id > account_status.id [delete: restrict]
Ref: account_status_event.to_status_id > account_status.id [delete: restrict]
Ref: account_status_event.actor_type_id > actor_type.id [delete: restrict]

Ref: financial_transaction.transaction_type_id > transaction_type.id [delete: restrict]

Ref: transaction_entry.transaction_id > financial_transaction.id [delete: restrict]
Ref: transaction_entry.account_id > account.id [delete: restrict]
Ref: transaction_entry.direction_id > transaction_direction.id [delete: restrict]
Ref: transaction_entry.entry_type_id > entry_type.id [delete: restrict]
```
