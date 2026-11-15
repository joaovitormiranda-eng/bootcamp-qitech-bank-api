# P2-Final — Auditoria Final Independente (QI Tech Bank API)

> **Natureza:** auditoria independente, crítica e baseada em evidências, do
> estado **efetivamente integrado** à `main` após P1, P2-A, P2-B e P2-Final.
> Rodada **somente de leitura e relatório**: nenhum arquivo de `src/`, teste,
> SQL, migração, Docker, workflow ou configuração do GitHub foi alterado. O
> único artefato produzido é este documento.
>
> **Repositório:** `joaovitormiranda-eng/bootcamp-qitech-bank-api` (fork).
> **Baseline:** `main` @ `c25b2e56fe65e7968077ff4af161f93e741291bf` (merge do PR #15).
> **CI de referência:** run [`43738426562`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43738426562) — `test`, `migration` e `security` = `success`, **554 passed**.

## Convenção de evidência

Cada afirmação é marcada por **como** foi apurada nesta rodada:

- **[CÓDIGO]** — verificado por leitura direta do arquivo citado (file:linha).
- **[EXEC-LOCAL]** — a auditoria **executou** no host (checagem estática/deps que não exigem banco).
- **[CI]** — atestado **apenas** por run verde do GitHub Actions (a suíte completa exige dois clusters PostgreSQL físicos + MockServer + uvicorn, não reproduzível localmente).
- **[INFERÊNCIA]** — conclusão derivada de evidência indireta.
- **[NÃO VERIFICÁVEL]** — fora do alcance desta sessão (ex.: configuração privada do GitHub).

Nenhuma CVE, métrica, resultado ou nota oficial foi inventada. Ausência de
achado **não** é tratada como garantia absoluta de segurança.

---

## 1. Resumo executivo e veredito

A Bank API é um **MVP acadêmico de BaaS single-tenant** cujo núcleo
financeiro (tarifa PF/PJ com `HALF_UP`, locks ordenados, atomicidade com commit
único e rollback integral, idempotência global com SHA-256) foi **reconferido
diretamente contra o código** nesta rodada e está **correto e coberto**. A
evolução P1→P2 destravou a suíte (P0/COD-01), normalizou o modelo de dados
(P1-D), impôs fronteiras de camada (P1-C), e em P2 corrigiu a higiene de
segurança (token em tempo constante, dependências, exposição da API, hardening
de CI) e adicionou verificações DevSecOps **bloqueantes**. A documentação foi
sincronizada ao código e revisada factualmente.

**Veredito.** No escopo declarado pela RFC v2.1, a **P2 pode ser considerada
encerrada** quanto ao que era executável e verificável: todos os PRs #1–#15
estão integrados, o CI está verde nos três jobs (`test`, `migration`,
`security`) com **554 testes**, as verificações de segurança reproduzem
localmente, e os riscos SEC remanescentes são **residuais aceitos e
justificados** (não defeitos). **Ressalvas a registrar:** (a) algumas
configurações do GitHub (proteção de branch) são **não verificáveis** por esta
sessão; (b) persistem débitos COD-04/08/14 **parciais e legítimos** (frações de
testes que acessam banco por necessidade) e a divergência consciente de COD-05
nas especializações PF/PJ; (c) este é um **MVP validado em CI**, distinto de um
serviço em produção — **não** se declara segurança absoluta.

| Severidade | Qtde | Itens |
|---|---|---|
| Crítica | 0 | nenhum |
| Alta | 0 | nenhum |
| Média | 0 | nenhum confirmado nesta rodada |
| Baixa / residual aceito | 4 | SEC-04, SEC-07, SEC-11, SEC-12 |
| Não verificável | 1 | proteção de branch / configs privadas do GitHub (§7.H) |

---

## 2. Baseline, SHA e evidências de CI

- **main @ `c25b2e5`**; PRs **#1–#15 todos integrados**; **0 PRs abertos**. [CÓDIGO]/[CI]
- Run **`43738426562`** (merge do #15): `test=success`, `migration=success`, `security=success`. [CI]
- Contagem lida no log: **`554 passed in 29.12s`** (não assumida). [CI]
- Job `security` no mesmo run: Bandit **No issues identified** (3864 LOC); pip-audit **No known vulnerabilities found** em `requirements.txt` e `requirements-dev.txt`. [CI]

---

## 3. Escopo e metodologia

**Escopo.** `src/`, `tests/`, `database/` (schema + migrações), `.github/workflows/ci.yml`, dependências e a documentação (`README.md`, `docs/*`).

**Procedimento desta rodada (independente das auditorias anteriores):**
1. Releitura direta dos pontos críticos de decisão financeira, idempotência, paginação e segurança — com citação file:linha.
2. Reexecução **local** de Bandit e pip-audit sobre a baseline.
3. Confirmação do resultado real dos três jobs de CI e da contagem de testes nos logs.
4. Conferência cruzada documentação↔código e checagem de links/diagramas/JSON implícita na própria revisão.

**Limites assumidos.** Sem Docker/PostgreSQL/`psql`/`psycopg2` no host; a suíte completa só é verde **no CI**. Sem pentest dinâmico. Configurações privadas do GitHub não são acessíveis pelo token desta sessão.

---

## 4. Avaliação dos requisitos R01–R10 (RFC v2.1)

Contratos reconferidos contra `src/app.py` (rotas), `src/resources/*`, `src/controllers/*` e `docs/ROTAS.md`. [CÓDIGO] + [CI]

| Rota | Método/Caminho | Sucesso | Estado |
|---|---|---|---|
| R01 | `POST /client` | 201 | ✅ cadastro PF/PJ atômico (cliente+perfil+evento inicial) |
| R02 | `GET /client/{client_key}` | 200 | ✅ leitura idempotente |
| R03 | `POST /client/{client_key}/analysis` | 200 | ✅ provedor HTTP fora de lock; revalida PENDING sob lock |
| R04 | `POST /client/{client_key}/account` | 201 | ✅ conta única (UNIQUE client_id); ACC0002 na 2ª |
| R05 | `GET /account/{account_key}` | 200 | ✅ snapshot de saldo/estado |
| R06 | `PATCH /account/{account_key}` | 200 | ✅ transições + coordenação do cliente; CLOSED só com saldo 0 |
| R07 | `POST /account/{account_key}/transaction` | 201 | ✅ depósito/transferência atômicos e idempotentes |
| R08 | `GET /account/{account_key}/transactions` | 200 | ✅ extrato por lançamento; **200 + lista vazia** além do fim |
| R09 | `PATCH /client/{client_key}` | 200 | ✅ reanálise/estado sem conta; CLI0009 exige R06 |
| R10 | `GET /health_check` | 204 | ✅ liveness sem corpo, público |

Catálogo de erros `QITxxxxxx`/`CLIxxxx`/`ACCxxxx`/`TRXxxxx` confere com `src/errors/*` (25 códigos). O `GET /` público retorna apenas `{"service": ...}` (sem PID — SEC-06). [CÓDIGO]

**Classificação RFC:** **Resolvido e comprovado** — as 10 rotas estão implementadas e cobertas; `/docs`,`/redoc`,`/openapi.json` ficam atrás do token e são desligados em `APP_ENV=production`.

---

## 5. Integridade financeira

Reverificado em `src/services/transfer_fee.py`, `src/services/transaction_hash.py`, `src/controllers/transaction_controller.py`, `src/repositories/account_repository.py`, `database/database.sql`. [CÓDIGO] + [CI]

- **Tarifa (transfer_fee.py).** PF (`INDIVIDUAL`): `rate_bps=50`, min `50`, max `1000`. PJ (`COMPANY`): `rate_bps=100`, min `100`, max `1500`. Fórmula inteira **HALF_UP**: `(amount_cents * rate_bps + 5000) // 10000`, depois `min(max(fee, min), max)`. Sem ponto flutuante. **Resolvido e comprovado.**
- **Locks ordenados.** Transferência trava contas por **`ACCOUNT.id` crescente** (`get_by_ids_for_update(sorted(...))`), repositório com `.order_by(Account.id).populate_existing().with_for_update(of=Account)`. Anti-deadlock. **Resolvido e comprovado.**
- **Fronteira transacional (COD-11).** Exatamente **um** `self.session.commit()`, no método **público** `create` (linha 221); métodos privados só preparam/`flush`. O middleware `session_manager` **nunca** commita (só rollback/close). **Resolvido e comprovado.**
- **Revalidação sob lock.** Status/saldo revalidados **após** o `FOR UPDATE` (`populate_existing` força releitura); `InsufficientBalance` (TRX0001) levantada **antes** de qualquer persistência. **Resolvido e comprovado.**
- **Rollback.** `except Exception: rollback(); raise` no `create`; ramo de colisão de idempotência faz `rollback()` e relê o vencedor. **Resolvido e comprovado.**
- **Invariantes de banco.** `CHECK (balance_cents >= 0)`, `amount_cents > 0`, `balance_after_cents >= 0`. **Resolvido e comprovado.**

---

## 6. Idempotência global

[CÓDIGO] + [CI]

- **Intenção canônica (transaction_hash.py).** Depósito: `DEPOSIT|{account_key}|{amount_cents}`; transferência: `TRANSFER|{source}|{target}|{amount_cents}`; `sha256(...).hexdigest()`. **Não** inclui JSON bruto, tarifa, timestamp nem a própria chave.
- **Persistência e unicidade.** `financial_transaction.request_control_key UUID NOT NULL UNIQUE` (constraint `financial_transaction_request_control_key_key`).
- **Replay vs conflito.** Mesma chave + mesmo hash → devolve a transação original (sem nova movimentação); mesma chave + hash diferente → `IdempotencyKeyConflict` (TRX0003, 409).
- **Concorrência.** Colisão simultânea tratada por `IntegrityError` → `rollback()` → releitura do vencedor; se não achar, re-levanta. Coberto por testes de concorrência de idempotência. **[CI]**

**Classificação:** **Resolvido e comprovado.**

---

## 7. PostgreSQL, migrações e rollback

[CÓDIGO] + [CI]

- **15 tabelas** em `database/database.sql`: 8 de domínio + 7 de lookup. Confirmado que **`client_status` e `account_status` já existiam no schema legado** (`tests/integration/database/legacy_schema.sql`); a P1-D **acrescentou 5** lookups (`client_type`, `transaction_type`, `transaction_direction`, `entry_type`, `actor_type`) — correção factual já aplicada à documentação.
- **Integridade referencial.** Enumerações por **FK `*_id` `ON DELETE RESTRICT`**; `transaction_entry.entry_key UUID NOT NULL UNIQUE` (COD-05). **10 índices** declarados (incluindo `idx_transaction_entry_account/transaction`).
- **Migração 0001 (populada).** Transação única com `ON_ERROR_STOP=1`; `pgcrypto`; cria lookups (idempotente via `IF NOT EXISTS` + `ON CONFLICT DO NOTHING`); backfill texto→FK com validação por `RAISE EXCEPTION`; `entry_key` por linha via `gen_random_uuid()` — **UUIDs aleatórios**, com idempotência garantida por `WHERE entry_key IS NULL` (não regera chaves existentes). Correção factual já refletida em `docs/MIGRACOES.md`.
- **Rollback.** `0001_ROLLBACK.sql` restaura estrutura legada; **lossless** para dados de negócio (o `enumerator` é o mesmo texto); `entry_key` é descartado (sem FK). Validado pelo job `migration` (cluster efêmero dedicado, 5434: snapshots BEFORE/AFTER, idempotência, rollback) e por `tests/integration/database/test_populated_migration.py`. **[CI]**

**Classificação:** **Resolvido e comprovado** (COD-06 integralmente; COD-05 resolvido para `transaction_entry`, **parcial/divergência consciente** para as especializações PF/PJ — ver §8).

---

## 8. Segurança e DevSecOps

### 8.1 Autenticação e exposição — [CÓDIGO] + [EXEC-LOCAL] + [CI]
- **INTERNAL-TOKEN em tempo constante (SEC-01).** `_tokens_match` usa `hmac.compare_digest` com codificação `latin-1` nos dois lados e guarda de `None`/vazio (sem bypass, sem `TypeError`/500 em bytes não-ASCII). **Resolvido e comprovado.**
- **BYPASS_ENDPOINTS** = `["/", "/health_check"]`. Nenhuma rota de negócio é pública.
- **OpenAPI (SEC-05).** `/docs`,`/redoc`,`/openapi.json` atrás do token; desligados quando `APP_ENV == "production"`. **Resolvido e comprovado.**
- **PID (SEC-06).** `GET /` retorna só `{"service": ...}`. **Resolvido e comprovado.**
- **Logs.** Allowlist estruturada (`STRUCTURED_FIELDS`); `tests/integration/test_observability.py` assere ausência de CPF/CNPJ/e-mail/segredo/`INTERNAL_TOKEN` e uso de rota templada. **Resolvido e comprovado.**

### 8.2 Dependências (SEC-02/SEC-03) — [EXEC-LOCAL] + [CI]
- `requirements.txt`: `requests==2.33.0`; `requirements-dev.txt`: `pytest==9.0.3`, `python-dotenv==1.2.2`.
- **Reexecução local nesta rodada (dois escopos de Bandit):**
  - `bandit -r src -ll` (piso MEDIUM, o comando do CI) → **No issues identified**, exit 0.
  - `bandit -r src` (**todas as severidades**, sem o filtro `-ll`) → **No issues identified**, exit 0; breakdown por severidade: **Undefined 0 · Low 0 · Medium 0 · High 0** (3864 linhas analisadas).
  Ou seja, não há achados **mesmo incluindo severidade/confiança baixas** — a afirmação "0 achados gerais" está lastreada na execução sem filtro, não apenas no comando do CI.
  - pip-audit → **No known vulnerabilities found** em `requirements.txt` e `requirements-dev.txt`.
  Reproduz o CI. **Resolvido e comprovado.**

### 8.3 Hardening do CI (SEC-08/09/10) — [CÓDIGO]
- `permissions: contents: read` no topo do workflow.
- Actions pinadas por **SHA** em runtime **Node.js 24** (checkout v5.1.0, setup-python v6.3.0, upload-artifact v7.0.2).
- Artefato `pytest-results` com `retention-days: 7`.

### 8.4 DevSecOps — Bandit e pip-audit são de fato bloqueantes? — [CÓDIGO] + [CI]
**Sim.** No job `security` do `ci.yml`: `bandit -r src -ll` roda sem `continue-on-error`; o passo de pip-audit roda `pip-audit -r requirements.txt` e `pip-audit -r requirements-dev.txt` **sem `continue-on-error` e sem `|| true`** — o status de saída decide o job. Os três jobs (`test`, `migration`, `security`) funcionam na `main` integrada (run `43738426562`). **Resolvido e comprovado.**

> **Nota sobre o escopo do Bandit no CI.** O `-ll` eleva o piso para MEDIUM, ou seja, o gate do CI reprovaria apenas achados de severidade **MEDIUM/HIGH**; achados LOW não derrubariam o job. Isso **não** mascara nada na baseline atual: a reexecução local **sem** `-ll` (§8.2) confirma **0 achados em todas as severidades** (Low/Medium/High = 0). Recomendação futura (fora desta auditoria): considerar rodar também o escopo sem filtro no CI, ou documentar explicitamente a política de severidade, para que um eventual achado LOW no futuro seja ao menos visível.

### 8.5 GitHub — proteções de branch, permissões, regras de merge — [NÃO VERIFICÁVEL]
`GET /repos/.../branches/main/protection` retornou **HTTP 404** ao token desta sessão (configuração privada ou ausente). **Não verificável aqui.** Passos para o proprietário conferir (UI do repositório):
- *Settings → Branches → Branch protection rules* para `main`: exigir PR + review; **status checks obrigatórios** `test`, `migration`, `security`; bloquear force-push; exigir branch atualizada.
- *Settings → Code security and analysis*: Dependabot alerts/updates, secret scanning, push protection, code scanning.
- *Settings → Actions → General*: confirmar `Workflow permissions = Read repository contents` como default.

### 8.6 Riscos SEC residuais (aceitos e justificados)
| ID | Tema | Classificação | Justificativa |
|---|---|---|---|
| SEC-04 | Sem rate limiting no gate de token | **Risco residual aceito** | Mitigação natural na borda/infra; em código arriscaria testes de concorrência. SEC-01 já reduz o canal lateral. |
| SEC-07 | `page` sem teto (OFFSET profundo) | **Risco residual aceito** | Contrato exige 200+lista vazia além do fim; custo limitado por `statement_timeout` (SQLSTATE 57014 tratado). Keyset mudaria a semântica — recomendação futura. |
| SEC-11 | Usuário único de banco com DDL; TLS não no repo | **Risco residual aceito** | Responsabilidade de infra de deploy; credenciais demonstrativas locais. |
| SEC-12 | Connector de análise sem INTERNAL-TOKEN | **Risco residual aceito** | Provedor é o MockServer (não exige token); parametrizar quando houver provedor real. |

---

## 9. Matriz final COD / SEC / RFC

| Item | Classificação | Evidência |
|---|---|---|
| COD-01 (suíte sobe/passa) | Resolvido e comprovado | [CI] 554 passed, run 43738426562 |
| COD-02 (rotas testadas) | Resolvido e comprovado | `app.py` sem `sample_entity`; teste de contrato 404 |
| COD-03 (erros de domínio) | Resolvido (majoritário) + reforço P2-B | catálogo `src/errors/*`; PR #14 (ACC0002/TRX0002) black-box |
| COD-04 (só integração black-box) | **Parcial (legítimo)** | conversões reais; frações MISTAS por necessidade (schema/concorrência/fault-injection) |
| COD-05 (`id`+`*_key`) | Resolvido p/ `transaction_entry`; **Parcial/divergência consciente** p/ PF/PJ | `entry_key` UNIQUE; `individual_client`/`company_client` mantêm `client_id` PK+FK (documentado) |
| COD-06 (enum→lookup) | Resolvido e comprovado | 7 lookups + FKs em `database.sql` (5 adicionadas em P1-D) |
| COD-07 (`*_status_event`) | Resolvido e comprovado | históricos com `actor_type_id` FK |
| COD-08 (não importar `src`) | **Parcial (legítimo)** | unidades puras e teste de fronteira importam `src` por design |
| COD-09 (sem chamada entre irmãos) | Resolvido e comprovado | `services/` puro; módulos legados removidos |
| COD-10 (rotas singular) | Resolvido (majoritário) | `app.py` singular, coletivos legítimos (analysis/transactions) |
| COD-11 (commit no fim) | Resolvido e comprovado | único `commit()` em `create` (linha 221) |
| COD-12 (JSON schema não-GET) | Resolvido e comprovado | `src/schemas/*` |
| COD-13 (connector via MockServer) | Resolvido e comprovado | teste R03 grava/consulta MockServer |
| COD-14 (testes sem banco fora de rollback) | **Parcial (legítimo)** | acesso a banco por necessidade documentada |
| SEC-01 token tempo constante | Resolvido e comprovado | `hmac.compare_digest` (internal_token.py) |
| SEC-02 `requests` | Resolvido e comprovado | 2.33.0; pip-audit limpo |
| SEC-03 deps dev | Resolvido e comprovado | pytest 9.0.3 / python-dotenv 1.2.2; pip-audit limpo |
| SEC-05 OpenAPI | Resolvido e comprovado | gating por `APP_ENV`; atrás do token |
| SEC-06 PID | Resolvido e comprovado | `health_check.py` sem `getpid` |
| SEC-08/09/10 CI | Resolvido e comprovado | permissions, SHA Node 24, retenção |
| SEC-04 / SEC-07 / SEC-11 / SEC-12 | Risco residual aceito e justificado | §8.6 |
| Proteção de branch | **Não verificável** | HTTP 404 (§8.5) |
| RFC v2.1 / R01–R10 | Resolvido e comprovado | §4 |

---

## 10. Cobertura de testes e evidências

- **70 arquivos** `test_*.py`; a suíte cobre contrato HTTP, validação de payload, regras de domínio, persistência, estados, idempotência, **concorrência/atomicidade** (R04/R06/R07/R09), rollback, movimentações financeiras e extrato. [CÓDIGO]
- **Casos negativos black-box** reforçados em P2-B (`test_r04_r07_negative_paths_blackbox.py`: ACC0002, TRX0002, HTTP-only). [CÓDIGO]
- **Isolamento entre bancos:** dois clusters PostgreSQL **fisicamente separados** no job `test` (5432/5433) e um terceiro dedicado no job `migration` (5434); fixtures comparam `system_identifier` por cluster. [CÓDIGO]/[CI]
- **Evidência verde:** 554 passed, run `43738426562`. [CI]
- **Limitação:** a suíte completa não roda localmente (sem Docker/Postgres/psycopg2 no host); a aba Actions é a fonte autoritativa. Débitos COD-04/08/14 implicam que uma fração dos testes acessa banco por necessidade legítima — cobertura real, não black-box pura.

---

## 11. Consistência documental

Revisados `README.md`, `ROTAS.md`, `ERD.md`, `FLUXOS.md`, `RFC.md`, `ARQUITETURA.md`, `SEGURANCA.md`, `CI-DEVSECOPS.md`, `MIGRACOES.md`, `AUDITORIAS.md` e os relatórios históricos P1/P2. [CÓDIGO]

- **Coerentes com o código:** contagem de testes (554), 15 tabelas, FKs de enumeração, `entry_key`, tarifa/HALF_UP, idempotência, paginação 200+vazia, jobs de CI bloqueantes.
- **Correções factuais da revisão do PR #15 confirmadas:** (a) origem das lookups (5 em P1-D, 2 legadas); (b) backfill de `entry_key` com `gen_random_uuid()` é **aleatório**, não determinístico, com idempotência por `WHERE entry_key IS NULL`; (c) modelo dbdiagram.io rotulado como **histórico/não verificado**.
- **Preservação histórica:** RFC v2.1 (Markdown e PDF) e relatórios P1/P2 mantidos sem reescrita; a RFC traz apenas nota editorial apontando para o schema atual.
- **Observação menor (não bloqueia):** o comentário/cabeçalho do SQL da migração ainda usa a expressão "backfill determinístico"; o texto executável não foi alterado nesta campanha por decisão de escopo. A documentação em `MIGRACOES.md` já esclarece a semântica real. Recomenda-se corrigir o comentário do SQL numa futura rodada de código (fora desta auditoria).

---

## 12. Pendências objetivas

1. **Proteção de branch não verificável** (§8.5): conferir na UI que `test`, `migration` e `security` são checks **obrigatórios** na `main`. — *ação do proprietário.*
2. **Comentário "determinístico" no SQL da migração** (§11): ajuste textual no SQL, fora do escopo desta auditoria. — *rodada de código futura.*

Nenhuma dessas pendências é bloqueante para o encerramento da P2.

> **Correção quanto ao `P2-CAMPAIGN-LOG.md`.** Verificado nesta rodada que o
> arquivo `docs/P2-CAMPAIGN-LOG.md` **não está versionado** — não consta de
> `origin/main` (`git ls-tree -r origin/main` não o lista) nem é rastreado em
> qualquer branch (`git ls-files` vazio); existe apenas como artefato **local
> não rastreado** no diretório de trabalho. Portanto **não faz parte da entrega
> versionada** e **não é uma pendência do repositório**. Uma versão anterior
> deste relatório o listava como pendência cosmética; isso fica retificado aqui.

---

## 13. Critérios de encerramento e parecer final

| Critério | Situação |
|---|---|
| PRs #1–#15 integrados | ✅ |
| CI `test` / `migration` / `security` verdes na `main` | ✅ (run 43738426562) |
| Contagem real de testes confirmada | ✅ 554 |
| Núcleo financeiro reverificado contra o código | ✅ |
| Verificações de segurança reproduzidas localmente | ✅ (Bandit 0, pip-audit limpo) |
| Documentação coerente com o código | ✅ |
| Riscos residuais registrados e justificados | ✅ (SEC-04/07/11/12) |
| Itens não verificáveis declarados | ✅ (proteção de branch) |

**Parecer.** Com base nas evidências acima, a **P2 está apta a ser considerada
encerrada** no escopo executável e verificável, com as **ressalvas** de §11–§12.
O projeto cumpre a RFC v2.1 e as invariantes financeiras, com segurança
adequada ao modelo single-tenant de um MVP acadêmico validado em CI. **Não** se
declara segurança absoluta nem se atribui nota oficial de banca — isso depende de
avaliação externa. Nenhum problema crítico ou alto foi confirmado nesta rodada.

---

## 14. Recomendações para eventual contribuição ao upstream (sem executar)

> Apenas avaliação de alto nível. **Nenhum** PR foi aberto para o upstream
> `mohamad347/bootcamp-qitech-bank-api` e nada nele foi tocado.

1. **Verificar `CONTRIBUTING`/convenções do upstream** antes de qualquer proposta (nomes de branch, formato de commit, branch-alvo).
2. **Curar um subconjunto coeso:** as correções de segurança (SEC-01/02/03/05/06/08/09/10) e a cobertura black-box (COD-03) são candidatas naturais; a normalização P1-D exige a migração versionada + rollback juntos.
3. **Preservar a baseline verde:** garantir `test`/`migration`/`security` verdes no fork antes de propor.
4. **Separar documentação de código** em PRs distintos, como feito aqui.
5. **Antes de tornar pip-audit bloqueante no upstream**, confirmar que a baseline dele está limpa, para não criar um check impossível de passar.
6. **Não** promover riscos residuais aceitos a refatorações obrigatórias sem decisão de produto (keyset pagination, usuário de banco sem DDL, provedor real, rate limiting na borda).

---

## Apêndice A — Procedência das evidências (amostra)

| Evidência | Método | Resultado |
|---|---|---|
| SHA da main | `git rev-parse HEAD` | `c25b2e5` |
| PRs 1–15 integrados | `gh api .../pulls?state=all` | todos `merged=true`; 0 abertos |
| CI verde | `gh run view 43738426562 --json jobs` | `test/migration/security = success` |
| Contagem de testes | `gh run view ... --log` | `554 passed in 29.12s` |
| Bandit local (piso MEDIUM) | `bandit -r src -ll` | exit 0, No issues identified (3864 LOC) |
| Bandit local (todas severidades) | `bandit -r src` | exit 0, No issues identified; Low/Medium/High = 0 |
| pip-audit local | `pip-audit -r requirements*.txt` | No known vulnerabilities found (ambos) |
| Tarifa/HALF_UP | leitura `src/services/transfer_fee.py` | PF 50bps/50/1000; PJ 100bps/100/1500; `(amt*bps+5000)//10000` |
| Commit único | leitura `transaction_controller.py` | 1 `commit()` em `create` (linha 221) |
| Token tempo constante | leitura `src/middlewares/internal_token.py` | `hmac.compare_digest` + latin-1 + guarda None |
| 15 tabelas / FKs / entry_key | leitura `database/database.sql` | 15 `CREATE TABLE`; FKs `*_id`; `entry_key UNIQUE` |
| Lookups legadas | leitura `tests/integration/database/legacy_schema.sql` | contém `client_status` e `account_status` |
| pip-audit/bandit bloqueantes | leitura `.github/workflows/ci.yml` | sem `continue-on-error`/`|| true` no job `security` |
| Proteção de branch | `gh api .../branches/main/protection` | HTTP 404 (não verificável) |

## Apêndice B — Restrições de ambiente

Sem Docker/PostgreSQL/`psql`/`initdb`/`psycopg2` no host; rede restrita. A suíte
completa (dois clusters Postgres físicos + MockServer + uvicorn) **só** é verde
no GitHub Actions, que permanece a prova autoritativa. Esta auditoria executou
localmente apenas checagens estáticas e de dependências (Bandit, pip-audit) e
leitura de código/SQL/workflow. Sem pentest dinâmico. Rodada somente de
leitura/relatório.
