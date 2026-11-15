# Histórico de auditorias e rastreabilidade — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Versão:** P2-Final

**Documentos relacionados:** [Segurança](SEGURANCA.md) · [CI/DevSecOps](CI-DEVSECOPS.md) · [Migrações](MIGRACOES.md) · [Arquitetura](ARQUITETURA.md)

> Este documento consolida o histórico das rodadas de auditoria e liga cada
> afirmação da documentação ao código integrado. Os relatórios por fase são
> **preservados como evidência de cada momento** e não devem ser reescritos:
> [P1 consolidada](P1-CONSOLIDATED-AUDIT.md), [P1-B testes](P1B-TEST-AUDIT.md),
> [P1-C arquitetura](P1C-ARCHITECTURE-AUDIT.md), [P1-D banco](P1D-DATABASE-AUDIT.md),
> [P2-A segurança](P2A-SECURITY-AUDIT.md).

## 1. Linha do tempo

| Fase | Foco | Resultado |
|---|---|---|
| **P0** | Reprodutibilidade da suíte e provisionamento da stack no CI (COD-01) | Suíte passou a subir verde no GitHub Actions (baseline inicial: 442 testes) |
| **P1-A** | Saneamento de rotas (COD-02) e cobertura de contrato/erro (COD-03/COD-10) | Rotas de demonstração removidas; cobertura de contrato ampliada |
| **P1-B** | Isolamento black-box dos testes e integração MockServer (COD-04/08/13/14) | Conversões para HTTP-only; connector testado via MockServer |
| **P1-C** | Fronteiras de camada e controle transacional (COD-09, COD-11) | `services/` puro extraído; `COMMIT` único no controller público |
| **P1-D** | Integridade do modelo PostgreSQL (COD-05, COD-06) | Lookups por FK + `transaction_entry.entry_key`; migração populada + rollback |
| **P1 consolidada** | Auditoria independente da evolução P0→P1-D | Relatório `P1-CONSOLIDATED-AUDIT.md` |
| **P2-A** | Auditoria independente de cibersegurança (só relatório) | Relatório `P2A-SECURITY-AUDIT.md` (SEC-01…SEC-12) |
| **P2 (remediação)** | Correções de segurança, hardening, DevSecOps e cobertura | PRs #9–#14 (ver §2) |
| **P2-Final** | Documentação definitiva sincronizada ao código integrado | Esta rodada documental |

## 2. P2 — correções integradas (PRs #9–#14)

Fato verificado (PRs mesclados na `main`; cada um com CI verde no merge):

| PR | Item | Mudança | Escopo |
|---|---|---|---|
| #9 | **SEC-02** | `requests` 2.32.3 → **2.33.0** (CVE-2024-47081, CVE-2026-25645) | `requirements.txt` |
| #10 | **SEC-05/06** | OpenAPI desligada em `production` + alinhamento comentário/config; remoção do PID em `GET /` | `src/app.py`, `src/resources/health_check.py` + testes |
| #12 | **SEC-03** | `pytest` 7.4.4 → **9.0.3** (CVE-2025-71176); `python-dotenv` 1.0.1 → **1.2.2** (CVE-2026-28684) | `requirements-dev.txt` |
| #11 | **SEC-08/09/10** | `permissions: contents: read`; Actions pinadas por SHA em Node.js 24; `retention-days: 7` | `.github/workflows/ci.yml` |
| #13 | **DevSecOps** | Job `security` com Bandit (bloqueante) e pip-audit (**bloqueante** após SEC-02/03) | `.github/workflows/ci.yml` |
| #14 | **COD-03** | Testes black-box de caminho negativo (ACC0002, TRX0002) | `tests/integration/transaction/` |

Estado de CI na `main` após as integrações: run
[`43735514804`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43735514804)
— `test`, `migration` e `security` em `success`, **554 testes aprovados**.

### SEC-01 (baseline)
Corrigido antes desta campanha (PR #8): comparação do `INTERNAL-TOKEN` em tempo
constante com `hmac.compare_digest`. Ver [SEGURANCA.md](SEGURANCA.md) §2.

### Política de pip-audit — evolução honesta
Enquanto SEC-02/SEC-03 não estavam integrados, o pip-audit rodou em modo
**observação** (não bloqueante) para não criar um check impossível de passar na
baseline, **sem mascarar achados**. Com os dois arquivos limpos, passou a
**bloqueante** (sem `continue-on-error`, sem `|| true`). Ver
[CI-DEVSECOPS.md](CI-DEVSECOPS.md) §6.

## 3. Matriz de rastreabilidade (documentação ↔ código)

| Afirmação na documentação | Fonte no código / CI |
|---|---|
| 10 rotas R01–R10; `/` e `/health_check` públicas | `src/app.py` (rotas); `src/constants.py` `BYPASS_ENDPOINTS` |
| `INTERNAL-TOKEN` em tempo constante (`hmac.compare_digest`) | `src/middlewares/internal_token.py` `_tokens_match` |
| OpenAPI desligada em `APP_ENV=production` | `src/app.py` (`docs_url`/`redoc_url`/`openapi_url` condicionais) |
| `GET /` sem PID | `src/resources/health_check.py` (`{"service": ...}`) |
| 15 tabelas (8 domínio + 7 lookup); FKs de enumeração; `entry_key` | `database/database.sql` |
| Tarifa PF/PJ (bps, min, max) e `HALF_UP` | `src/services/transfer_fee.py` |
| `request_hash` SHA-256 da intenção canônica | `src/services/transaction_hash.py` |
| Lock ordenado por `ACCOUNT.id`; `COMMIT` único; revalidação sob lock | `src/controllers/transaction_controller.py`; `src/repositories/account_repository.py` |
| Idempotência global; replay vs conflito (TRX0003) | `src/controllers/transaction_controller.py` (`_get_existing_response`, `IntegrityError`) |
| Extrato R08: `OFFSET (page-1)*limit`, `limit+1`, 200+lista vazia além do fim | `src/controllers/transaction_controller.py` `get_statement`; `src/repositories/transaction_repository.py` |
| Logs com allowlist; sem PII/segredo | `src/utils/logger.py`; `tests/integration/test_observability.py` |
| Catálogo de erros `QITxxxxxx`/`CLIxxxx`/`ACCxxxx`/`TRXxxxx` | `src/errors/*` |
| Migração populada + idempotência + rollback | `database/migrations/0001_*.sql`; job `migration`; `tests/integration/database/test_populated_migration.py` |
| Bandit 0 achados; pip-audit limpo e bloqueante | `.github/workflows/ci.yml` job `security`; run `43735514804` |
| 3 clusters PostgreSQL isolados (test: 5432/5433; migration: 5434) | `.github/workflows/ci.yml` |

## 4. Resíduos (COD e SEC)

**COD (P1).** Itens marcados PARCIAIS na P1 consolidada permanecem exceções
documentadas e legítimas (não defeitos):
- **COD-04/08/14** (fração de testes black-box / não-import de `src` / não-acesso
  a banco): vários testes de comportamento acessam banco por necessidade legítima
  (schema, back-dating, concorrência, fault-injection, overflow inatingível pela
  API). A P2-B **acrescentou** cobertura black-box de caminho negativo (PR #14)
  sem enfraquecer asserções, mas não converteu os casos MISTOS legítimos.
- **COD-05** (padrão `id`+`*_key` nas especializações PF/PJ): `individual_client`
  e `company_client` preservam `client_id` como PK+FK por decisão de engenharia
  (ver [P1D-DATABASE-AUDIT](P1D-DATABASE-AUDIT.md)).

**SEC (P2).** Corrigidos: SEC-01, SEC-02, SEC-03, SEC-05, SEC-06, SEC-08, SEC-09,
SEC-10. Riscos residuais **aceitos** (limitações de MVP, detalhados em
[SEGURANCA.md](SEGURANCA.md) §7): **SEC-04** (rate limiting — borda/infra),
**SEC-07** (OFFSET profundo — contrato 200+lista vazia preservado; keyset como
recomendação futura), **SEC-11** (usuário de banco/TLS — infra de deploy),
**SEC-12** (token do provedor de análise — sem contrato real).

## 5. Distinção fundamental

- **Fato verificado:** afirmado quando há evidência em código ou em run de CI
  citável.
- **Limitação:** escolha consciente do escopo MVP (resíduos aceitos acima).
- **Recomendação:** trabalho futuro não implementado (ex.: keyset pagination,
  usuário de banco sem DDL, provedor de análise real, rate limiting na borda).

Este é um **MVP acadêmico validado em CI**, distinto de um **serviço implantado
em produção**. O projeto **não** implementa CD, Kubernetes, AWS ou GCP, e **não**
se declara "segurança absoluta". Nenhuma nota oficial de banca é atribuída aqui —
isso depende de avaliação externa.
