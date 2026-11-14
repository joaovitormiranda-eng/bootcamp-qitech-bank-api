# P1 - Auditoria Consolidada e Independente (QI Tech Bank API)

> Auditoria final da fase **P1**, cobrindo toda a evolução das etapas
> **P0, P1-A, P1-B, P1-C e P1-D**, confrontada com a **avaliação oficial
> v2.13** (commit avaliado `53269c1`) e a **RFC v2.1** (12/10/2026).
>
> **Rodada somente de leitura e relatório.** Nenhum arquivo de `src/`,
> teste, `database/database.sql`, migração ou workflow de CI foi alterado.
> O único arquivo produzido é este documento.
>
> Baseline auditada: `main` @ `f57ca8f` (merge do PR #5, P1-D).
> Sinal verde autoritativo da suíte completa: GitHub Actions
> [run 43549391873](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43549391873)
> (jobs `test` e `migration` = `success`).

---

## Convenção de evidência (lida em todo o documento)

Cada afirmação técnica é marcada por **como** foi apurada. Isto é um
requisito explícito da auditoria (seção 2 da tarefa) e vale para todas as
seções:

- **[CI]** - comportamento atestado **apenas** por execução verde do
  GitHub Actions citado. A suíte completa exige dois clusters PostgreSQL
  físicos, MockServer e uvicorn vivo; **não** é executável localmente neste
  ambiente (sem `psql`/`postgres`/`initdb`, sem `psycopg2`, rede
  `COMMON_DEPENDENCIES`). O CI é a única prova verde da suíte inteira.
- **[EXEC-LOCAL]** - comportamento que **esta auditoria executou** no host
  (testes puros que não exigem banco).
- **[INSPEÇÃO]** - comportamento verificado por **leitura** de código, SQL,
  configuração ou histórico git, sem execução.

Nenhuma nota oficial de reavaliação é inventada neste documento. A nota
`0,0/10` e a matriz de critérios abaixo são as **da banca v2.13 sobre o
commit `53269c1`**, usadas como linha de base; esta auditoria não atribui
nota nova.

---

## 1. Resumo executivo

A avaliação oficial v2.13 eliminou o projeto em **COD-01** (a suíte não
subia: 13 falhas + 200 erros, 229/442), zerando a nota (`0,0/10`) apesar de
`ESC-01` atendido e de uma nota parcial citada de `6,9/10`. As etapas P0→P1-D
atacaram exatamente a cadeia de bloqueio apontada pela banca ("comece pelo
COD-01, depois COD-14 e COD-04") e o restante dos critérios estruturais
(COD-02, COD-05, COD-06, COD-09, COD-11, COD-13).

Estado atual, confrontado com a baseline da banca:

- **COD-01 - comprovadamente resolvido [CI].** A suíte sobe e passa inteira:
  `544 passed in 26.52s`, 0 falhas / 0 erros / 0 skips, no run
  `43549391873` (commit `f57ca8f`). É a inversão direta do bloqueio que
  eliminou o projeto.
- **COD-02, COD-06, COD-07, COD-09, COD-11, COD-12, COD-13 -
  comprovadamente resolvidos** por mudança estrutural verificável no código/SQL
  **[INSPEÇÃO]** e atestados em verde pelo CI **[CI]**.
- **COD-05 - parcialmente resolvido.** `transaction_entry` ganhou sua chave
  pública `entry_key` e está **resolvida**; porém `individual_client` e
  `company_client` **ainda divergem** da interpretação literal da régua
  (mantêm `client_id` como PK/FK, sem `id` surrogado separado nem `*_key`
  público). Por isso o critério fica **PARCIAL**, não integralmente resolvido:
  é resolução por decisão de engenharia em uma tabela e divergência consciente
  (documentada) nas duas especializações PF/PJ.
- **COD-04, COD-08, COD-14 - parcialmente resolvidos.** Houve progresso real e
  honesto (conversão de testes para black-box, mínimo de SQL retido), mas a
  **fração exata por teste coletado** que a banca pontua só é mensurável
  rodando a stack viva. O repositório, com razão, **não reivindica
  conformidade total** nesses três; permanecem exceções legítimas e
  documentadas (unit de função pura, schema, concorrência, fault-injection).
  Em COD-08 há um ponto adicional: a P1-C **acrescentou** testes novos que
  importam módulos internos de `src` (os unit de fronteira de camada), de modo
  que o critério não pode ser lido como uniformemente melhorado pela P1-B.
- **COD-03, COD-10 - permaneciam "não verificáveis" para a banca**; aqui são
  reavaliados por inspeção como **majoritariamente atendidos**, mas a fração
  por teste continua CI/avaliador-dependente.
- **ESC-01, RFC-01 - mantidos.** Escopo mínimo entregue; RFC fiel. Das quatro
  "omissões" observadas pela banca, o balanço honesto é **uma resolvida, uma
  parcialmente documentada e duas pendentes**: (1) rotas `sample_entity`
  removidas e cobertas por teste → **resolvida**; (2) índices
  `idx_transaction_entry_account/transaction` citados em
  `docs/P1D-DATABASE-AUDIT.md §1.10` mas **ainda ausentes do diagrama do
  `docs/ERD.md`** → **parcialmente documentada**; (3) erros-base `QIT0000xx`
  declarados e não citados na RFC → **pendente**; (4) `BankSlipConnector`
  exportado embora boletos estejam fora de escopo → **pendente**.

**Veredito de maior valor / menor risco:** a maior criação de valor já foi
entregue (COD-01 verde). A próxima mudança de **maior valor e menor risco**
é **documental e de testes**, não de produção: (a) alinhar os comentários
"442 testes" do `ci.yml` e do README ao número real (544), e (b) fechar as
pendências de documentação da RFC-01. Em seguida, elevar formalmente
COD-04/08/14 convertendo alvos de baixo risco. Detalhes na seção 5 e 6.

> **Ressalva honesta e central.** A separação [CI] × [EXEC-LOCAL] ×
> [INSPEÇÃO] não é formalidade: o único ponto que **esta auditoria executou
> de fato** foram os invariantes puros de tarifa (6 testes, seção 3.2).
> Tudo o que depende de banco/HTTP é **[CI]** - herdado de um run verde que
> confio porque reli o `ci.yml` e confirmei que o passo decisório é
> `pytest -q -ra` sem `continue-on-error`, sem `--maxfail` e sem
> skip/xfail artificiais. Não há como esta auditoria, neste ambiente,
> reproduzir a suíte inteira.

---

## 2. Matriz completa - avaliação original (v2.13) × estado atual

Colunas por critério: **Diagnóstico original da banca · Alterações P0→P1-D ·
Evidência atual (arquivo/método/teste/CI) · Status · Riscos/pendências.**
Status possíveis: **RESOLVIDO** (comprovado), **PARCIAL**, **NÃO RESOLVIDO**,
**NÃO VERIFICÁVEL**. Nenhum critério de evidência parcial é marcado como
integralmente resolvido.

### COD-01 - Sobe e testes passam
- **Banca:** ❌ 229/442. Pytest vermelho: 13 falhas, 200 erros.
- **P0→P1-D:** P0 (`fix/p0-test-suite-reproducibility`, PR #1) tornou a suíte
  reprodutível e provisionou a stack completa no CI (`ci.yml`: dois Postgres
  físicos em 5432/5433, MockServer 8.0.0, uvicorn vivo aguardado por
  `/health_check=204`). Fases seguintes preservaram o verde.
- **Evidência:** [CI] run `43549391873`, job `test` = `success`, passo *Run
  full pytest suite* → **`544 passed in 26.52s`** (0 falhas/erros/skips).
  [INSPEÇÃO] `ci.yml` usa `pytest -q -ra --junitxml` como único portão, sem
  `continue-on-error`/`--maxfail`.
- **Status:** **RESOLVIDO.**
- **Riscos:** verde é por-run, não garantia de ambiente; local é
  irreproduzível aqui. O comentário-cabeçalho do `ci.yml` ("442 testes") está
  **desatualizado** (hoje são 544) - é dívida de documentação, não de função.

### ESC-01 - Escopo mínimo entregue
- **Banca:** ✅ 5/5.
- **P0→P1-D:** escopo das 10 rotas R01–R10 preservado.
- **Evidência:** [INSPEÇÃO] `src/app.py` registra exatamente R01–R10 e `/`.
- **Status:** **RESOLVIDO (mantido).**

### COD-02 - Toda rota testada com 2xx
- **Banca:** ❌ 11/16. 5 rotas `sample_entity` sem teste (`src/app.py:146–166`).
- **P0→P1-D:** as rotas de demonstração `SampleEntity` foram **removidas** do
  registro de rotas.
- **Evidência:** [INSPEÇÃO] `src/app.py` não registra nenhuma rota
  `sample_entity` (só R01–R10). [CI] `tests/integration/contracts/test_route_contracts.py::TestNotFound::test_removed_demo_routes_are_gone`
  dirige `POST/GET/PUT/PATCH /sample_entity[...]` e assere **404 `QIT000404`**,
  provando que não restou handler vivo.
- **Status:** **RESOLVIDO.**
- **Riscos:** nenhum relevante; a remoção é coberta por teste de contrato.

### COD-03 - Todo erro de domínio testado
- **Banca:** ⏸ 14/19 - não verificável.
- **P0→P1-D:** suíte de erros de domínio ampliada (R01–R09 têm módulos
  `test_errors`/`test_validation`/`test_business_rules`).
- **Evidência:** [INSPEÇÃO] erros de domínio concentrados em `src/errors/`
  (`client_errors.py`, `account_errors.py`, `transaction_errors.py`) com
  testes por rota. [CI] exercitados no run verde.
- **Status:** **PARCIAL / majoritariamente atendido** - a fração exata
  (erros cobertos / erros declarados) exige o método do avaliador; não é
  afirmável como 19/19 aqui.
- **Riscos:** possíveis erros de domínio sem teste dedicado; medir cobertura
  de erro formalmente na P2.

### COD-04 - Só testes de integração black-box
- **Banca:** ❌ 197/272. `tests/unit/*` e testes que importam app sem HTTP
  (timeouts, observability, healthcheck:59, fee, hash, analysis-init, client_schema via TestClient).
- **P0→P1-D (P1-B):** conversão de alvos R07/R08 para dirigir a API só via
  HTTP; redução do SQL ao mínimo justificado; +3 arquivos black-box a nível
  de arquivo (15→18). Ver `docs/P1B-TEST-AUDIT.md §3–§4`.
- **Evidência:** [INSPEÇÃO] `test_r08_statement_basic.py` e
  `test_r08_statement_validation.py` passaram a HTTP-only; muitos R07/R08
  mantêm SQL **mínimo** só para fixtures inatingíveis via API (back-dating de
  `created_at`, saldo near-overflow, pré-estados INACTIVE/CLOSED). [CI]
  verde no run citado.
- **Status:** **PARCIAL.** Progresso real; a fração por teste coletado é
  CI/avaliador-autoritativa. O próprio `docs/P1B-TEST-AUDIT.md §1,§4,§6`
  **não reivindica conformidade total** - avaliação honesta e correta.
- **Riscos:** vários testes de comportamento ainda usam banco por necessidade
  legítima; conversão adicional é de médio/alto risco (seção 6).

### COD-05 - Entidade com `id` e `*_key`
- **Banca:** ❌ 3/6. `individual_client`/`company_client` (PK `client_id`, sem
  `*_key`); `transaction_entry` sem `*_key`.
- **P0→P1-D (P1-D):** adicionada `transaction_entry.entry_key UUID NOT NULL
  UNIQUE` (chave pública), preservando `id` BIGINT como PK (locks/ordenação
  do extrato intactos). `individual_client`/`company_client` **preservadas**
  por decisão fundamentada (`client_id` PK+FK já é o padrão 1:1 canônico; ver
  `docs/P1D-DATABASE-AUDIT.md §2.2`).
- **Evidência:** [INSPEÇÃO] `database/database.sql` - `transaction_entry`
  (linhas ~190–215) tem `entry_key UUID NOT NULL UNIQUE`; `individual_client`
  e `company_client` mantêm `client_id BIGINT PRIMARY KEY REFERENCES
  client(id)`. [CI] `tests/integration/database/test_financial_schema.py` e o
  job `migration` (backfill de `entry_key` único/total) verdes.
- **Status:** **PARCIAL.** **RESOLVIDO para `transaction_entry`** (ganhou
  `entry_key` público); **divergente da régua literal para
  `individual_client`/`company_client`**, que mantêm `client_id` PK/FK sem
  `id` surrogado separado nem `*_key` público (divergência consciente e
  documentada). Como duas das três tabelas não seguem a interpretação literal
  da régua, o critério **não** é marcado como integralmente resolvido.
- **Riscos:** se a banca exigir o padrão literal `id`+`*_key` nas tabelas de
  especialização, a divergência está documentada, mas **contará como não
  atendida pela régua literal**. É o principal ponto em que "resolvido por
  decisão de engenharia" ≠ "resolvido pela régua".

### COD-06 - Enum com tabela auxiliar
- **Banca:** ❌ 2/5. `client.client_type`, `financial_transaction.transaction_type`,
  `transaction_entry.entry_type` em `varchar+CHECK IN` sem FK.
- **P0→P1-D (P1-D):** criadas 5 lookups `(id, enumerator UK)` -
  `client_type`, `transaction_type`, `transaction_direction`, `entry_type`,
  `actor_type` - e trocados os CHECK textuais por FKs (`*_id`), inclusive em
  `direction` e nos dois `*_status_event.actor_type`. Representação textual
  externa preservada por property ORM.
- **Evidência:** [INSPEÇÃO] `database/database.sql`: as 5 lookups com seed e as
  colunas `client.client_type_id`, `financial_transaction.transaction_type_id`,
  `transaction_entry.direction_id/entry_type_id`,
  `*_status_event.actor_type_id`, todas `REFERENCES ... ON DELETE RESTRICT`.
  [CI] `test_lookup_tables.py`, `test_*_schema.py` (CHECK 23514 → FK 23503) e o
  job `migration` verdes.
- **Status:** **RESOLVIDO** (os 3 enums apontados + 3 adicionais normalizados).
- **Riscos:** resolução de lookup dentro da janela de lock adiciona
  round-trips (impacto desprezível; tabelas-semente minúsculas, seção 3.6).

### COD-07 - Status em `*_status_event`
- **Banca:** ✅ 2/2.
- **Evidência:** [INSPEÇÃO] `client_status_event`/`account_status_event`
  existem com `from/to_status_id` e `actor_type_id`.
- **Status:** **RESOLVIDO (mantido e reforçado)** - `actor_type` agora é FK.

### COD-08 - Testes não importam `src`
- **Banca:** ❌ 104/110. 6 arquivos importam `src` (timeouts, observability,
  healthcheck:77-78, fee, hash).
- **P0→P1-D - resultado da P1-B ≠ mudança posterior da P1-C:** na **P1-B** o
  conjunto que importava `src` foi mantido pequeno e justificado (função pura +
  observabilidade/timeout que exigem introspecção interna), sem crescimento.
  Porém a **P1-C acrescentou testes novos que importam módulos internos de
  `src`**: `tests/unit/test_services_layer_boundary.py` (commit `b15972a`,
  `test(p1c): add COD-09 services-boundary unit tests ...`) importa
  `controllers.transaction_controller`, `services.transaction_hash` e
  `services.transfer_fee`. Ou seja, o critério **não** melhorou de forma
  uniforme: a P1-B conteve, a P1-C introduziu novos imports internos por
  design (teste de fronteira de camada).
- **Evidência:** [INSPEÇÃO] importam `src`: `tests/unit/test_transaction_fee.py`,
  `test_transaction_hash.py`, `test_transfer_fee_invariants.py`,
  `test_analysis_provider_initialization.py`,
  `test_services_layer_boundary.py` (COD-09, **adicionado na P1-C**),
  `tests/integration/test_observability.py`,
  `tests/integration/database/test_database_timeouts.py`,
  `test_database_timeout_observability.py`. [INSPEÇÃO] `git log` do arquivo de
  fronteira confirma origem na P1-C (`b15972a`); seu cabeçalho de imports puxa
  `controllers.*` e `services.*`.
- **Status:** **PARCIAL.** Os imports de `src` que restam são exceções válidas
  (unidade de função pura e de fronteira de camada), mas a P1-C **adicionou**
  imports internos novos; por isso o critério continua **parcial**, não
  integralmente resolvido. A régua pontua por fração de teste; não afirmável
  como 110/110.
- **Riscos:** nenhum de produção; é classificação de teste. A leitura honesta
  é que a fronteira de camada (COD-09) e o critério "não importar `src`"
  (COD-08) têm uma tensão deliberada: o teste que prova COD-09 importa `src`.

### COD-09 - Sem chamada entre camadas irmãs
- **Banca:** ❌ 19/20. `transaction_controller` importava
  `controllers/transaction_fee` e `controllers/transaction_hash` (irmãos).
- **P0→P1-D (P1-C):** fee e hash **extraídos** para `src/services/`
  (`transfer_fee.py`, `transaction_hash.py`); os módulos antigos em
  `controllers/` foram **removidos**.
- **Evidência (separada por método, sem atribuir execução local ao teste de
  fronteira):**
  - **[INSPEÇÃO]** o refactor que moveu fee/hash de `controllers/` para
    `src/services/` e o grafo de imports: `src/controllers/transaction_controller.py:9-13`
    importa `from services.transfer_fee import calculate_transfer_fee_cents` e
    `from services.transaction_hash import ...`; o teste
    `tests/unit/test_services_layer_boundary.py` assere que
    `controllers.transaction_fee`/`controllers.transaction_hash` **não existem
    mais** (`ModuleNotFoundError`) e que o controller resolve as funções a
    partir de `services.*`.
  - **[CI]** o run verde `43549391873` inclui esse teste de fronteira (job
    `test`). **Esta auditoria NÃO executou `test_services_layer_boundary.py`
    localmente** - ele importa `controllers`, que puxa `psycopg2`, ausente
    neste ambiente. O único teste executado localmente nesta rodada foi
    `tests/unit/test_transfer_fee_invariants.py` (§3.2), que não cobre esta
    fronteira. Não há, portanto, tag [EXEC-LOCAL] para COD-09.
- **Status:** **RESOLVIDO** (por [INSPEÇÃO] do refactor/grafo de imports +
  [CI] verde; sem prova de execução local do teste de fronteira).

### COD-10 - Rotas REST no singular
- **Banca:** ⏸ 12/14 - não verificável.
- **Evidência:** [INSPEÇÃO] `src/app.py` - rotas no singular (`/client`,
  `/account`, `/client/{client_key}/account`), com exceção dos **coletivos
  legítimos** `/client/{client_key}/analysis` e o extrato
  `/account/{account_key}/transactions` (lista, plural intencional per RFC/ROTAS).
- **Status:** **PARCIAL / majoritariamente atendido** - convenção seguida; a
  pontuação por rota é do avaliador.

### COD-11 - Commit só no fim do controller
- **Banca:** ❌ 4/9. `transaction_controller.py:371` fazia commit em método
  privado `_commit_and_build_response`.
- **P0→P1-D (P1-C):** o `self.session.commit()` foi movido para o método
  **público** `create()`, tornando o commit o **limite explícito** da operação;
  os fluxos privados `_create_deposit`/`_create_transfer` apenas preparam e
  devolvem a `transaction_key`, e o commit acontece uma vez no topo.
- **Evidência:** [INSPEÇÃO] `src/controllers/transaction_controller.py`:
  `create()` contém `self.session.commit()` logo antes de
  `self._build_response(...)`; não há commit nos métodos privados. [CI]
  `tests/integration/transaction/r07_safety/test_commit_boundary.py` verde.
- **Status:** **RESOLVIDO.**

### COD-12 - Rota não-GET com JSON schema
- **Banca:** ✅ 6/6.
- **Evidência:** [INSPEÇÃO] validação por `jsonschema` nos DTOs/resources das
  rotas POST/PATCH.
- **Status:** **RESOLVIDO (mantido).**

### COD-13 - Connector testado via MockServer
- **Banca:** ❌ 0/1. `client_analysis_connector.py:16` `POST /v1/client-analysis`
  sem teste que consulte o MockServer.
- **P0→P1-D (P1-B):** adicionado `tests/integration/client/r03/test_provider_call_recording.py`
  (3 testes) que dirige a **rota HTTP real** e depois consulta o MockServer
  (`retrieve_recorded_requests`) para provar que a chamada
  `POST /v1/client-analysis` saiu - inclusive no caminho de falha 500.
- **Evidência:** [INSPEÇÃO] o teste confere `method/path` e o corpo
  `{client_key, client_type, document}` gravados; o connector
  (`src/connectors/client_analysis_connector.py`) faz o POST para
  `/v1/client-analysis`. [CI] verde.
- **Status:** **RESOLVIDO.**

### COD-14 - Testes não acessam o banco (fora de rollback)
- **Banca:** ❌ 67/109. 42 arquivos acessam o banco fora de rollback
  (create_engine/connect/exec_driver_sql/SQL literal) em r01–r03.
- **P0→P1-D (P1-B):** −2 arquivos deixaram de acessar o banco (45→43 a nível
  de arquivo) e vários tiveram o SQL reduzido ao mínimo. Mantidos por
  necessidade legítima: schema, timezone/back-dating, atomicidade por
  fault-injection, concorrência/locks, overflow inatingível pela API.
- **Evidência:** [INSPEÇÃO] `docs/P1B-TEST-AUDIT.md §4,§6,§7` lista o delta e
  as pendências explicitamente; `tests/utils/db_utils.py` mantém a guarda de
  `DROP SCHEMA` só em bancos `*_test`. [CI] verde.
- **Status:** **PARCIAL.** Progresso real e honesto; a fração por teste é
  CI/avaliador-autoritativa, **não reivindicada como total**.
- **Riscos:** acesso direto ao banco em muitos testes de comportamento. É o
  critério com maior superfície remanescente (seção 6).

### RFC-01 - RFC fiel à implementação
- **Banca:** ✅ 50/50, com 4 omissões fora da contagem.
- **Estado das 4 omissões (1 resolvida · 1 parcial · 2 pendentes):**
  1. **Rotas `sample_entity` registradas e não citadas** → **RESOLVIDA**:
     rotas removidas e cobertas por teste (COD-02). [INSPEÇÃO] `src/app.py`
     não registra `sample_entity`.
  2. **Índices `idx_transaction_entry_account/transaction` ausentes do
     diagrama** → **PARCIALMENTE DOCUMENTADA**: existem em
     `database/database.sql` e estão descritos em
     `docs/P1D-DATABASE-AUDIT.md §1.10`, mas o bloco `Table transaction_entry`
     do `docs/ERD.md` **não tem seção `indexes {}`** e a tabela de índices do
     ERD **não os lista**. Ainda pendente no próprio diagrama.
  3. **Erros-base `QIT0000xx` declarados e não citados na RFC** → **PENDENTE**.
     [INSPEÇÃO] `src/errors/base_error.py` define `QIT000405/500/404/001/002/010`;
     não constam da RFC.
  4. **`BankSlipConnector` exportado embora boletos estejam fora de escopo** →
     **PENDENTE**. [INSPEÇÃO] `src/connectors/__init__.py:1` ainda exporta
     `BankSlipConnector`; `.env.example` mantém `BANKSLIP_API_*`.
- **Status:** **RESOLVIDO (50/50) com 1 omissão resolvida, 1 parcial e 2
  pendentes documentais.** A contagem fora da nota é: 1 fechada, 1 parcial
  (item 2, falta o diagrama do ERD), 2 abertas (itens 3 e 4).

---

## 3. Auditoria de regressões (R01–R10) e integridade financeira

Diferenciação explícita **[CI]** (atestado por run verde) × **[EXEC-LOCAL]**
(executado nesta auditoria) × **[INSPEÇÃO]** (lido).

### 3.1 Idempotência e hashes SHA-256 - [INSPEÇÃO] + [CI]
`src/services/transaction_hash.py` canonicaliza a intenção
(`DEPOSIT|{account_key}|{amount}` e `TRANSFER|{src}|{dst}|{amount}`) e aplica
`sha256(...).hexdigest()` determinístico. `transaction_controller.create()`
persiste `request_control_key` (Idempotency-Key, UNIQUE global) + `request_hash`;
replay com mesma chave + mesma intenção devolve a transação original
(`_get_existing_response`), e mesma chave + intenção diferente levanta
`IdempotencyKeyConflict` (409). Corrida de inserção é tratada por
`IntegrityError` → rollback → re-leitura do vencedor. **[INSPEÇÃO]** do fluxo;
**[CI]** `test_r07_transfer_idempotency.py`, `test_r07_idempotency_concurrency.py`.

### 3.2 Tarifas PF/PJ e HALF_UP - [EXEC-LOCAL] ✅
`src/services/transfer_fee.py`: PF `rate_bps=50, min=50, max=1000`; PJ
`rate_bps=100, min=100, max=1500`; HALF_UP por `(amount*bps + 5000)//10000`,
depois piso/teto. **Esta auditoria executou** `tests/unit/test_transfer_fee_invariants.py`
→ **`6 passed`**, cobrindo piso logo abaixo do limiar, teto em valor grande e
borda exata de .5 cent (PF 20_300→102, PJ 20_150→202). É o único ponto com
prova de execução **local** desta rodada.

### 3.3 Atomicidade financeira, rollback e locks - [INSPEÇÃO] + [CI]
`_create_transfer` ordena locks por `ACCOUNT.id` crescente
(`get_by_ids_for_update(sorted(...))`) - invariante anti-deadlock preservada
mesmo após a normalização (a PK `account.id` não mudou). Débito principal +
tarifa na origem, crédito no destino, saldo revalidado sob lock
(`InsufficientBalance` → 422 antes de persistir) e **um único** `commit()` no
método público (COD-11). **[CI]** `r07_safety/test_atomicity.py`,
`test_r07_financial_concurrency.py`.

### 3.4 Estados e históricos - [INSPEÇÃO] + [CI]
`*_status_event` registram `from/to_status_id` + `actor_type_id`; transições e
semântica inalteradas pela P1-D (só o mecanismo CHECK→FK mudou). **[CI]**
`r06/*`, `r09/*` (transitions/atomicity/concurrency).

### 3.5 Extratos, paginação e timezone - [INSPEÇÃO] + [CI]
`get_statement` interpreta `date_from/date_to` no timezone cadastrado
(`ZoneInfo`), converte para UTC, pagina com `limit+1` (`next_page`), ordena de
forma determinística com desempate por `transaction_entry.id` (PK preservada).
Formato inválido → `InvalidSchema` (400); `date_from > date_to` →
`InvalidTransactionDateRange` (422). **[CI]** `test_r08_statement_*`.

### 3.6 Integração com MockServer - [INSPEÇÃO] + [CI]
Ver COD-13. O connector real chama `POST /v1/client-analysis`; o teste
consulta o MockServer para provar a saída, inclusive no caminho 500.

### 3.7 Modelo PostgreSQL, chaves, FKs, lookups - [INSPEÇÃO] + [CI]
Ver COD-05/06. `database/database.sql` tem 15 tabelas (10 de domínio + 5
lookups), FKs `ON DELETE RESTRICT`, `entry_key` público, índices de FK.
**[CI]** `test_schema_bootstrap.py`, `test_lookup_tables.py`.

### 3.8 Migração populada e recuperação de dados - [INSPEÇÃO] + [CI], **nunca [EXEC-LOCAL]**
`database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql`: transação
única, `pgcrypto` para `gen_random_uuid()`, pré-condições, backfill
texto→FK sem perda, `entry_key` por linha, validação pós-migração com
`RAISE EXCEPTION` (FK nula/entry_key duplicado/lookup duplicada), idempotente
(`IF NOT EXISTS` + `ON CONFLICT DO NOTHING`). Rollback estrutural em
`0001_ROLLBACK.sql`; schema legado de partida em
`tests/integration/database/legacy_schema.sql`. **Validação exclusivamente por
[CI]** no job `migration` (cluster dedicado, porta 5434): snapshots BEFORE/AFTER
idênticos, idempotência confirmada e rollback preservando dados. Esta auditoria
**não** executou a migração (sem Postgres local) - coerente com o que o
`docs/P1D-DATABASE-AUDIT.md §0.1,§10` já declara.

### 3.9 Resumo da distinção testado × inspecionado
- **[EXEC-LOCAL] (executado aqui):** apenas os invariantes puros de tarifa
  (6 testes, §3.2). O teste de fronteira de camada (COD-09,
  `test_services_layer_boundary.py`) **não** foi executado localmente - importa
  `controllers`/`psycopg2`; seu verde vem do CI.
- **[CI] (atestado pelo run 43549391873):** toda a suíte de integração R01–R10,
  schema, concorrência, idempotência, atomicidade e o job de migração populada.
- **[INSPEÇÃO] (lido, não executado):** SQL do schema e da migração, fluxo de
  locks/commit, canonicalização de hash, contratos de rota, exportações.

---

## 4. Qualidade técnica (avaliação crítica)

### 4.1 Organização de módulos e dependências - bom, com assimetria
Separação clara `resources → controllers → repositories/models`, com
`services/` puro (fee/hash) e `connectors/` isolando HTTP externo. **Crítica:**
o fluxo lógico cita "resources + validação → controllers → repositories", mas a
pasta `src/repositories/` existe e não aparece no `fileTree` de `models` - a
camada está presente e correta; a documentação do README desenha bem o fluxo.
Boundary COD-09 bem imposta por teste.

### 4.2 Complexidade e duplicação - aceitável; um ponto de atenção
`transaction_controller.create()` é longo e concentra parsing, idempotência,
validação de valor, dispatch e commit. É legível e bem comentado, mas é o
método de maior complexidade ciclomática do projeto; candidato a extração de
helpers **sem** mudar a fronteira de commit (risco médio - adiar). Não há
duplicação de fee/hash após a extração para `services/`.

### 4.3 Segurança e exposição de segredos - adequado para MVP, com ressalvas
- **[INSPEÇÃO]** Autenticação por header `INTERNAL-TOKEN` comparado a
  `INTERNAL_TOKEN` (de ambiente, não hard-coded) em
  `src/middlewares/internal_token.py`; `/` e `/health_check` públicos.
  **Crítica:** a comparação `!=` **não é constant-time** - vulnerável em teoria
  a timing attack. Para um token interno de MVP, risco baixo; registrar.
- **[INSPEÇÃO]** `.env.example` e defaults do Compose usam `default_token`
  e `bootcamp:bootcamp` - **explicitamente marcados como somente-local**; o
  arquivo avisa "nunca coloque credenciais reais". Correto para o escopo.
- Nenhum segredo real versionado encontrado.

### 4.4 Dependências e versões - majoritariamente fixadas; inconsistência real
- `requirements.txt` fixa tudo com `==` (fastapi 0.141.1, SQLAlchemy 2.0.23,
  psycopg2-binary 2.9.10, requests 2.32.3, jsonschema 4.17.3). Bom para
  reprodutibilidade.
- **Crítica factual:** o comentário ao lado de `psycopg2-binary==2.9.10` fala
  em "2.9.10 é a primeira série com pacote ARM" e cita "2.9.5", mas o README e
  o quick-start assumem Docker; o comentário é levemente enganoso (texto, não
  função). `jsonschema==4.17.3` é uma série antiga (Draft-7); funcional, mas
  candidata a atualização controlada na P2.
- `pydantic==2.13.4` permanece fixado embora o projeto valide via `jsonschema`
  (o próprio `requirements.txt` admite que o código não usa mais pydantic
  diretamente). Dependência transitiva do FastAPI - manter, mas documentar.

### 4.5 Observabilidade, erros e logs - ponto forte
Middlewares de `request_context` (id por requisição), `request_logger`
(ENTROU/SAIU, inclusive 403) e `session_manager` (rollback/close, nunca commit
implícito). Erros de domínio com códigos `QITxxxxxx` e envelope consistente
(`test_error_envelope.py`). Timeouts de banco configuráveis
(`DB_LOCK_TIMEOUT_MS`, `DB_STATEMENT_TIMEOUT_MS`) com testes de observabilidade.
**Crítica:** os erros-base genéricos não estão na RFC (RFC-01 pendência 3).

### 4.6 Desempenho dos acessos ao PostgreSQL - adequado
Índices em todas as FKs relevantes e nos históricos (`(client_id, created_at,
id)`), índice de tipo em `financial_transaction`. Locks ordenados evitam
deadlock. **Custo introduzido pela P1-D:** resolução texto→id de lookup na
escrita adiciona SELECTs em tabelas-semente minúsculas (cacheáveis); impacto
desprezível e já reconhecido em `docs/P1D-DATABASE-AUDIT.md §11`.

### 4.7 Qualidade dos testes e efetividade do CI - forte, com honestidade rara
O CI roda a suíte real contra stack completa, sem atalhos (`pytest -q -ra`,
sem `continue-on-error`/`--maxfail`/skips), e **falha** o job em qualquer
vermelho. Os testes de COD-09/COD-11/COD-13 são de regressão genuína (falham
se o código for revertido): o de camada verifica `ModuleNotFoundError` dos
módulos removidos; o de commit-boundary exercita a fronteira pública; o de
MockServer prova a saída HTTP real. **Crítica:** COD-04/08/14 ainda têm fração
não-black-box; e a migração populada depende só do CI (não há teste pytest de
rollback de dados - pendência consciente registrada em
`docs/P1D-DATABASE-AUDIT.md §11`).

### 4.8 Documentação e reprodutibilidade - muito boa, com dívida numérica
README, RFC, ERD, ROTAS, FLUXOS e as auditorias de fase são densos e
confiáveis. Quick-start por Docker é reprodutível. **Crítica factual e
acionável:** README (badge/seção CI) e o cabeçalho do `ci.yml` ainda citam
**"442 testes"**, enquanto o run real atual tem **544**. Não é fraude (o
próprio texto manda ler a aba Actions), mas é dado desatualizado que confunde.

---

## 5. Roadmap priorizado da P2

Cada item: **Impacto · Risco de regressão · Esforço · Justificativa ·
Critérios de aceitação mensuráveis.** Prioriza correção/segurança/
confiabilidade/observabilidade/documentação. Nada fora da RFC.

### P2-01 - Sincronizar contagem de testes e sinais de CI na documentação
- **Impacto:** médio · **Risco:** baixo · **Esforço:** pequeno.
- **Justificativa:** README e cabeçalho do `ci.yml` citam "442"; o real é
  544. Dado desatualizado prejudica credibilidade de uma entrega madura.
- **Aceitação:** README e comentário do `ci.yml` citam **544** e o run
  `43549391873` (ou o mais recente verde); nenhum "442" remanescente
  (`grep -r "442" README.md .github/` vazio). Sem mudança de código/teste.

### P2-02 - Fechar as pendências documentais da RFC-01
- **Impacto:** médio · **Risco:** baixo · **Esforço:** pequeno.
- **Justificativa:** erros-base `QIT0000xx` e `BankSlipConnector`
  (boletos fora de escopo) não são citados/justificados na RFC.
- **Aceitação:** a RFC (ou ERD/ROTAS) lista os códigos de erro genéricos de
  `base_error.py`; e documenta por que `BankSlipConnector`/`BANKSLIP_API_*`
  existem apesar de boletos estarem fora de escopo **ou** os remove. Decisão
  registrada; sem mudança de comportamento de produção.

### P2-03 - Elevar formalmente COD-04/COD-14 (conversão de testes de baixo risco)
- **Impacto:** alto · **Risco:** médio · **Esforço:** médio.
- **Justificativa:** são os critérios parciais que a banca pontua por fração;
  converter os alvos de baixo risco (os já listados como pendência em
  `P1B-TEST-AUDIT.md §6`) aumenta a conformidade sem enfraquecer asserções.
- **Aceitação:** redução mensurável de arquivos DB-ACCESS sem nenhum
  `skip`/`xfail` novo e sem asserção enfraquecida; CI continua
  `N passed, 0 failed`; relatório atualizado com o delta por arquivo.

### P2-04 - Teste pytest dedicado de rollback de dados da migração
- **Impacto:** médio · **Risco:** baixo · **Esforço:** médio.
- **Justificativa:** hoje o rollback de dados é provado só pelo job `migration`
  do CI; um teste pytest em banco efêmero dá cobertura reproduzível
  (pendência consciente de `P1D-DATABASE-AUDIT.md §11`).
- **Aceitação:** novo teste no cluster efêmero que aplica migração→rollback e
  assere contagens/`sum_balance`/texto de enums preservados; verde no CI.

### P2-05 - Comparação de token em tempo constante
- **Impacto:** baixo · **Risco:** baixo · **Esforço:** pequeno.
- **Justificativa:** `internal_token.py` compara o token com `!=`
  (não constant-time). Risco real baixo, mas é higiene de segurança barata.
- **Aceitação:** uso de `hmac.compare_digest`; teste de autenticação (R01)
  continua verde; sem mudança de contrato.

### P2-06 - Cobertura formal de erros de domínio (COD-03) e convenção de rotas (COD-10)
- **Impacto:** médio · **Risco:** baixo · **Esforço:** médio.
- **Justificativa:** ambos ficaram "não verificáveis" para a banca; tornar a
  cobertura mensurável fecha a lacuna de verificação.
- **Aceitação:** matriz erro-de-domínio × teste publicada (cada erro de
  `src/errors/*` tem ao menos um teste que o dispara); e checagem
  automatizada da convenção singular das rotas; CI verde.

### P2-07 (opcional, só se a banca exigir literalidade) - `*_key` em especializações PF/PJ
- **Impacto:** baixo · **Risco:** médio · **Esforço:** médio.
- **Justificativa:** a régua literal do COD-05 sugere `id`+`*_key` em
  `individual_client`/`company_client`; a P1-D preservou `client_id` PK+FK por
  decisão fundamentada. Só executar **se** a banca rejeitar a justificativa.
- **Aceitação:** se adotado, migração aditiva sem criar segundo identificador
  público exposto na API; R01/R02 inalterados; CI verde. Caso contrário,
  manter a justificativa documentada.

---

## 6. Recomendação - próxima mudança de maior valor e menor risco

**Comece por P2-01 + P2-02 (documentação) na mesma rodada.**

- **Por quê é o maior valor com o menor risco:** a maior entrega de valor -
  destravar o COD-01 e manter a suíte verde - **já está feita** (544 verdes no
  CI). O que ainda corrói a percepção de qualidade são **dados
  desatualizados e omissões de documentação**, não defeitos de função: o
  "442" repetido no README e no `ci.yml` versus 544 reais, e as duas
  pendências RFC-01 (erros-base e `BankSlipConnector`). Corrigir isso é
  **esforço pequeno, risco de regressão nulo** (nenhuma linha de `src/`,
  teste, SQL ou lógica de CI muda) e remove exatamente o tipo de inconsistência
  que um avaliador rigoroso penaliza.
- **Sequência sugerida depois:** P2-05 (token constant-time, higiene barata) →
  P2-03/P2-06 (elevar COD-04/14 e tornar COD-03/10 mensuráveis, que é onde a
  pontuação por fração ainda tem folga) → P2-04 (teste pytest de rollback). O
  P2-07 fica reservado e condicionado à exigência explícita da banca.

**O que NÃO recomendar:** reabrir a fronteira de commit, reescrever o
`transaction_controller` ou introduzir novas camadas/tecnologias por
sofisticação. O núcleo financeiro (tarifa, HALF_UP, idempotência, locks,
atomicidade) está correto e coberto; mexer nele agora é risco sem retorno.

---

## Apêndice A - Procedência das evidências

| Evidência | Comando / arquivo | Resultado |
| --- | --- | --- |
| CI verde da suíte | `gh api .../actions/runs/43549391873` + `--log` | `conclusion=success`, `head_sha=f57ca8f`, `544 passed in 26.52s` |
| Jobs do run | `gh api .../runs/43549391873/jobs` | `test=success`, `migration=success` |
| Tarifa PF/PJ + HALF_UP | `pytest tests/unit/test_transfer_fee_invariants.py` (**executado aqui**) | `6 passed` |
| Boundary de camada COD-09 | leitura `transaction_controller.py:9-13` + `test_services_layer_boundary.py` | import de `services.*`; módulos legados inexistentes |
| Commit boundary COD-11 | leitura `transaction_controller.create()` | `self.session.commit()` no método público |
| Schema COD-05/06 | leitura `database/database.sql` | `entry_key UUID UNIQUE`; 5 lookups + FKs `ON DELETE RESTRICT` |
| Migração populada | leitura `0001_*.sql`, `0001_ROLLBACK.sql`, `legacy_schema.sql` + job `migration` | transação única, idempotente, validações; verde só no CI |
| COD-02 rotas demo | leitura `app.py` + `test_route_contracts.py::test_removed_demo_routes_are_gone` | `sample_entity` ausente; teste assere 404 |
| COD-13 MockServer | leitura `test_provider_call_recording.py` + `client_analysis_connector.py` | POST real gravado e asserido |
| Diff total da evolução | `git diff --stat 53269c1 f57ca8f` | 98 arquivos, +5957 / −1696 |
| Pendências RFC-01 | `grep` em `base_error.py`, `connectors/__init__.py`, `.env.example` | `QIT0000xx` e `BankSlipConnector` presentes, não citados na RFC |

## Apêndice B - Restrições de ambiente desta auditoria

- Rede `COMMON_DEPENDENCIES`; sem `psql`/`postgres`/`initdb`; `psycopg2`
  ausente; Docker CLI presente mas a suíte completa não foi executada
  localmente (exige dois clusters Postgres físicos + MockServer + uvicorn).
- Portanto, **a única prova verde da suíte inteira é o CI citado**; esta
  auditoria executou apenas testes puros sem banco. Essa limitação está
  refletida em cada marcação [CI]/[EXEC-LOCAL]/[INSPEÇÃO] acima.
- Rodada somente de leitura: `src/`, testes, `database.sql`, migrações e
  `ci.yml` **não** foram modificados.
