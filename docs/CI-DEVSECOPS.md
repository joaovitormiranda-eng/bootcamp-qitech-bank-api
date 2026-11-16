# CI e verificações de segurança — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Documentos relacionados:** [Segurança](SEGURANCA.md) · [Migrações](MIGRACOES.md) · [Arquitetura](ARQUITETURA.md) · [Workflow](../.github/workflows/ci.yml)

O workflow [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (nome: **CI - full test suite**) é a forma reprodutível de executar a suíte completa, porque os testes de integração precisam de dois PostgreSQL, do MockServer e da API rodando ao mesmo tempo. O resultado de cada execução fica na aba [Actions](https://github.com/mohamad347/bootcamp-qitech-bank-api/actions/workflows/ci.yml).

## Sumário

1. [Gatilhos e permissões](#1-gatilhos-e-permissões)
2. [Job `test`](#2-job-test)
3. [Job `migration`](#3-job-migration)
4. [Job `security`](#4-job-security)
5. [Actions utilizadas](#5-actions-utilizadas)
6. [Checks obrigatórios para merge](#6-checks-obrigatórios-para-merge)
7. [Limitações](#7-limitações)

## 1. Gatilhos e permissões

- `push` para `main`, `pull_request` para `main` e `workflow_dispatch` (execução manual).
- `permissions: contents: read` no nível do workflow. Nenhum job escreve no repositório, cria releases ou comenta em PRs, e nenhum usa segredos.
- Os três jobs rodam em `ubuntu-latest` e são independentes entre si.

## 2. Job `test`

Executa toda a suíte pytest contra uma stack provisionada no runner:

| Serviço | Imagem | Porta | Papel |
|---|---|---|---|
| `postgres_api` | `postgres:16` | `127.0.0.1:5432` | Banco `bootcamp` da API; recebe `database/database.sql` via `psql` |
| `postgres_test` | `postgres:16` | `127.0.0.1:5433` | Banco descartável `bootcamp_test` para os testes de schema |
| `mockserver` | `mockserver/mockserver:8.0.0` | `127.0.0.1:1080` | Provedor de análise simulado, configurado pelos próprios testes |

Os dois PostgreSQL são **instâncias separadas** porque fixtures de suporte comparam o `system_identifier` de cada cluster e exigem que o banco da API e o de testes não sejam o mesmo servidor.

Passos: instala `requirements-dev.txt`, aguarda os bancos e o MockServer, carrega o schema, sobe a API com uvicorn em `127.0.0.1:3001`, espera `/health_check` responder `204` e roda:

```bash
python -m pytest -q -ra --junitxml=pytest-results.xml
```

Não há `continue-on-error`, `--maxfail` nem skip/xfail artificiais. O relatório JUnit e o `api.log` são publicados como artefato `pytest-results` com retenção de 7 dias; em caso de falha, o log da API também é impresso no job.

## 3. Job `migration`

Valida a migração versionada `0001` (ver [MIGRACOES.md](MIGRACOES.md)) em um PostgreSQL próprio (`postgres_migration`, porta `5434`), sem relação com o job `test`:

1. Instala o schema anterior à normalização (`tests/integration/database/legacy_schema.sql`).
2. Insere dados representativos: clientes PF e PJ, contas com saldo, eventos de status, um depósito e uma transferência com lançamentos.
3. Registra um *snapshot* com contagem de clientes, transações e lançamentos e a soma dos saldos.
4. Aplica `database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql`.
5. Compara o *snapshot* posterior com o anterior e verifica que `entry_key` está preenchido e é único, que nenhuma FK nova ficou nula e que as lookups existem.
6. Reexecuta a migração e confirma que nada mudou e que as lookups não duplicaram.
7. Aplica `0001_ROLLBACK.sql` e confirma que a estrutura anterior voltou, que contagens e soma de saldos são iguais ao *snapshot* inicial e que o texto de `direction`, `entry_type` e `transaction_type` foi restaurado.

Cada verificação usa `ON_ERROR_STOP=1` e `RAISE EXCEPTION` ou `diff`, então qualquer divergência falha o job.

## 4. Job `security`

Analisa código e dependências sem banco nem MockServer. As ferramentas são instaladas com versões fixas: `bandit==1.9.4` e `pip-audit==2.10.1`.

| Passo | Comando | Efeito |
|---|---|---|
| Bandit | `bandit -r src -ll` | Análise estática de `src/`. `-ll` reporta apenas achados de severidade média ou alta; qualquer um deles falha o job |
| pip-audit | `pip-audit -r requirements.txt` e `pip-audit -r requirements-dev.txt` | Consulta advisories conhecidas para as dependências resolvidas; uma vulnerabilidade encontrada ou uma falha da própria auditoria falha o job |

Os dois passos rodam sem `continue-on-error` e sem `|| true`, e o pip-audit não usa `--ignore-vuln`.

O que esses resultados significam:

- Um Bandit sem achados indica que as regras do Bandit, com o piso de severidade configurado, não encontraram padrões inseguros em `src/`. Não cobre lógica de negócio, autorização nem achados de severidade baixa.
- Um pip-audit limpo vale para a base de advisories consultada no momento da execução. Uma vulnerabilidade publicada depois pode fazer o mesmo commit falhar numa execução futura; nesse caso, a dependência afetada precisa ser atualizada.

## 5. Actions utilizadas

Actions oficiais fixadas por SHA completo, com a versão no comentário. Todas declaram runtime Node.js 24.

| Action | SHA | Versão |
|---|---|---|
| `actions/checkout` | `fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09` | v5.1.0 |
| `actions/setup-python` | `ece7cb06caefa5fff74198d8649806c4678c61a1` | v6.3.0 |
| `actions/upload-artifact` | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | v7.0.2 |

## 6. Checks obrigatórios para merge

A existência de um job no workflow **não** o torna obrigatório para merge. Isso depende da proteção de branch ou de rulesets configurados nas configurações do repositório, que não fazem parte do código.

Para conferir quais checks são exigidos na `main`, um administrador do repositório pode abrir **Settings → Rules → Rulesets** e **Settings → Branches**, e verificar em *Require status checks to pass* se `test`, `migration` e `security` estão listados.

## 7. Limitações

- O CI prova o comportamento no ambiente do runner do GitHub. Este repositório não tem pipeline de deploy.
- As verificações de segurança são análise estática e auditoria de dependências; não há teste de invasão dinâmico nem varredura de imagens de container.
- PRs abertos a partir de forks podem exigir aprovação de um mantenedor antes da primeira execução do workflow, conforme a política do repositório.
