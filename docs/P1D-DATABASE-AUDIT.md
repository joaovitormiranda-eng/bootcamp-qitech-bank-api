# P1-D — Modelagem PostgreSQL, Normalização e Migrações Seguras

Auditoria e design da fase **P1-D** sobre
`refactor/p1d-postgresql-model-integrity`, ramificada da `main` do fork
`joaovitormiranda-eng/bootcamp-qitech-bank-api` no commit `952a9c6`
(merge do PR #4). Escopo restrito a **COD-05** (chaves, identificadores e
relacionamentos) e **COD-06** (normalização de enumerações e integridade
referencial). Nenhuma refatoração fora dessa abrangência.

> Régua de avaliação: v2.13. RFC: v2.1. Documentos de apoio:
> `docs/ERD.md`, `docs/P1B-TEST-AUDIT.md`, `docs/P1C-ARCHITECTURE-AUDIT.md`.

---

## 0. Baseline verificada (pré-condições da P1-D)

| Pré-condição | Evidência | Situação |
| --- | --- | --- |
| `main` do fork atualizada | `git rev-list --left-right --count origin/main...HEAD` = `0 0` | ✅ em sincronia |
| PRs #1, #2, #3, #4 integrados | `gh api .../pulls?state=all` → todos `merged`; `git log --merges` mostra os 4 merges | ✅ integrados |
| CI verde na baseline | run `43519210228` (commit `952a9c6`), job `test` = `success` | ✅ verde |
| Suíte de 521 testes | log do passo *Run full pytest suite*: `521 passed in 20.44s` | ✅ 521/521 |
| Branch de trabalho | `refactor/p1d-postgresql-model-integrity` criada a partir de `952a9c6` | ✅ criada |

> **Nota sobre o número 521.** O comentário de cabeçalho do `ci.yml` menciona
> "442 testes" — é texto herdado de uma fase anterior. A contagem real do
> último run verde é **521 passed**, que é a baseline que a P1-D preserva.

### 0.1 Restrição de ambiente (crítica para a validação da migração)

O sandbox de desenvolvimento **não tem Docker, nem PostgreSQL, nem
`psycopg2`** (`docker info` falha; `which psql/postgres/initdb` não encontra
nada; `import psycopg2` → `ModuleNotFoundError`). A rede está em modo
`COMMON_DEPENDENCIES` (sem internet aberta). Portanto:

- O único sinal verde **autoritativo** da suíte completa (que exige dois
  clusters PostgreSQL fisicamente separados + MockServer + uvicorn vivo) é o
  **GitHub Actions CI** (`.github/workflows/ci.yml`) — exatamente como nas
  fases P1-B e P1-C.
- **Não é possível** rodar localmente o teste de migração em banco populado.
  Conforme exigido pela própria tarefa, **não alegamos** que a migração foi
  validada por execução local: ela é validada por um **job de CI dedicado e
  isolado** (`migration`), adicionado nesta fase, que preserva integralmente o
  job `test` obrigatório para a main protegida.

---

## 1. Inventário real do schema (fonte: `database/database.sql` + `src/models/`)

Dez tabelas, três domínios. Para cada uma: colunas e tipos, PK, FKs + ON
DELETE, UNIQUE, CHECK, índices e o espelho SQLAlchemy.

### 1.1 `client_status` (lookup) — linhas 1-12
- Colunas: `id BIGINT` (IDENTITY), `enumerator VARCHAR(20)`.
- PK: `id`. UNIQUE: `enumerator`. CHECK: `enumerator IN ('PENDING','ACTIVE','REJECTED','INACTIVE')`.
- Seed: 4 linhas. ORM: `models/client_status.py` (constantes `PENDING/ACTIVE/REJECTED/INACTIVE`).

### 1.2 `account_status` (lookup) — linhas 14-25
- Colunas: `id BIGINT` (IDENTITY), `enumerator VARCHAR(20)`.
- PK: `id`. UNIQUE: `enumerator`. CHECK: `enumerator IN ('ACTIVE','INACTIVE','CLOSED')`.
- Seed: 3 linhas. ORM: `models/account_status.py`.

### 1.3 `client` — linhas 27-38
- Colunas: `id BIGINT` (IDENTITY), `client_key UUID`, `client_type VARCHAR(20)`,
  `email VARCHAR(254)`, `timezone VARCHAR(64)`, `status_id BIGINT`,
  `created_at/updated_at TIMESTAMPTZ`.
- PK: `id`. UNIQUE: `client_key`, `email`.
- FK: `status_id → client_status(id) ON DELETE RESTRICT`.
- **CHECK (enum textual): `ck_client_type` → `client_type IN ('INDIVIDUAL','COMPANY')`** ⚠️ COD-06.
- Índice: `idx_client_status (status_id)`.
- ORM: `models/client.py`. Identidade pública = `client_key` (UUID).

### 1.4 `individual_client` (especialização PF) — linhas 42-47
- Colunas: `client_id BIGINT`, `cpf VARCHAR(11)`, `full_name VARCHAR(200)`, `birth_date DATE`.
- **PK: `client_id`** (também FK). UNIQUE: `cpf`.
- FK: `client_id → client(id) ON DELETE RESTRICT`.
- ORM: `models/individual_client.py`. **Não exposta como linha própria na API.**

### 1.5 `company_client` (especialização PJ) — linhas 49-54
- Colunas: `client_id BIGINT`, `cnpj VARCHAR(14)`, `legal_name VARCHAR(200)`, `trade_name VARCHAR(200) NULL`.
- **PK: `client_id`** (também FK). UNIQUE: `cnpj`.
- FK: `client_id → client(id) ON DELETE RESTRICT`.
- ORM: `models/company_client.py`. **Não exposta como linha própria na API.**

### 1.6 `client_status_event` (histórico) — linhas 56-67
- Colunas: `id BIGINT`, `client_id`, `from_status_id NULL`, `to_status_id`,
  `actor_type VARCHAR(20)`, `reason VARCHAR(500) NULL`, `created_at`.
- PK: `id`. FKs (todas RESTRICT): `client_id → client(id)`, `from_status_id → client_status(id)`, `to_status_id → client_status(id)`.
- **CHECK (enum textual): `actor_type IN ('SYSTEM','INTERNAL')`** ⚠️ COD-06.
- Índice: `idx_client_status_event_history (client_id, created_at, id)`.

### 1.7 `account` — linhas 73-85
- Colunas: `id BIGINT` (IDENTITY), `account_key UUID`, `client_id BIGINT`,
  `status_id BIGINT`, `balance_cents BIGINT DEFAULT 0`, timestamps.
- PK: `id`. UNIQUE: `account_key`, `client_id`.
- FKs (RESTRICT): `client_id → client(id)`, `status_id → account_status(id)`.
- CHECK: `balance_cents >= 0`. Índice: `idx_account_status (status_id)`.
- **`id` é a chave interna usada para ordenar locks na transferência** (RFC p.4).

### 1.8 `account_status_event` (histórico) — linhas 87-100
- Análogo a 1.6, para conta. **CHECK: `actor_type IN ('SYSTEM','INTERNAL')`** ⚠️ COD-06.
- Índice: `idx_account_status_event_history (account_id, created_at, id)`.

### 1.9 `financial_transaction` — linhas 102-111
- Colunas: `id BIGINT` (IDENTITY), `transaction_key UUID`, `request_control_key UUID`,
  `request_hash CHAR(64)`, `transaction_type VARCHAR(20)`, `created_at`.
- PK: `id`. UNIQUE: `transaction_key`, `request_control_key`.
- **CHECK (enum textual): `transaction_type IN ('DEPOSIT','TRANSFER')`** ⚠️ COD-06.
- `request_control_key` = Idempotency-Key (UNIQUE global). `request_hash` = SHA-256 da intenção.

### 1.10 `transaction_entry` (lançamentos) — linhas 113-146
- Colunas: `id BIGINT` (IDENTITY), `transaction_id`, `account_id`,
  `direction VARCHAR(10)`, `entry_type VARCHAR(20)`, `amount_cents BIGINT`,
  `balance_after_cents BIGINT`, `created_at`.
- **PK: `id`. Sem coluna `*_key` própria.** ⚠️ COD-05.
- FKs (RESTRICT): `transaction_id → financial_transaction(id)`, `account_id → account(id)`.
- **CHECK (enum textual): `direction IN ('DEBIT','CREDIT')`**, **`entry_type IN ('PRINCIPAL','FEE')`** ⚠️ COD-06.
- CHECK: `amount_cents > 0`, `balance_after_cents >= 0`.
- Índices: `idx_transaction_entry_account (account_id)`, `idx_transaction_entry_transaction (transaction_id)`.
- **A ordenação do extrato depende de `transaction_entry.id` como desempate** (`transaction_repository.list_statement_entries`).

### 1.11 Onde cada coluna enum/chave é usada (acesso por SQLAlchemy — tudo ORM, sem SQL cru em `src/`)

| Coluna | Escrita (constante usada) | Leitura / filtro | Exposição pública (DTO → campo JSON) |
| --- | --- | --- | --- |
| `client.client_type` | `client_repository.create_client` (string vinda do controller `"INDIVIDUAL"`/`"COMPANY"`) | `client_analysis_repository.get_analysis_source`, `account_repository.get_client_type`, `client_controller.get_by_key`, `services/transfer_fee` | `client_dto._base_response` → `"client_type"`; resposta de `POST /client` |
| `financial_transaction.transaction_type` | `transaction_repository.create_transaction` (`FinancialTransaction.DEPOSIT/TRANSFER`) | DTOs ramificam em `== TRANSFER` | `transaction_dto` → `"transaction_type"`; `transaction_statement_dto` → `"transaction_type"` |
| `transaction_entry.entry_type` | `transaction_repository.create_entry` (`TransactionEntry.PRINCIPAL/FEE`) | DTOs filtram entries | `transaction_statement_dto` → `"entry_type"` |
| `transaction_entry.direction` | `transaction_repository.create_entry` (`TransactionEntry.DEBIT/CREDIT`) | DTOs filtram entries | `transaction_statement_dto` → `"direction"` |
| `*_status_event.actor_type` | repositories (`SYSTEM`/`INTERNAL`) | **nunca lida/filtrada na aplicação** | **não exposta** |
| `individual/company_client` (linha) | `client_repository.create_individual/company_client` | joins internos | **só atributos escalares** (`cpf`, `cnpj`, …); nunca a chave da linha |
| `transaction_entry` (linha) | `transaction_repository.create_entry` | ordenação do extrato por `id` | **nenhuma chave da entry é emitida**; identidade pública = `transaction_key` do pai |

---

## 2. Diagnóstico COD-05 — Integridade das chaves

Régua v2.13, COD-05 (3/6): aponta `individual_client`, `company_client`
(PK `client_id`, sem `*_key`) e `transaction_entry` (sem `*_key`).

### 2.1 `transaction_entry` — **DIVERGÊNCIA REAL → corrigir (aditivo)**

1. **Redundância/inconsistência:** `client`, `account` e `financial_transaction`
   possuem o par `id BIGINT` (interno) + `*_key UUID` (público). `transaction_entry`
   é a única entidade de primeira classe do domínio **sem** chave pública própria
   — quebra o padrão do esquema.
2. **Por que melhora:** adicionar `entry_key UUID UNIQUE` dá à linha um
   identificador público estável e determinístico (gerado pela aplicação),
   padronizando o esquema **sem** tocar na chave interna `id`. O `id` BIGINT
   continua sendo a PK — preserva FKs, a relação `FinancialTransaction.entries`
   (`order_by TransactionEntry.id`) e **toda a ordenação determinística do
   extrato** (que desempata por `transaction_entry.id`).
3. **Afetados:** `database.sql` (+coluna, +UNIQUE); `models/transaction_entry.py`
   (+coluna); `transaction_repository.create_entry` (gera `uuid4()`); o teste de
   contrato `test_financial_schema.py` (passa a esperar a coluna + UNIQUE);
   `builders.insert_entry` (passa a inserir `entry_key`). **Nenhuma FK, índice de
   ordenação, lock ou consulta de saldo muda.**
4. **Preservação de identidade:** o `id` interno permanece; o `entry_key`
   é **novo** (não substitui nada). Registros históricos ganham a chave via
   backfill determinístico na migração.
5. **R01–R10:** aditivo e não exposto por padrão nos contratos atuais; nenhum
   payload muda. Compatível.

**Decisão: implementar `transaction_entry.entry_key`.**

### 2.2 `individual_client` / `company_client` — **AUDITADO: PRESERVAR (desenho já correto)**

A régua sugere "adicionar `id` PK + `*_key` + manter `client_id` como FK
UNIQUE". Aplicar isso literalmente **piora** o modelo. Evidências:

1. **`client_id` como PK já é estritamente mais forte** que "FK UNIQUE": uma PK é
   `NOT NULL` + `UNIQUE` e é o vínculo 1:1 natural da especialização
   (*class-table inheritance*). Trocar a PK por um `id` surrogate e rebaixar
   `client_id` para "FK UNIQUE" **não adiciona integridade** — apenas introduz
   uma coluna redundante e uma segunda restrição para recuperar a garantia 1:1
   que a PK atual já fornece de graça.
2. **Identidade pública:** a RFC (p.3) e `docs/ERD.md` definem `client_id PK,FK`
   para ambas as tabelas. A identidade pública de um cliente é **sempre**
   `client.client_key` (UUID). **Não existe** rota, DTO ou payload que exponha
   um perfil PF/PJ como recurso próprio — `GET /client/{client_key}` devolve os
   atributos escalares (`cpf`, `cnpj`, …) embutidos na resposta do cliente.
   Inventar `individual_client_key`/`company_client_key` criaria um **segundo
   identificador público para a mesma entidade lógica**, violando o próprio
   enunciado da P1-D ("não introduza mudanças de identidade pública, nem
   substitua um UUID exposto por um BIGINT interno") e divergindo da RFC fiel
   (RFC-01 = 50/50).
3. **Enunciado da P1-D (literal):** *"individual_client e company_client já
   utilizam client_id como chave primária e estrangeira… Não recrie esses
   mecanismos sem uma divergência efetiva."* Não há divergência efetiva: o
   desenho é o padrão canônico de especialização 1:1.

**Decisão: preservar. Registrar COD-05 destas duas tabelas como auditado, com
evidência, sem alteração cosmética.** (Enquadra-se explicitamente no
"preserve o desenho correto" da tarefa.)

### 2.3 `client` / `account` / `financial_transaction` / status events — já conformes
Todas têm `id` interno + chave pública UUID onde aplicável (`client_key`,
`account_key`, `transaction_key`) e FKs por `id`. Nada a fazer. `ACCOUNT.id`
preservado como chave de ordenação de locks (invariante financeira).

---

## 3. Diagnóstico COD-06 — Enumerações e tabelas de lookup

Régua v2.13, COD-06 (2/5): `client.client_type`,
`financial_transaction.transaction_type`, `transaction_entry.entry_type`
usam `VARCHAR + CHECK IN` sem FK. A seção 5 da P1-D lista ainda
`transaction_entry.direction`, `client_status_event.actor_type` e
`account_status_event.actor_type`.

Padrão de referência já aprovado no repo (COD-07 ✅): `client_status` /
`account_status` = `(id BIGINT PK, enumerator VARCHAR UNIQUE)` + FK por `id`.
A P1-D replica **exatamente** esse padrão para os enums restantes.

| Enum textual | Valores (determinísticos) | Tabela de lookup nova | Coluna FK nova | Exposto na API? |
| --- | --- | --- | --- | --- |
| `client.client_type` | INDIVIDUAL, COMPANY | `client_type` | `client.client_type_id` | sim (texto) |
| `financial_transaction.transaction_type` | DEPOSIT, TRANSFER | `transaction_type` | `financial_transaction.transaction_type_id` | sim (texto) |
| `transaction_entry.entry_type` | PRINCIPAL, FEE | `entry_type` | `transaction_entry.entry_type_id` | sim (texto) |
| `transaction_entry.direction` | DEBIT, CREDIT | `transaction_direction` | `transaction_entry.direction_id` | sim (texto) |
| `client_status_event.actor_type` + `account_status_event.actor_type` | SYSTEM, INTERNAL | `actor_type` (compartilhada) | `*_status_event.actor_type_id` | não |

Para cada enum: (1) já existe tabela equivalente? Não, exceto o padrão de
status. (2) Valores e orientação: domínio fechado e estável, definido pela RFC
e pelos CHECKs atuais. (3) Deve existir lookup? Sim — é a correção direta do
COD-06 e alinha com o padrão de status já aprovado. (4) Criada com PK + UNIQUE
+ seed determinístico. (5) FK + backfill por `enumerator`. (6) ORM, repositories
e testes atualizados. (7) **Representação textual externa preservada.**

### 3.1 Preservação do contrato textual externo (requisito RFC)

A RFC exige `client_type`, `transaction_type`, `entry_type` e `direction` como
**strings** nas respostas. Para não vazar `*_id` nem quebrar os DTOs:

- Cada modelo ORM ganha a coluna FK `*_id`, um `relationship` para o lookup e
  uma **property Python de leitura** que devolve `self.<rel>.enumerator`
  (ex.: `Client.client_type` continua retornando `"INDIVIDUAL"`).
- Os **repositories** resolvem `texto → linha de lookup` na inserção
  (helper com cache por sessão), idêntico ao que já fazem com `status`.
- Resultado: **controllers, DTOs e `services/transfer_fee` ficam inalterados**;
  a superfície de mudança é `database.sql`, os modelos e 3 repositories.

### 3.2 `actor_type` — por que uma única tabela compartilhada

`SYSTEM`/`INTERNAL` são os mesmos valores em `client_status_event` e
`account_status_event`, nunca lidos pela aplicação (só escritos). Uma lookup
`actor_type` compartilhada evita duplicar a mesma dimensão em duas tabelas e
mantém a integridade por FK nos dois históricos. Semântica e transições
**inalteradas**.

### 3.3 Mudança de código de erro de CHECK para FK (consequência esperada)

Hoje um valor inválido gera **`23514`** (CHECK violation). Com FK, passa a gerar
**`23503`** (FK violation). Isso é a *prova* da normalização e será refletido —
de forma controlada e explícita — nos testes de contrato
(`test_rejects_unknown_*`). O domínio fechado (conjunto de valores aceitos)
**não muda**; apenas o mecanismo de imposição (CHECK → FK) muda.

---

## 4. Matriz de impacto (arquivos afetados × achado)

| Arquivo | COD-05 (entry_key) | COD-06 (lookups) | Tipo de mudança |
| --- | --- | --- | --- |
| `database/database.sql` | +`entry_key UUID UNIQUE` | +5 tabelas lookup, +seeds, troca CHECK→FK | schema alvo |
| `database/migrations/0001_*.sql` (novo) | backfill `entry_key` | cria lookups, FKs, backfill, dropa CHECKs | migração versionada |
| `src/models/transaction_entry.py` | +coluna + property | +`direction_id`/`entry_type_id` + rels + props | ORM |
| `src/models/client.py` | — | +`client_type_id` + rel + prop | ORM |
| `src/models/financial_transaction.py` | — | +`transaction_type_id` + rel + prop | ORM |
| `src/models/client_status_event.py` | — | +`actor_type_id` + rel + prop | ORM |
| `src/models/account_status_event.py` | — | +`actor_type_id` + rel + prop | ORM |
| `src/models/{client_type,transaction_type,entry_type,transaction_direction,actor_type}.py` (novos) | — | modelos de lookup | ORM |
| `src/repositories/transaction_repository.py` | gera `entry_key` | resolve texto→id | repo |
| `src/repositories/client_repository.py` | — | resolve `client_type`/`actor_type` | repo |
| `src/repositories/account_repository.py` | — | resolve `actor_type` | repo |
| `tests/integration/database/test_schema_bootstrap.py` | — | +5 tabelas em `ERD_TABLES` | contrato |
| `tests/integration/database/test_financial_schema.py` | +coluna/UNIQUE `entry_key`; CHECK→FK | CHECK→FK (23514→23503) | contrato |
| `tests/integration/database/test_client_schema.py` | — | CHECK→FK; novas lookups | contrato |
| `tests/integration/database/test_account_schema.py` | — | CHECK→FK (actor_type) | contrato |
| `tests/integration/database/builders.py` | insere `entry_key` | insere `*_id` ou resolve enumerator | suporte |
| `tests/integration/database/test_lookup_tables.py` (novo) | — | consistência das lookups | contrato novo |
| `tests/integration/database/test_populated_migration.py` (novo) | valida backfill `entry_key` | valida backfill + identidade | migração |
| `.github/workflows/ci.yml` | — | +job `migration` isolado | CI |

**Preservado sem alteração:** `individual_client`, `company_client` (desenho
correto, §2.2); todos os controllers; todos os DTOs; `services/transfer_fee`;
`src/database.py`; `tests/utils/db_utils.py` (DROP SCHEMA só no cluster `_test`).

---

## 5. Schema alvo (resumo das mudanças)

Aditivas e de normalização, sobre o `database.sql` atual:

1. **5 tabelas de lookup** no padrão `(id BIGINT IDENTITY PK, enumerator VARCHAR UNIQUE)`
   com seed determinístico: `client_type`, `transaction_type`, `entry_type`,
   `transaction_direction`, `actor_type`.
2. **`client.client_type` → `client.client_type_id BIGINT NOT NULL REFERENCES client_type(id)`**
   (remove `ck_client_type`).
3. **`financial_transaction.transaction_type` → `transaction_type_id … REFERENCES transaction_type(id)`**.
4. **`transaction_entry`:** `direction → direction_id`, `entry_type → entry_type_id`
   (FKs), e **+`entry_key UUID NOT NULL UNIQUE`**.
5. **`client_status_event.actor_type` / `account_status_event.actor_type` → `actor_type_id … REFERENCES actor_type(id)`**.
6. CHECKs de valor textual (`amount_cents > 0`, `balance_after_cents >= 0`,
   `balance_cents >= 0`) **mantidos** — não são enumerações.

Os valores semânticos dos estados e as transições permitidas **não mudam**.
Nenhum valor é adicionado ou removido do domínio.

---

## 6. Diagrama ER — antes / depois (recorte do que muda)

### Antes (enum textual + entry sem chave)
```
client(.., client_type VARCHAR CHECK IN('INDIVIDUAL','COMPANY'), ..)
financial_transaction(.., transaction_type VARCHAR CHECK IN('DEPOSIT','TRANSFER'), ..)
transaction_entry(id PK, .., direction VARCHAR CHECK, entry_type VARCHAR CHECK, ..)   -- sem *_key
client_status_event(.., actor_type VARCHAR CHECK IN('SYSTEM','INTERNAL'), ..)
account_status_event(.., actor_type VARCHAR CHECK IN('SYSTEM','INTERNAL'), ..)
```

### Depois (lookups + FK + entry_key)
```
client_type(id PK, enumerator UK)            <-- client.client_type_id FK
transaction_type(id PK, enumerator UK)       <-- financial_transaction.transaction_type_id FK
entry_type(id PK, enumerator UK)             <-- transaction_entry.entry_type_id FK
transaction_direction(id PK, enumerator UK)  <-- transaction_entry.direction_id FK
actor_type(id PK, enumerator UK)             <-- client_status_event.actor_type_id FK
                                             <-- account_status_event.actor_type_id FK
transaction_entry(id PK, entry_key UUID UK, .., direction_id FK, entry_type_id FK, ..)
```
`individual_client` / `company_client` **inalteradas** (`client_id PK,FK`).
`account.id`, `client_key`, `account_key`, `transaction_key` **inalterados**.

---

## 7. Estratégia de migração em banco populado (ver `database/migrations/`)

Como o esquema é bootstrapado a partir de `database/database.sql` (sem Alembic),
a migração é um **script SQL versionado idempotente**
`database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql` que leva um banco
**já populado** (schema antigo) ao schema alvo, com:

- **Pré-condições:** verifica existência das colunas antigas; aborta cedo se já
  migrado (idempotência — evita duplicar lookups se reexecutado).
- **Backfill seguro:** cria lookups e popula FKs a partir do texto existente;
  `entry_key` recebe `gen_random_uuid()` por linha.
- **Validação pós-migração:** nenhuma FK nula; contagem de linhas preservada;
  `entry_key` único e total; valores de lookup sem duplicata.
- **Falha explícita:** `ON_ERROR_STOP`, tudo em transação única → `ROLLBACK`
  total em erro; dados inválidos param a migração em vez de perder silenciosamente.
- **Rollback / recuperação:** documentado em
  `database/migrations/0001_ROLLBACK.sql` + estratégia de backup
  (`pg_dump` antes; restore do dump em falha). Ver §9.

A migração é testada por `tests/integration/database/test_populated_migration.py`
em um **banco efêmero dedicado** com registros representativos de PF/PJ, contas,
saldos, históricos, depósitos, transferências, lançamentos e chaves de
idempotência, comparando contagem, identidade, valores monetários, hashes e
relacionamentos **antes e depois**. Executado no job de CI `migration`,
fisicamente isolado do job `test`.

---

## 8. Invariantes financeiras preservadas

Nenhuma invariante da seção 8 da P1-D é tocada: dinheiro em centavos; tarifas
PF/PJ; HALF_UP; Idempotency-Key/`request_control_key` UNIQUE + hash SHA-256;
replay sem duplicidade; conflito por reutilização incompatível; **ordenação de
locks por `ACCOUNT.id` crescente** (a PK `account.id` é preservada);
transferências atômicas; saldo não negativo (CHECK mantido); COMMIT/rollback do
pós-P1-C; históricos; ordenação determinística dos lançamentos (desempate por
`transaction_entry.id`, preservado); timezone; contratos R01–R10; MockServer.

---

## 9. Plano de recuperação / rollback e pré-condições

Detalhado em `database/migrations/`. Resumo:
- **Pré-condição obrigatória:** `pg_dump` completo antes de aplicar a migração
  em qualquer ambiente não-efêmero.
- **Rollback estrutural:** `0001_ROLLBACK.sql` recria as colunas textuais a
  partir das FKs (lossless, pois o `enumerator` é o mesmo texto) e remove as
  lookups/`entry_key`. Preferência, porém, é **restaurar do backup** quando
  houver qualquer dúvida de integridade.
- **Nunca** `DROP SCHEMA` como estratégia de migração; `DROP SCHEMA` só no
  cluster `_test` efêmero (guarda `_test` em `db_utils.reset_schema`).

---

## 10. Risco residual e pendências (preenchido na FASE F)

Ver seção final após validação de CI.
