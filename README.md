# BaaS Simplificado

[![CI - full test suite](https://github.com/mohamad347/bootcamp-qitech-bank-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mohamad347/bootcamp-qitech-bank-api/actions/workflows/ci.yml)

**API REST de Banking as a Service (BaaS)** desenvolvida para o **Bootcamp QI Tech 2026** por **João Vitor Miranda Sousa** e **Mohamad Ahmad Barakat**.

O projeto implementa o ciclo bancário básico de uma plataforma parceira: cadastro de pessoas físicas (PF) e jurídicas (PJ), análise cadastral, abertura e gerenciamento de contas, depósitos, transferências e consulta de extrato. A solução prioriza **consistência financeira, integridade dos estados, idempotência, concorrência e rastreabilidade**.

> **Projeto acadêmico.** Esta é uma API de referência validada por testes automatizados e CI. Não é um serviço implantado em produção, e este repositório não contém infraestrutura de deploy.

## Sumário

- [Funcionalidades](#funcionalidades)
- [Tecnologias](#tecnologias)
- [Quick start](#quick-start)
- [Configuração](#configuração)
- [Rotas](#rotas)
- [Testes](#testes)
- [Banco de dados e migrações](#banco-de-dados-e-migrações)
- [Integração contínua](#integração-contínua)
- [Documentação técnica](#documentação-técnica)
- [Escopo e limitações](#escopo-e-limitações)
- [Estrutura do repositório](#estrutura-do-repositório)

## Funcionalidades

- **Clientes PF e PJ** com validação de CPF/CNPJ, idade mínima para PF, e-mail normalizado, cadastro inicial `PENDING` e histórico de transições de estado.
- **Análise cadastral** por um provedor HTTP externo, simulado com MockServer no ambiente local e de testes.
- **Uma conta por cliente** durante todo o ciclo de vida, com saldo não negativo e encerramento somente com saldo zero.
- **Depósitos e transferências** em centavos de BRL, com tarifa de transferência calculada no servidor (PF: 0,50%, mín. R$ 0,50, máx. R$ 10,00; PJ: 1,00%, mín. R$ 1,00, máx. R$ 15,00; arredondamento `HALF_UP`).
- **Idempotência** obrigatória na R07 pelo header `Idempotency-Key` (UUID) associado ao SHA-256 da intenção: retentativas idênticas não duplicam movimentações e reutilizações conflitantes são rejeitadas.
- **Concorrência controlada** com locks pessimistas ordenados por `ACCOUNT.id`, revalidação de saldo sob lock e `COMMIT` único por operação.
- **Extrato paginado** por lançamento (principal e tarifa), com ordenação determinística e filtros de data no timezone do cliente.

## Tecnologias

| Componente | Tecnologia |
|---|---|
| API | Python 3.11, FastAPI, uvicorn |
| Persistência | PostgreSQL 16, SQLAlchemy |
| Validação de entrada | JSON Schema |
| Integração de análise | HTTP; MockServer 8.0.0 no ambiente local e de testes |
| Ambiente | Docker e Docker Compose |
| Testes | pytest |
| CI | GitHub Actions (jobs `test`, `migration` e `security`) |

## Quick start

Pré-requisito: **Docker com Compose**.

```bash
git clone https://github.com/mohamad347/bootcamp-qitech-bank-api.git
cd bootcamp-qitech-bank-api
docker compose up -d --build --wait
curl -i http://localhost:3000/health_check
```

O `health_check` responde **HTTP 204 No Content**, sem corpo. A API fica em `http://localhost:3000`. Para ver o nome do serviço:

```bash
curl -s http://localhost:3000/
# {"service":"bootcamp-api"}
```

Exemplo de rota protegida, usando o token local de demonstração:

```bash
curl -i -X POST http://localhost:3000/client \
  -H "INTERNAL-TOKEN: default_token" \
  -H "Content-Type: application/json" \
  -d '{"client_type":"INDIVIDUAL","email":"cliente@example.com","cpf":"52998224725","full_name":"Cliente Exemplo","birth_date":"1995-05-10","timezone":"America/Sao_Paulo"}'
```

O Compose cria o schema a partir de `database/database.sql` **somente no primeiro provisionamento de um volume vazio**. Para um volume que já existia antes da versão atual do schema, veja [Banco de dados e migrações](#banco-de-dados-e-migrações).

Para consultar logs ou parar os serviços sem remover volumes:

```bash
docker compose logs -f api
docker compose stop
```

## Configuração

O quick start não exige arquivo `.env`: o `docker-compose.yml` tem defaults locais. Para sobrescrever valores, copie o exemplo versionado:

```bash
cp .env.example .env
```

Variáveis principais (lista completa em [`.env.example`](.env.example)):

| Variável | Default local | Uso |
|---|---|---|
| `INTERNAL_TOKEN` | `default_token` | Segredo compartilhado exigido no header `INTERNAL-TOKEN` das rotas R01–R09 |
| `APP_ENV` | `local` (no Compose) | Habilita a documentação OpenAPI apenas quando é `local` ou `test` |
| `API_PORT` | `3000` | Porta publicada da API principal |
| `ANALYSIS_PROVIDER_URL` | `http://mockserver:1080` | URL do provedor de análise cadastral |
| `ANALYSIS_PROVIDER_TIMEOUT` | `5` | Timeout, em segundos, da chamada ao provedor |
| `DB_LOCK_TIMEOUT_MS` / `DB_STATEMENT_TIMEOUT_MS` | `3000` / `10000` | Timeouts aplicados a cada conexão PostgreSQL |

> `default_token` e as credenciais `bootcamp:bootcamp` servem **somente para ambiente local**. Nunca coloque credenciais reais em arquivos versionados.

Com `APP_ENV=local` ou `APP_ENV=test`, a documentação interativa fica em `/docs`, `/redoc` e `/openapi.json` (atrás do `INTERNAL-TOKEN`). Com `APP_ENV` ausente, vazio, `production` ou qualquer outro valor, essas rotas não são registradas. Detalhes em [SEGURANCA.md](docs/SEGURANCA.md).

## Rotas

R01–R09 exigem o header `INTERNAL-TOKEN`; R10 é pública.

| ID | Método | Endpoint | Função |
|---|---|---|---|
| R01 | `POST` | `/client` | Cadastro de cliente PF/PJ |
| R02 | `GET` | `/client/{client_key}` | Consulta cadastral |
| R03 | `POST` | `/client/{client_key}/analysis` | Análise cadastral pelo provedor externo |
| R04 | `POST` | `/client/{client_key}/account` | Abertura da conta |
| R05 | `GET` | `/account/{account_key}` | Consulta de conta e saldo |
| R06 | `PATCH` | `/account/{account_key}` | Alteração do estado da conta |
| R07 | `POST` | `/account/{account_key}/transaction` | Depósito ou transferência idempotente |
| R08 | `GET` | `/account/{account_key}/transactions` | Extrato paginado |
| R09 | `PATCH` | `/client/{client_key}` | Alteração do estado do cliente |
| R10 | `GET` | `/health_check` | Liveness HTTP (`204`) |

Payloads, respostas, códigos de erro e exemplos estão em [docs/ROTAS.md](docs/ROTAS.md).

## Testes

A suíte cobre contratos HTTP, regras de domínio, persistência, estados, idempotência, concorrência, atomicidade, rollback, extrato, schema e migração. Os testes de integração precisam da API, de dois PostgreSQL fisicamente separados e do MockServer ao mesmo tempo.

### Local, com a stack do Compose

`docker compose up -d --build --wait` também sobe uma stack isolada para testes, publicada apenas em `127.0.0.1`:

| Serviço | Porta no host | Uso |
|---|---|---|
| `api_test` | `3001` | API com `APP_ENV=test` |
| `db_api_test` | `55433` | Banco da API de testes |
| `db_schema_test` | `55432` | Banco descartável `bootcamp_test` para testes de schema |
| `mockserver_test` | `1081` | MockServer controlado pelos testes |

Esses valores já são os defaults de [`tests/conftest.py`](tests/conftest.py), portanto não é preciso exportar variáveis:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

No Windows (PowerShell), use `py -3.11 -m venv .venv` e `.\.venv\Scripts\python.exe`.

> **Atenção:** os testes de schema executam `DROP SCHEMA public CASCADE` no banco apontado por `TEST_DATABASE_URL`. `tests/utils/db_utils.py` só permite essa operação em bancos cujo nome termina em `_test`. Nunca aponte as variáveis de teste para um banco com dados reais.

Sem a stack, apenas os testes unitários rodam de ponta a ponta:

```bash
.venv/bin/python -m pytest tests/unit -q
```

### Contagem de testes

- **Entrega de 12/10/2026:** a equipe reportou `442 passed in 64.58s` em execução local.
- **Estado atual:** o run [`43786395203`](https://github.com/mohamad347/bootcamp-qitech-bank-api/actions/runs/43786395203) da `main` (merge do PR #46) terminou com **`562 passed`** no job `test`, com `migration` e `security` em `success`.

A aba [Actions](https://github.com/mohamad347/bootcamp-qitech-bank-api/actions/workflows/ci.yml) é a fonte autoritativa para execuções posteriores.

## Banco de dados e migrações

O schema tem **15 tabelas**: 8 de domínio e 7 de lookup (`client_status`, `account_status`, `client_type`, `transaction_type`, `transaction_direction`, `entry_type`, `actor_type`). Enumerações são referenciadas por chave estrangeira, e `transaction_entry` tem a chave pública `entry_key`. O DDL executável é [`database/database.sql`](database/database.sql); o modelo comentado está em [docs/ERD.md](docs/ERD.md).

- **Volume novo:** o Compose aplica `database/database.sql` automaticamente.
- **Volume existente com o schema anterior:** reiniciar ou reconstruir containers **não** aplica migrações. Faça backup e aplique a migração versionada `0001` conforme [docs/MIGRACOES.md](docs/MIGRACOES.md). Não apague volumes com dados para "atualizar" o schema.

## Integração contínua

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) roda em `push` e `pull_request` para `main` e em `workflow_dispatch`, com três jobs independentes:

| Job | O que valida |
|---|---|
| `test` | Suíte pytest completa contra dois PostgreSQL 16 separados, MockServer e a API viva |
| `migration` | Migração `0001` sobre um banco legado populado, idempotência da reexecução e rollback com preservação dos dados de negócio |
| `security` | Bandit (`bandit -r src -ll`) e pip-audit sobre `requirements.txt` e `requirements-dev.txt`, ambos bloqueantes no job |

Detalhes em [docs/CI-DEVSECOPS.md](docs/CI-DEVSECOPS.md).

## Documentação técnica

| Documento | Conteúdo |
|---|---|
| [RFC](docs/RFC.md) · [PDF](docs/RFC.pdf) | RFC v2.1 original: problema, solução, rotas, modelo de dados e fluxos |
| [ROTAS](docs/ROTAS.md) | Contratos HTTP R01–R10, erros e exemplos |
| [ERD](docs/ERD.md) | Modelo relacional de 15 tabelas, chaves, índices e decisões |
| [FLUXOS](docs/FLUXOS.md) | Diagramas dos fluxos cadastrais, financeiros, idempotência e concorrência |
| [ARQUITETURA](docs/ARQUITETURA.md) | Camadas, middlewares, fronteira transacional e locks |
| [SEGURANCA](docs/SEGURANCA.md) | Modelo de confiança, controles e riscos residuais |
| [CI-DEVSECOPS](docs/CI-DEVSECOPS.md) | Jobs de CI, scanners e limites |
| [MIGRACOES](docs/MIGRACOES.md) | Banco novo × existente, migração 0001, backup e rollback |

## Escopo e limitações

- **Uma plataforma parceira por implantação**, no Brasil e em BRL. Não há autenticação de usuário final, autorização por titular nem multi-tenancy.
- Fora do escopo: PIX, TED, boletos, saques, estornos, KYC comercial real e contabilidade completa por partidas dobradas.
- O provedor de análise é simulado com MockServer; não há integração com um fornecedor real.
- Rate limiting, TLS e usuário de banco com privilégios mínimos dependem da infraestrutura de implantação, que não faz parte deste repositório.

Os riscos residuais estão em [docs/SEGURANCA.md](docs/SEGURANCA.md#riscos-residuais).

## Estrutura do repositório

```text
bootcamp-qitech-bank-api/
├── .github/workflows/ci.yml   # CI: jobs test, migration e security
├── src/                       # API (resources, controllers, services, repositories, models...)
├── database/
│   ├── database.sql           # Schema PostgreSQL atual (15 tabelas)
│   └── migrations/            # Migração 0001, rollback e instruções
├── mockserver/                # Imagem e expectativas do provedor de análise local
├── tests/                     # Testes unitários, de integração e de banco
├── docs/                      # RFC, contratos, modelo de dados, fluxos e guias técnicos
├── docker-compose.yml         # Stack principal e stack isolada de testes
├── compose.test.yml           # Apenas o banco de testes de schema
├── requirements.txt           # Dependências da aplicação
└── requirements-dev.txt       # Dependências de desenvolvimento e testes
```

---

**Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Projeto acadêmico:** Bootcamp QI Tech 2026 — BaaS Simplificado. Licença: [MIT](LICENSE).
