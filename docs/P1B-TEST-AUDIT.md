# P1-B — Auditoria e classificação dos testes (black-box, isolamento, MockServer)

Branch: `refactor/p1b-test-isolation-mockserver`
Escopo: qualidade de teste **somente** (COD-04 black-box, COD-08 sem import de `src/`, COD-13 conector exercitado via MockServer real, COD-14 sem acesso ao banco fora de rollback). Sem mudança em `src/`, `database/database.sql`, tabelas/enums/chaves ou CI.

> **Nota de conformidade:** este documento **não** reivindica conformidade total. As porcentagens exatas por critério (fração de testes *coletados*) são autoritativas apenas quando medidas pelo avaliador contra a mesma stack viva. Docker está quebrado neste sandbox (`could not find a working conmon binary`), portanto o run verde autoritativo é o **GitHub Actions CI** (`.github/workflows/ci.yml`), que provisiona `postgres_api` (5432), `postgres_test` (5433), `mockserver` (1080), carrega `database/database.sql`, sobe `uvicorn app:app` e roda `python -m pytest -q`. Localmente só foram validados: lint (flake8), byte-compile e `pytest --collect-only` (coleta sem erro, contagem preservada). As deltas abaixo são medidas **a nível de arquivo** com `grep`, que é determinístico e não depende da stack.

---

## 1. Baseline da banca (v2.13, commit 53269c1) e método de medição

Baseline de avaliação informado pela banca (fração de testes conformes / total avaliado):

| Critério | Descrição | Baseline banca v2.13 |
|----------|-----------|----------------------|
| COD-04 | Testes exercitam a API exclusivamente via HTTP (black-box) | **197 / 272** |
| COD-08 | Testes não importam módulos de `src/` | **104 / 110** |
| COD-13 | Conector externo testado via gravação de requisição no MockServer real | **0 / 1** |
| COD-14 | Testes não acessam o banco fora de rollback | **67 / 109** |

**Método de medição do "depois"** (branch atual):

1. Classificação **a nível de arquivo** (determinística, independente da stack) usando as regras da seção 2 e os `grep` da seção 7 (Evidências).
2. Reconciliação de contagem com `pytest --collect-only -q`, observando que **parametrização e classes inflam a contagem coletada** acima do número de linhas `def test_` (ex.: `test_r08_statement_validation.py` tem 8 linhas `def test_` mas coleta 34 casos).
3. Comparação do estado atual contra o commit base de P1-B `3166b72` (merge de P1-A) via `git grep` no commit base.

Baseline de coleta (commit `3166b72`, P1-A merged): **503** testes coletados, 0 erros de coleta.
Estado atual do branch: **506** testes coletados, 0 erros de coleta.
Delta de coleta: **+3** = os três testes novos de COD-13 em `tests/integration/client/r03/test_provider_call_recording.py`. Nenhum teste foi deletado. A suíte de transação coleta **134** antes e depois.

---

## 2. Regras de classificação (aplicadas neste documento)

Cada arquivo sob `tests/` que contém `def test_` recebe exatamente uma categoria, por prioridade:

- **(a) BLACK-BOX** — dirige a API apenas via `ClientRequisition`/HTTP e **nunca** importa `src/` **nem** executa SQL/SQLAlchemy (nem usa fixture de engine, nem helper de suporte com SQL).
- **(b) IMPORTS-SRC** — tem import de topo de um módulo de `src/` (`controllers`, `repositories`, `models`, `connectors`, `dtos`, `errors`, `middlewares`, `database`, `constants`, `resources`, `app`).
- **(c) DB-ACCESS** — usa `sqlalchemy`/`text()`/`exec_driver_sql`/`create_engine`, uma fixture de engine (`api_database_engine`/`app_db_engine`) ou um helper de suporte apoiado em SQL (`create_account`/`read_*_state`/`set_account_status`).
- **(d) LEGITIMATE-INTERNAL** — é teste de função pura (unit), teste de schema/persistência, teste de concorrência/atomicidade, ou teste de infra/observabilidade, onde o acesso interno (import de `src/` e/ou SQL) é **justificado**. Um arquivo IMPORTS-SRC ou DB-ACCESS é simultaneamente marcado LEGITIMATE-INTERNAL quando o acesso interno é inerente ao que o teste verifica.

**Regra crítica (não inflar):** um teste que usa o banco por necessidade real (schema, timezone com linhas back-dated, atomicidade por fault-injection, concorrência/locks, boundary de overflow inatingível pela API pública) **não** é reclassificado artificialmente como black-box. Nenhuma asserção foi enfraquecida, nenhum `skip`/`xfail` foi adicionado para subir porcentagem.

---

## 3. Matriz por arquivo

Legenda de colunas: **N** = `grep -c 'def test_'` (linhas de teste); **HTTP-only** = dirige a API só via HTTP; **src** = importa `src/`; **db** = acessa banco (SQLAlchemy/engine/helper-SQL); **Categoria** conforme seção 2.

Todos os arquivos sob `tests/` que contêm `def test_` (63 arquivos):

| Arquivo | N | HTTP-only | src | db | Categoria | Justificativa (uma linha) |
|---------|---|-----------|-----|----|-----------|--------------------------|
| integration/client/r01/test_authentication.py | 2 | sim | não | não | BLACK-BOX | Autenticação do R01 via HTTP. |
| integration/client/r01/test_documents.py | 6 | sim | não | não | BLACK-BOX | Validação de CPF/CNPJ via HTTP. |
| integration/client/r01/test_domain_rules.py | 5 | sim | não | não | BLACK-BOX | Regras de domínio do cadastro via HTTP. |
| integration/client/r01/test_payload_validation.py | 13 | sim | não | não | BLACK-BOX | Validação de payload via HTTP. |
| integration/client/r01/test_persistence.py | 4 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Persistência do cliente: verifica linha gravada (sem projeção HTTP). |
| integration/client/r01/test_success.py | 8 | sim | não | não | BLACK-BOX | Caminho feliz do R01 via HTTP. |
| integration/client/r01/test_uniqueness_and_normalization.py | 6 | sim | não | não | BLACK-BOX | Unicidade/normalização via HTTP. |
| integration/client/r02/test_errors.py | 6 | sim | não | não | BLACK-BOX | Erros do R02 via HTTP. |
| integration/client/r02/test_statuses.py | 1 | não | não | sim | DB-ACCESS | Usa fixture de engine para preparar estado. |
| integration/client/r02/test_success.py | 3 | sim | não | não | BLACK-BOX | Caminho feliz do R02 via HTTP. |
| integration/client/r03/test_decisions.py | 2 | não | não | sim | DB-ACCESS | Decisão APPROVE/REJECT com verificação de estado no banco. |
| integration/client/r03/test_eligibility.py | 4 | não | não | sim | DB-ACCESS | Elegibilidade com setup/verify no banco. |
| integration/client/r03/test_provider_call_recording.py | 3 | sim | não | não | BLACK-BOX (COD-13) | **NOVO (FEAT-002):** chama rota real e confere gravação no MockServer. |
| integration/client/r03/test_provider_contract.py | 3 | não | não | sim | DB-ACCESS | Contrato do provedor + verificação de estado. |
| integration/client/r03/test_transaction_safety.py | 2 | não | não | sim | DB-ACCESS | Atomicidade da análise (estado no banco). |
| integration/client/r04/test_atomicity.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Atomicidade de abertura de conta via banco. |
| integration/client/r04/test_business_rules.py | 4 | não | não | sim | DB-ACCESS | Regras de negócio com setup/verify no banco. |
| integration/client/r04/test_concurrency.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Concorrência/locks de abertura (precisa de banco). |
| integration/client/r04/test_success.py | 3 | não | não | sim | DB-ACCESS | Sucesso do R04 com verificação de linhas. |
| integration/client/r04/test_validation.py | 4 | não | não | sim | DB-ACCESS | Validação do R04 com fixture de engine. |
| integration/client/r05/test_errors.py | 3 | sim | não | não | BLACK-BOX | Erros do R05 (GET conta) via HTTP. |
| integration/client/r05/test_read_only.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Invariante "leitura não muta estado" (snapshot no banco). |
| integration/client/r05/test_snapshots.py | 3 | não | não | sim | DB-ACCESS | Snapshot de conta comparado ao banco. |
| integration/client/r06/test_atomicity.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Atomicidade de transição de status. |
| integration/client/r06/test_business_rules.py | 4 | não | não | sim | DB-ACCESS | Regras de transição com verificação no banco. |
| integration/client/r06/test_concurrency.py | 2 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Concorrência de transições (locks). |
| integration/client/r06/test_transitions.py | 5 | não | não | sim | DB-ACCESS | Eventos de transição verificados no banco. |
| integration/client/r06/test_validation.py | 5 | sim | não | não | BLACK-BOX | Validação de payload do R06 via HTTP. |
| integration/client/r09/test_atomicity.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Atomicidade do R09. |
| integration/client/r09/test_business_rules.py | 3 | não | não | sim | DB-ACCESS | Regras do R09 verificadas no banco. |
| integration/client/r09/test_concurrency.py | 4 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Concorrência do R09 (locks). |
| integration/client/r09/test_transitions.py | 4 | não | não | sim | DB-ACCESS | Transições/eventos do R09 no banco. |
| integration/client/r09/test_validation.py | 5 | sim | não | não | BLACK-BOX | Validação do R09 via HTTP. |
| integration/contracts/test_error_envelope.py | 9 | sim | não | não | BLACK-BOX | Envelope de erro (referência P1-A) via HTTP. |
| integration/contracts/test_route_contracts.py | 13 | sim | não | não | BLACK-BOX | Contratos de rota (referência P1-A) via HTTP. |
| integration/database/test_account_schema.py | 16 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Teste de schema (constraints/colunas). |
| integration/database/test_client_schema.py | 24 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Teste de schema de cliente. |
| integration/database/test_database_timeout_observability.py | 1 | não | sim | sim | IMPORTS-SRC + DB / LEGITIMATE-INTERNAL | Observabilidade de timeout do banco (precisa de acesso interno). |
| integration/database/test_database_timeouts.py | 3 | não | sim | sim | IMPORTS-SRC + DB / LEGITIMATE-INTERNAL | Timeouts de banco (precisa de acesso interno). |
| integration/database/test_financial_schema.py | 11 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Teste de schema financeiro. |
| integration/database/test_schema_bootstrap.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Bootstrap/reset de schema. |
| integration/test_healthcheck.py | 9 | sim | não | não | BLACK-BOX | Healthcheck via HTTP. |
| integration/test_observability.py | 5 | não | sim | sim | IMPORTS-SRC + DB / LEGITIMATE-INTERNAL | Observabilidade (logs/contexto) com acesso interno justificado. |
| integration/transaction/r07_safety/test_atomicity.py | 4 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Atomicidade por fault-injection (precisa de banco). |
| integration/transaction/r07_safety/test_history.py | 1 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Histórico financeiro por fault-injection. |
| integration/transaction/test_r07_deposit_errors.py | 6 | não | não | sim | DB-ACCESS (parcial) | 2/6 black-box; SQL mantido p/ overflow/INACTIVE/CLOSED/conta inexistente. |
| integration/transaction/test_r07_deposit.py | 5 | não | não | sim | DB-ACCESS (parcial) | Prep via API; SQL só p/ ler `request_hash` SHA-256 (sem projeção HTTP). |
| integration/transaction/test_r07_financial_concurrency.py | 2 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Concorrência financeira (locks). |
| integration/transaction/test_r07_idempotency_concurrency.py | 2 | não | não | sim | DB-ACCESS / LEGITIMATE-INTERNAL | Concorrência de idempotência (locks). |
| integration/transaction/test_r07_transfer_errors.py | 12 | não | não | sim | DB-ACCESS (parcial) | 7/12 black-box; SQL mantido p/ overflow/INACTIVE/CLOSED/conta None. |
| integration/transaction/test_r07_transfer_fee.py | 2 | não | não | sim | DB-ACCESS (parcial) | **Convertido (FEAT-003), ajustado no fix `08dbec1`:** verificação via R07/R08/R05; SQL só p/ semear saldo inicial da origem (abertura sem lançamento visível, sem projeção HTTP). |
| integration/transaction/test_r07_transfer_idempotency.py | 3 | não | não | sim | DB-ACCESS (parcial) | **Convertido (FEAT-003), ajustado no fix `08dbec1`:** replay/conflito via R05+R08; SQL só p/ semear saldo inicial da origem. |
| integration/transaction/test_r07_transfer.py | 1 | não | não | sim | DB-ACCESS (parcial) | Prep via API; SQL p/ `request_hash` SHA-256 do TRANSFER + sanity de setup (`client_type`/`client_id` sem projeção HTTP) + semear saldo da origem. |
| integration/transaction/test_r07_validation.py | 4 | sim | não | não | BLACK-BOX | Validação do R07 via HTTP (já black-box antes de P1-B). |
| integration/transaction/test_r08_statement_basic.py | 6 | sim | não | não | BLACK-BOX | **Convertido (FEAT-003):** INACTIVE/CLOSED via R06; verify via R08. |
| integration/transaction/test_r08_statement_dates.py | 8 | não | não | sim | DB-ACCESS (parcial) | SQL p/ timezone do cliente e `created_at` back-dated (persistência/timezone). |
| integration/transaction/test_r08_statement_entries.py | 4 | não | não | sim | DB-ACCESS (parcial) | SQL só p/ back-datar `transaction_entry.created_at` (persistência). |
| integration/transaction/test_r08_statement_ordering.py | 3 | não | não | sim | DB-ACCESS (parcial) | SQL p/ back-datar timestamps e empate por id (sem projeção HTTP). |
| integration/transaction/test_r08_statement_pagination.py | 4 | não | não | sim | DB-ACCESS (parcial) | SQL só p/ invariante "read não muta" (snapshot). |
| integration/transaction/test_r08_statement_validation.py | 8 | sim | não | não | BLACK-BOX | **Convertido (FEAT-003):** validação de query/empty via API. |
| unit/test_analysis_provider_initialization.py | 1 | não | sim | não | IMPORTS-SRC / LEGITIMATE-INTERNAL | Unit de inicialização do provedor (importa `src/`). |
| unit/test_transaction_fee.py | 2 | não | sim | não | IMPORTS-SRC / LEGITIMATE-INTERNAL | Unit de função pura de taxa (importa `src/`). |
| unit/test_transaction_hash.py | 10 | não | sim | não | IMPORTS-SRC / LEGITIMATE-INTERNAL | Unit de função pura de hash (importa `src/`). |

> **Reconciliação coleta vs grep:** a coluna N conta linhas `def test_`; `pytest --collect-only` reporta mais casos onde há parametrização. Exemplos: `test_r08_statement_validation.py` N=8 → 34 coletados; `test_r07_transfer_fee.py` N=2 → 12 coletados; `contracts/test_route_contracts.py` N=13 → 47 coletados. Soma de N = 302 linhas `def test_` (`grep -rc 'def test_' tests --include=*.py`); total coletado = 506 casos.

---

## 4. Resumo antes/depois (nível de arquivo)

Contagem de arquivos (`def test_`) por classificação, medida com `grep` no commit base `3166b72` e no branch atual:

| Métrica (arquivos) | Antes (`3166b72`) | Depois (branch) | Delta | Origem da delta |
|--------------------|-------------------|-----------------|-------|-----------------|
| Total de arquivos com `def test_` | 62 | 63 | +1 | FEAT-002 (novo módulo COD-13) |
| Black-box (HTTP-only: nem `src` nem DB) | 15 | 18 | +3 | +1 FEAT-002, +2 FEAT-003 |
| Importam `src/` | 5 | 5 | 0 | — (nenhum teste novo importa `src/`) |
| Acessam banco (SQLAlchemy/engine/helper-SQL) | 45 | 43 | −2 | FEAT-003 (conversão R08) |

Os **2 arquivos que deixaram de acessar o banco** (DB-ACCESS → BLACK-BOX) por FEAT-003:
`test_r08_statement_basic.py`, `test_r08_statement_validation.py`.

> **Nota de reconciliação (fix `08dbec1`):** a revisão semântica (v1) apontou que a conversão inicial de `test_r07_transfer_fee.py`, `test_r07_transfer_idempotency.py` e `test_r08_statement_{entries,ordering,pagination}.py` quebrava asserções de forma determinística, porque o helper `open_funded_account_via_api(balance_cents>0)` financia a conta com um DEPOSIT **visível** no extrato, enquanto o antigo `create_account` definia o saldo de abertura **sem** lançamento. O fix reverteu **apenas a semeadura do saldo de abertura da conta de origem** para SQL (fixture legítima de forma de extrato, inatingível pela API pública sem um lançamento visível), mantendo targets preparados via API e todas as asserções intactas. Em consequência, `test_r07_transfer_fee.py` e `test_r07_transfer_idempotency.py` voltaram a ser DB-ACCESS (parcial) a nível de arquivo. O ganho líquido black-box a nível de arquivo é **+3** (não +5): o módulo COD-13 novo mais os dois arquivos de statement acima. O restante da conversão COD-04/COD-14 permanece como redução do SQL ao mínimo justificado dentro de cada arquivo.

Mapeamento para os critérios da banca (leitura a nível de arquivo; **as porcentagens exatas por teste coletado são CI-autoritativas**):

| Critério | Antes (banca v2.13) | Movimento em P1-B | Evidência |
|----------|---------------------|-------------------|-----------|
| **COD-04** (black-box) | 197/272 | **+3 arquivos** passaram a dirigir a API só via HTTP (15→18 arquivos black-box), além de redução do SQL ao mínimo justificado em vários arquivos R07/R08. As conversões preservam toda asserção (taxa PF 0,50% min50 max1000 / PJ 1,00% min100 max1500 / HALF_UP; replay idempotente; validação de statement). | §3, §4, FEAT-003 |
| **COD-08** (sem import de `src/`) | 104/110 | **0 arquivos adicionados** importando `src/`; permanece exatamente 5 arquivos, todos legítimos (seção 5). | §7 grep COD-08 |
| **COD-13** (MockServer real) | **0/1** | **0/1 → 1/1**: novo `test_provider_call_recording.py` com 3 testes que gravam a chamada real `POST /v1/client-analysis`. | §6, FEAT-002 |
| **COD-14** (sem banco fora de rollback) | 67/109 | **−2 arquivos** deixaram de acessar o banco (45→43 arquivos com DB); vários outros tiveram o SQL reduzido ao mínimo (parciais na seção 6). | §4, §6, FEAT-003 |

> As deltas acima são **a nível de arquivo** e determinísticas. A tradução para a fração exata de *testes coletados* que a banca pontua depende de rodar a stack viva; por Docker estar indisponível no sandbox, **o run verde autoritativo é o GitHub Actions CI**. Não reivindicamos conformidade total.

---

## 5. Acesso interno preservado (justificado)

Estes arquivos mantêm, por necessidade legítima, import de `src/` e/ou SQL; não devem ser convertidos:

**Unit de função pura (importam `src/` — COD-08 legítimo):**
- `tests/unit/test_transaction_fee.py` — testa a função pura de cálculo de taxa; import de `src/` é o próprio objeto de teste.
- `tests/unit/test_transaction_hash.py` — testa a função pura de hash canônico SHA-256; idem.
- `tests/unit/test_analysis_provider_initialization.py` — valida a inicialização do provedor a partir do arquivo de config; precisa importar `src/`.

**Infra/observabilidade (importam `src/` e usam banco):**
- `tests/integration/test_observability.py` — logs/contexto de requisição exigem inspeção interna.
- `tests/integration/database/test_database_timeout_observability.py`, `tests/integration/database/test_database_timeouts.py` — comportamento de timeout do pool/driver só é observável internamente.

**Schema/persistência (usam SQL — COD-14 legítimo):**
- `tests/integration/database/*` (`test_account_schema.py`, `test_client_schema.py`, `test_financial_schema.py`, `test_schema_bootstrap.py`) — verificam constraints/colunas/enums diretamente no schema; é o objeto de teste.

**Atomicidade por fault-injection (usam SQL):**
- `tests/integration/transaction/r07_safety/test_atomicity.py`, `tests/integration/transaction/r07_safety/test_history.py` — injetam falha para provar COMMIT/rollback tudo-ou-nada; inobservável por HTTP.

**Concorrência/locks (usam SQL):**
- `tests/integration/transaction/test_r07_financial_concurrency.py`, `tests/integration/transaction/test_r07_idempotency_concurrency.py` — exercitam locks/corridas concorrentes; precisam de acesso direto ao banco.
- Análogos em `r04/test_concurrency.py`, `r06/test_concurrency.py`, `r09/test_concurrency.py`.

---

## 6. Pendências (diferido para a próxima rodada)

Testes de comportamento que **ainda** usam SQL direto e **não** foram convertidos nesta rodada, com o motivo (risco/ausência de projeção HTTP). Listados explicitamente para não reivindicar conformidade não demonstrada:

**R07/R08 parcialmente convertidos — SQL mínimo retido (setup de conta já migrado para API):**
- `test_r07_deposit.py`, `test_r07_transfer.py` — uma leitura READ-ONLY de `financial_transaction.request_hash` para asserção do SHA-256 canônico; **não há projeção HTTP** desse campo.
- `test_r07_deposit_errors.py` (4/6 ainda com SQL), `test_r07_transfer_errors.py` (5/12 ainda com SQL) — pré-estados INACTIVE/CLOSED, saldo near-overflow (`BIGINT_MAX`) e casos de conta inexistente **inatingíveis pela API pública** (R04 sempre abre conta ACTIVE; depósitos reais não alcançam o near-overflow).
- `test_r08_statement_entries.py`, `test_r08_statement_ordering.py`, `test_r08_statement_dates.py` — back-dating de `created_at` e timezone do cliente (ex.: America/Manaus); a API não permite definir timestamps históricos/colidentes. Casos legítimos de persistência/timezone.
- `test_r08_statement_pagination.py` — snapshot antes/depois para provar que a leitura do extrato não muta estado financeiro.

**Setup de estado por banco ainda não migrado para API (risco/tamanho):**
- `tests/integration/client/r04/*`, `r06/*`, `r09/*` (regras de negócio/transições com `support/` apoiado em SQL) — conversão de alto risco; adiada.
- `tests/integration/client/r03/test_decisions.py`, `test_eligibility.py`, `test_provider_contract.py`, `test_transaction_safety.py` — asserções de verificação de estado no banco (R03 DB-verify) sem projeção HTTP equivalente completa.
- `tests/integration/client/r01/test_persistence.py`, `r02/test_statuses.py`, `r05/test_snapshots.py`, `r05/test_read_only.py` — verificação de persistência/invariância diretamente no banco.

Esses itens permanecem DB-ACCESS **por decisão consciente**, não por omissão; convertê-los exigiria ou enfraquecer asserções (inaceitável) ou capacidades que a API pública não expõe.

---

## 7. Evidências

Comandos executados no branch `refactor/p1b-test-isolation-mockserver` (reproduzíveis).

### COD-08 — arquivos de teste que importam `src/` (antes == depois: 5)

```
$ grep -rlnE "^(from|import) (controllers|repositories|models|connectors|dtos|errors|middlewares|database|constants|resources|app)\b" \
    $(grep -rln "def test_" tests --include=*.py) | sort
tests/integration/database/test_database_timeout_observability.py
tests/integration/database/test_database_timeouts.py
tests/integration/test_observability.py
tests/unit/test_transaction_fee.py
tests/unit/test_transaction_hash.py
```

Os 5 são todos LEGITIMATE-INTERNAL (seção 5). P1-B **não** adicionou nenhum teste novo que importe `src/`. A contagem é idêntica no commit base `3166b72` (verificado com `git grep` no commit base).

### COD-14 — arquivos de teste com acesso a banco (antes 45 → depois 41)

```
$ grep -rlnE "sqlalchemy|text\(|exec_driver_sql|create_engine|api_database_engine|app_db_engine" \
    $(grep -rln "def test_" tests --include=*.py) | sort | wc -l
43
```

Diferença contra o commit base `3166b72` (arquivos que deixaram de acessar o banco):

```
tests/integration/transaction/test_r08_statement_basic.py
tests/integration/transaction/test_r08_statement_validation.py
```

Conjunto black-box (nem `src` nem banco) subiu de **15** (base) para **18** (branch): os 2 acima + o módulo novo de COD-13. `test_r07_transfer_fee.py` e `test_r07_transfer_idempotency.py` foram inicialmente convertidos a black-box, mas o fix `08dbec1` (pós-revisão v1) reverteu a semeadura do saldo de abertura da origem para SQL, pois o financiamento por API deixa um lançamento visível no extrato que quebrava asserções de forma determinística; permanecem DB-ACCESS (parcial) a nível de arquivo, com asserções preservadas.

### COD-13 — chamada real ao provedor comprovada via MockServer (0/1 → 1/1)

Arquivo novo: `tests/integration/client/r03/test_provider_call_recording.py` (3 testes independentes).

Fluxo de cada teste:
1. `MockServer.reset()` e cria cliente PENDING único (via rota R01).
2. Configura expectativa no MockServer e dirige a **rota HTTP real** `POST /client/{client_key}/analysis` (via `ClientRequisition`, sem mock Python), o que faz a API chamar o provedor em `POST /v1/client-analysis` (conector `src/connectors/client_analysis_connector.py`).
3. Assere status + contrato da resposta da Bank API.
4. Chama `MockServer.retrieve_recorded_requests({"method": "POST", "path": "/v1/client-analysis"})` — que emite `PUT {MOCKSERVER_URL}/mockserver/retrieve?type=REQUESTS&format=JSON` (helper adicionado em `tests/utils/mockserver.py`, FEAT-001) — e assere **exatamente uma** requisição gravada, com `method == "POST"`, `path == "/v1/client-analysis"` e corpo JSON `== {"client_key", "client_type", "document"}`.

Casos cobertos:
- `test_approve_records_real_provider_call` — APPROVE → `{"status": "ACTIVE"}`; corpo `{client_key, "INDIVIDUAL", normalized_cpf}`.
- `test_reject_records_real_provider_call` — REJECT → `{"status": "REJECTED"}`; corpo `{client_key, "COMPANY", normalized_cnpj}`.
- `test_provider_failure_still_records_real_provider_call` — provedor 500 → resposta 500 `code == "QIT000500"`, e **mesmo assim** uma chamada real `POST /v1/client-analysis` foi gravada (prova que a saída HTTP ocorreu).

Sem mock Python do provedor: o MockServer real é usado ponta-a-ponta.

### Coleta (determinística, não exige stack)

```
$ .venv/bin/python -m pytest --collect-only -q 2>&1 | tail -1
506 tests collected in 0.83s

$ .venv/bin/python -m pytest --collect-only -q tests/integration/transaction 2>&1 | tail -1
134 tests collected in 0.04s
```

Base `3166b72`: 503 coletados. Branch: 506 (+3 = testes de COD-13). Transação: 134 antes e depois. Nenhum teste deletado.

### Nota sobre o run verde autoritativo

Docker está quebrado neste sandbox (`could not find a working conmon binary`), portanto a suíte completa **não** roda localmente (exige API viva + dois clusters PostgreSQL + MockServer). O run verde autoritativo é o **GitHub Actions CI** (`.github/workflows/ci.yml`): provisiona os serviços, carrega `database/database.sql`, sobe `uvicorn app:app` e roda `python -m pytest -q -ra`. Localmente foram validados apenas: `py_compile`, `flake8` (max-line-length 140) e `pytest --collect-only`.

---

## 8. Arquivos adicionados/modificados em P1-B (resumo)

| Commit | Arquivo | Natureza |
|--------|---------|----------|
| `a42b424` | `tests/utils/mockserver.py` | **modificado** — novo helper `retrieve_recorded_requests` (COD-13). |
| `b7753b4` | `tests/integration/client/r03/test_provider_call_recording.py` | **adicionado** — 3 testes COD-13 (MockServer real). |
| `eebb21a` | `tests/integration/transaction/support.py` + testes R07/R08 | **modificado** — helpers API-only; conversão fee/deposit/transfer/idempotency/statement (COD-04/14). |
| `7e32789` | `test_r08_statement_validation.py`, `test_r07_deposit_errors.py`, `test_r07_transfer_errors.py` | **modificado** — conversão de validação de statement e caminhos de erro R07 (COD-04/14). |
| `08dbec1` | `test_r07_transfer_fee.py`, `test_r07_transfer_idempotency.py`, `test_r07_transfer.py`, `test_r07_deposit.py`, `test_r08_statement_{entries,ordering,pagination}.py` | **modificado** — fix pós-revisão v1: reverte semeadura de saldo de abertura da origem para SQL e restaura invariantes `updated_at`/`client_type` sem enfraquecer asserções. |
| (este) | `docs/P1B-TEST-AUDIT.md` | **adicionado/atualizado** — esta auditoria, reconciliada com o fix `08dbec1`. |

Nenhum teste removido. Sem mudança em `src/`, `database/database.sql`, tabelas/enums/chaves, CI (`.github/workflows/ci.yml`), `tests/utils/db_utils.py` (isolamento de dois clusters e guarda de `DROP SCHEMA` só em `*_test` intactos). Semântica RFC v2.1 (taxas PF/PJ, idempotência+SHA-256, locks/concorrência, COMMIT/rollback/saldo não-negativo, estados/eventos, extratos/timezone, contrato R03) preservada.
