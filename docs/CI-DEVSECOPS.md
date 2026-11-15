# CI e DevSecOps — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Versão:** P2-Final

**Documentos relacionados:** [Segurança](SEGURANCA.md) · [Migrações](MIGRACOES.md) · [Arquitetura](ARQUITETURA.md) · [Auditorias](AUDITORIAS.md) · [Workflow](../.github/workflows/ci.yml)

> Tudo aqui é verificável contra [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
> e os logs do GitHub Actions. O último run verde da `main` citado nesta rodada é
> [`43735514804`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43735514804)
> — jobs `test`, `migration` e `security` em `success`, **554 testes aprovados**.

## 1. Por que o CI é a prova autoritativa

A suíte completa exige, ao mesmo tempo, **dois clusters PostgreSQL físicos**,
**MockServer** e a **API viva** (uvicorn). Esse arranjo não é reproduzível em
qualquer host arbitrário; o workflow o provisiona em runners `ubuntu-latest` a
cada `push` e `pull_request`. A evidência verde é a execução do workflow na aba
**Actions**, não uma garantia independente de ambiente.

## 2. Permissões mínimas (SEC-08)

O workflow declara, no topo, permissão mínima para o `GITHUB_TOKEN`:

```yaml
permissions:
  contents: read
```

Nenhum job escreve no repositório, cria release ou comenta em PR; o upload de
artefato usa o runtime de Actions, não a permissão `contents`. A declaração
explícita torna a postura resistente a mudança do *default* do repositório.

## 3. Pinagem de Actions por SHA em runtime Node.js 24 (SEC-09)

As Actions oficiais são pinadas por **SHA de commit completo** (imutável), com a
versão legível em comentário. Após a remoção do Node 20 dos runners, os releases
usados declaram `using: node24`:

| Action | SHA | Versão |
|---|---|---|
| `actions/checkout` | `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09` | v5.1.0 |
| `actions/setup-python` | `ece7cb06caefa5fff74198d8649806c4678c61a1` | v6.3.0 |
| `actions/upload-artifact` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | v7.0.2 |

## 4. Job `test` — suíte completa

Topologia de serviços (confirmada no workflow):

- **`postgres_api`** (`postgres:16`) em `127.0.0.1:5432` — banco `bootcamp` da API;
  o schema (`database/database.sql`) é carregado via `psql`.
- **`postgres_test`** (`postgres:16`) em `127.0.0.1:5433` — banco `bootcamp_test`,
  cluster **fisicamente separado**. A separação é obrigatória: fixtures de
  suporte comparam `pg_control_system()` (o `system_identifier` é único **por
  cluster**) e exigem que banco da API e banco de teste estejam em clusters
  distintos.
- **`mockserver`** (`mockserver/mockserver:8.0.0`) em `127.0.0.1:1080` — provedor
  cadastral simulado; os testes da R03 configuram expectativas em tempo de
  execução.
- **API viva** via `uvicorn app:app` em `127.0.0.1:3001`, aguardada até
  `/health_check` responder `204` antes da suíte.

O passo decisório é `pytest -q -ra --junitxml=pytest-results.xml` — **sem**
`continue-on-error`, **sem** `--maxfail`, **sem** skip/xfail artificiais. O
artefato `pytest-results` (JUnit XML + `api.log`) é publicado com
`retention-days: 7` (SEC-10).

## 5. Job `migration` — migração de schema populado

Job **isolado**, com seu **próprio** cluster PostgreSQL efêmero em `127.0.0.1:5434`
(`bootcamp_migration_test`). Não substitui nem altera o job `test`. Aplica a
migração versionada `0001` sobre um schema **legado populado** e prova, por
`RAISE EXCEPTION` e comparação de snapshots, que a evolução preserva contagem,
identidade, valores e relacionamentos; valida **idempotência** (reexecução é
no-op) e **rollback** com preservação de dados de negócio. Detalhes em
[MIGRACOES.md](MIGRACOES.md).

## 6. Job `security` — DevSecOps (P2)

Job **aditivo e isolado**: não provisiona banco e não usa segredos. Instala
ferramentas pinadas (`bandit==1.9.4`, `pip-audit==2.10.1`) e roda duas análises:

| Ferramenta | Comando | Política | Estado atual |
|---|---|---|---|
| **Bandit** (SAST) | `bandit -r src -ll` | **Bloqueante** | *No issues identified* (0 achados; piso MEDIUM) |
| **pip-audit** (dependências) | `pip-audit -r requirements.txt` e `pip-audit -r requirements-dev.txt` | **Bloqueante** | *No known vulnerabilities found* nos dois arquivos |

### Política de falha (explícita e honesta)

- **Bandit é bloqueante** desde a introdução do job (a auditoria P2-A registrou 0
  achados; manter em 0 é um gate barato e sustentável).
- **pip-audit tornou-se bloqueante** após a integração de **SEC-02** (`requests`
  2.33.0) e **SEC-03** (`pytest` 9.0.3, `python-dotenv` 1.2.2). O passo roda
  `pip-audit` **sem** `continue-on-error` e **sem** `|| true` — o status de saída
  decide o job. Uma advisory nova (nova dependência ou CVE recém-publicada)
  **reprova** o build.

> Honestidade de processo: enquanto os PRs de dependência (SEC-02/SEC-03) ainda
> não estavam integrados, pip-audit rodou em modo **observação** (não
> bloqueante), para **não** criar um check impossível de passar na baseline —
> sem mascarar achados. A transição para bloqueante só ocorreu quando os dois
> arquivos ficaram limpos de verdade. O registro dessa evolução está em
> [AUDITORIAS.md](AUDITORIAS.md).

### Ferramentas deliberadamente fora

Gitleaks, Semgrep (ruleset remoto) e Trivy **não** fazem parte da implementação:
dependem de binários Go/registro remoto não reproduzíveis no ambiente
(constatado na auditoria P2-A). Acrescentá-los sem execução reproduzível seria
teatro de segurança. O que está no workflow é o que roda de verdade.

## 7. Limitações

- O CI prova o comportamento **no ambiente do runner**, não em produção. Este
  projeto **não** implementa CD, Kubernetes, AWS ou GCP.
- As análises são SAST + auditoria de dependências; não há pentest dinâmico.
