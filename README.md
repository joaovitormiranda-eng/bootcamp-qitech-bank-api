# BaaS Simplificado

**API REST de Banking as a Service (BaaS)** desenvolvida para o **Bootcamp QI Tech 2026** por **João Vitor Miranda Sousa** e **Mohamad Ahmad Barakat**.

O projeto implementa o ciclo bancário básico de uma plataforma parceira: cadastro de pessoas físicas (PF) e jurídicas (PJ), análise cadastral, abertura e gerenciamento de contas, depósitos, transferências e consulta de extrato. A solução prioriza **consistência financeira, integridade dos estados, idempotência, concorrência e rastreabilidade**, com desenvolvimento orientado a testes (**TDD — RED → GREEN → REFACTOR**).

> **Entrega (12/10/2026) e evolução P1/P2.** As **10 rotas (R01–R10)** estão integradas à `main`. A evidência reprodutível e autoritativa da suíte completa é o pipeline de **Integração Contínua** (`.github/workflows/ci.yml`). Após as rodadas **P1** (reprodutibilidade, contratos, isolamento de testes, fronteiras de camada e normalização do schema) e **P2** (segurança de dependências, hardening da API e do CI, DevSecOps e cobertura de erros), o último run verde é [`43735514804`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43735514804), com os jobs `test`, `migration` e `security` em `success` e **554 testes aprovados** (`554 passed`). O resultado verde deve ser lido na aba **Actions** do repositório — a fonte autoritativa. Veja [CI / Integração contínua](#ci--integração-contínua) e o [histórico de auditorias](docs/AUDITORIAS.md).
>
> *Nota histórica:* a entrega inicial reportava **442 testes** (run `43474403332`); o número cresceu para 554 com os testes adicionados em P1/P2. Referências a "442" preservadas em documentos de auditoria descrevem a baseline daquele momento, não o estado atual.

## Quick start

### Inicialização

Pré-requisito: **somente Docker com Compose**. Para iniciar o projeto desde um clone novo:

```bash
git clone https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api.git
cd bootcamp-qitech-bank-api
docker compose up -d --build --wait
curl -i http://localhost:3000/health_check
```

> O projeto original (upstream) é
> [`mohamad347/bootcamp-qitech-bank-api`](https://github.com/mohamad347/bootcamp-qitech-bank-api);
> os comandos acima usam o fork `joaovitormiranda-eng/bootcamp-qitech-bank-api`.

Não é necessário exportar variáveis, instalar PostgreSQL no host, executar SQL
ou configurar o MockServer. Se o repositório já estiver clonado, basta entrar
na pasta e executar:

```bash
docker compose up -d --build --wait
curl -i http://localhost:3000/health_check
```

O health check retorna **HTTP 204**. A API fica disponível em `http://localhost:3000` e o token local de demonstração é `default_token`, enviado no header `INTERNAL-TOKEN`.

O Compose cria automaticamente o schema de um volume novo a partir de `database/database.sql`, incluindo os índices da R08, e sobe o PostgreSQL e o Analysis Provider necessários.

## Documentação

| Documento | Finalidade |
|---|---|
| [RFC — Markdown](docs/RFC.md) | Contexto, solução proposta, decisões arquiteturais, rotas, modelo de dados e principais fluxos |
| [RFC — PDF](docs/RFC.pdf) | Versão de apresentação da RFC, em A4 |
| [Modelo de Dados — ERD](docs/ERD.md) | Entidades, relacionamentos, integridade referencial e decisões de persistência |
| [Contratos da API — ROTAS](docs/ROTAS.md) | Headers, parâmetros, payloads, respostas, códigos HTTP e regras por endpoint |
| [Fluxos de Negócio — FLUXOS](docs/FLUXOS.md) | Diagramas Mermaid de sucesso, falha, transações, concorrência e idempotência |
| [Arquitetura em camadas — ARQUITETURA](docs/ARQUITETURA.md) | Camadas (resources, middlewares, controllers, services, repositories, connectors, banco), diagramas de componentes e de sequência |
| [Segurança e modelo de confiança — SEGURANCA](docs/SEGURANCA.md) | `INTERNAL-TOKEN`, single-tenant, comparação em tempo constante, riscos residuais aceitos do MVP |
| [CI e DevSecOps — CI-DEVSECOPS](docs/CI-DEVSECOPS.md) | Jobs `test`, `migration` e `security`; Bandit e pip-audit bloqueantes; clusters PostgreSQL isolados |
| [Migrações de schema — MIGRACOES](docs/MIGRACOES.md) | Schema populado, idempotência da migração e rollback com preservação de dados |
| [Histórico de auditorias — AUDITORIAS](docs/AUDITORIAS.md) | Rodadas P1/P2, decisões, matriz de rastreabilidade documentação↔código e riscos residuais |

**Modelo interativo:** [visualizar o ERD no dbdiagram.io](https://dbdiagram.io/d/ERD-bootcamp-QItech-6abc58be5869425612d24fa6). O esquema físico versionado encontra-se em [`database/database.sql`](database/database.sql).

## Funcionalidades e endpoints

As operações de negócio exigem o header **`INTERNAL-TOKEN`**. A rota de healthcheck é pública.

| ID | Método | Endpoint | Funcionalidade |
|---|---|---|---|
| R01 | `POST` | `/client` | Cadastro de cliente PF/PJ |
| R02 | `GET` | `/client/{client_key}` | Consulta cadastral |
| R03 | `POST` | `/client/{client_key}/analysis` | Análise cadastral por provedor externo simulado |
| R04 | `POST` | `/client/{client_key}/account` | Abertura de conta |
| R05 | `GET` | `/account/{account_key}` | Consulta de conta e saldo |
| R06 | `PATCH` | `/account/{account_key}` | Alteração do estado da conta |
| R07 | `POST` | `/account/{account_key}/transaction` | Depósito e transferência com idempotência |
| R08 | `GET` | `/account/{account_key}/transactions` | Extrato paginado de lançamentos |
| R09 | `PATCH` | `/client/{client_key}` | Alteração do estado cadastral |
| R10 | `GET` | `/health_check` | Verificação de vida da API (`204`, sem autenticação) |

Os contratos completos, com exemplos de requisição e resposta, estão em [`docs/ROTAS.md`](docs/ROTAS.md).

### Regras de negócio relevantes

- **Clientes:** perfis `INDIVIDUAL` e `COMPANY`, documentos validados, cadastro inicial `PENDING` e histórico de mudanças de estado.
- **Contas:** no máximo uma conta por cliente durante todo o ciclo de vida; abertura condicionada ao cliente elegível; saldo não negativo e encerramento somente com saldo zero.
- **Análise cadastral:** integração HTTP com o provedor simulado no ambiente local; revalidação do estado do cliente após a resposta externa.
- **Depósitos e transferências:** valores representados em **centavos de BRL**, com atualizações de saldo e lançamentos persistidos atomicamente.
- **Tarifa de transferência:** calculada no servidor conforme o perfil da conta de origem. Para PF, **0,50%**, mínimo de **R$ 0,50** e máximo de **R$ 10,00**; para PJ, **1,00%**, mínimo de **R$ 1,00** e máximo de **R$ 15,00**, com arredondamento `HALF_UP`.
- **Idempotência da R07:** header obrigatório `Idempotency-Key` (UUID), associado à intenção da operação. Retentativas idênticas não duplicam movimentações; reutilizações conflitantes são rejeitadas.
- **Concorrência financeira:** locks pessimistas ordenados, validação de saldo sob lock e `COMMIT` único; falhas antes da confirmação provocam `ROLLBACK`.
- **Extrato R08:** paginação por **lançamento** (`TRANSACTION_ENTRY`), incluindo principal e tarifa, ordenação determinística e filtros por datas civis interpretadas no timezone do cliente.

O produto atende **uma plataforma parceira por implantação**, no Brasil e em **BRL**. PIX, TED, boletos, saques, KYC comercial real, multi-tenancy e contabilidade completa por partidas dobradas estão fora do escopo deste MVP.

## Tecnologias e arquitetura

| Componente | Tecnologia / responsabilidade |
|---|---|
| API | Python, FastAPI |
| Persistência | PostgreSQL, SQLAlchemy |
| Validação de entrada | JSON Schema |
| Integração de análise | HTTP e MockServer no ambiente de desenvolvimento/testes |
| Ambiente | Docker e Docker Compose |
| Qualidade | pytest, testes unitários e de integração, TDD |

```text
Requisição HTTP
      |
      v
middlewares  (request_context -> request_logger -> internal_token -> session_manager)
      |
      v
resources + validação JSON Schema
      |
      v
controllers (regras de negócio e fronteira transacional / COMMIT único)
      |
      v
services (puro: tarifa HALF_UP, hash SHA-256 da intenção)
      |
      v
repositories + models (PostgreSQL, SQLAlchemy)   connectors (HTTP externo: Analysis Provider)
      |
      v
DTOs / projeções de resposta
      |
      v
Resposta HTTP
```

O detalhamento de cada camada, com diagramas de componentes e de sequência, está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

O banco possui **15 tabelas**: **8 de domínio** (cadastro, contas e movimentações financeiras) e **7 de lookup** (`client_status`, `account_status`, `client_type`, `transaction_type`, `transaction_direction`, `entry_type`, `actor_type`). As tabelas de lookup foram introduzidas na rodada **P1-D** (COD-06) para substituir enumerações `VARCHAR + CHECK IN (...)` por integridade referencial via `FOREIGN KEY`; a representação textual externa continua sendo o `enumerator`, resolvido pela camada ORM. Os históricos de mudança de estado são persistidos separadamente dos estados atuais, enquanto `financial_transaction` e `transaction_entry` registram as operações e seus efeitos (este último com `entry_key UUID` público, também de P1-D/COD-05). Consulte o [ERD](docs/ERD.md) para o modelo completo, cardinalidades e restrições.

## Executar localmente com Docker

**Pré-requisitos:** Docker com Compose. Para executar a suíte de testes fora dos containers, também é necessário **Python 3.11 ou superior**.

Clone o repositório e entre na pasta do projeto:

```powershell
git clone https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api.git
cd bootcamp-qitech-bank-api
```

> O projeto original (upstream) é
> [`mohamad347/bootcamp-qitech-bank-api`](https://github.com/mohamad347/bootcamp-qitech-bank-api);
> o comando acima usa o fork `joaovitormiranda-eng/bootcamp-qitech-bank-api`.

Se necessário, crie o arquivo de configuração local a partir do exemplo versionado:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Inicie os serviços definidos no Compose principal:

```powershell
docker compose up -d --build --wait
docker compose ps
```

Verifique o funcionamento HTTP:

```powershell
curl.exe -i http://localhost:3000/health_check
```

**Resultado esperado:** `HTTP 204 No Content`, sem corpo. Esse endpoint verifica a resposta HTTP do processo, **não** a disponibilidade do PostgreSQL.

Para consultar logs ou parar os serviços sem remover volumes:

```powershell
docker compose logs -f api
docker compose stop
```

As portas locais de referência são **3000** (API), **5432** (PostgreSQL principal) e **1080** (MockServer, quando habilitado). Os valores de `.env.example` e as credenciais de desenvolvimento são destinados **somente ao ambiente local**. O script [`database/database.sql`](database/database.sql) inicializa o esquema no primeiro provisionamento de um volume PostgreSQL vazio; reconstruir um container não reinicializa automaticamente um volume persistente.

## CI / Integração contínua

[![CI - full test suite](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/workflows/ci.yml)

O workflow [`.github/workflows/ci.yml`](.github/workflows/ci.yml) é a forma
**sancionada e reprodutível** de executar a suíte completa (atualmente **554
testes**: unitários, integração HTTP e esquema). A cada `push` e `pull_request`
ele provisiona, em runners `ubuntu-latest`, toda a infraestrutura que os testes
exigem e executa **três jobs** — `test`, `migration` e `security` — detalhados em
[docs/CI-DEVSECOPS.md](docs/CI-DEVSECOPS.md). O job `test` executa `pytest` como
único portão de aprovação, sobre:

- **PostgreSQL** (`postgres:16`) em **dois clusters fisicamente separados**:
  `bootcamp` (API) em `127.0.0.1:5432` e `bootcamp_test` (esquema/testes) em
  `127.0.0.1:5433`. Precisam ser instâncias distintas porque as fixtures de
  suporte comparam o `system_identifier` (único por cluster físico) e exigem que
  o banco da API e o banco de testes estejam em servidores diferentes;
  `database/database.sql` é carregado em `bootcamp`.
- **MockServer** (`mockserver/mockserver:8.0.0`) como provedor cadastral simulado;
  os testes da R03 configuram as expectativas em tempo de execução pela API de
  controle.
- **API viva** via `uvicorn app:app` em `127.0.0.1:3001`, aguardada até
  `/health_check` responder **204** antes de rodar a suíte.

Além de `test`, o workflow executa:

- **`migration`** — valida a migração de schema **populado** (P1-D) em um cluster
  PostgreSQL efêmero dedicado: aplica `database/migrations/0001_*.sql` sobre um
  schema legado com dados, confere contagens/saldos antes/depois, idempotência e
  rollback com preservação de dados. Ver [docs/MIGRACOES.md](docs/MIGRACOES.md).
- **`security`** (DevSecOps, P2) — roda **Bandit** (SAST, bloqueante em 0 achados)
  e **pip-audit** (auditoria de dependências, **bloqueante** sobre
  `requirements.txt` e `requirements-dev.txt`). Ver
  [docs/CI-DEVSECOPS.md](docs/CI-DEVSECOPS.md).

**A evidência verde autoritativa é a execução do workflow na aba Actions do
repositório**, não uma garantia independente de ambiente. O último run verde da
`main` é [`43735514804`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43735514804),
com `test`, `migration` e `security` em `success` e **`554 passed`** no job
`test`. Nenhum resultado verde foi fabricado neste README: o número de testes
aprovados é o lido no log do GitHub Actions, e a aba
[**Actions**](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/workflows/ci.yml)
permanece a fonte autoritativa. O artefato `pytest-results` publicado pelo job
`test` contém o relatório JUnit (`pytest-results.xml`) e o `api.log`
(retenção de 7 dias).

Localmente, a suíte completa continua dependendo de **Docker**, conforme descrito
na seção abaixo. Sem Docker (ou sem PostgreSQL + MockServer + API disponíveis no
host), apenas os testes unitários isolados rodam de ponta a ponta:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/unit -q
```

## Executar os testes

A suíte inclui testes de contrato HTTP, regras de domínio, persistência, estados, idempotência, concorrência, rollback, movimentações financeiras e extrato.

> **Docker é obrigatório para a execução local completa.** Os testes de
> integração HTTP exigem a API viva, o PostgreSQL e o MockServer no ar ao mesmo
> tempo; a stack do Compose provê exatamente esses serviços. Para uma execução
> reprodutível sem configurar a infraestrutura à mão, prefira o pipeline de CI
> descrito em [CI / Integração contínua](#ci--integração-contínua).

### 1. Instalar as dependências de desenvolvimento (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

No Linux/macOS, substitua a criação do ambiente por `python3.11 -m venv .venv` e utilize `.venv/bin/python` nos comandos seguintes.

### 2. Subir o PostgreSQL isolado para testes de esquema

Os testes de esquema usam uma instância separada: **não aponte `TEST_DATABASE_URL` para o banco principal**.

```powershell
$env:TEST_DB_PORT = "5433"
docker compose -f compose.test.yml up -d --build --wait
$env:TEST_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@127.0.0.1:5433/bootcamp_test"
```

> **Cuidado:** os testes em `tests/integration/database/` podem recriar o schema `public` **do banco de testes**. Nunca utilize dados reais ou a URL do banco principal nessa configuração.

### 3. Executar a regressão

Com os serviços necessários disponíveis:

```powershell
$env:SERVER_LOCALHOST = "127.0.0.1"
$env:MOCKSERVER_URL = "http://127.0.0.1:1080"
$env:TEST_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@127.0.0.1:5433/bootcamp_test"

.\.venv\Scripts\python.exe -m pytest -q
```

Para executar somente os testes físicos do esquema:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/integration/database -q
```

No Linux/macOS, exporte as mesmas variáveis com `export` (por exemplo
`export SERVER_LOCALHOST=127.0.0.1`) e use `.venv/bin/python -m pytest -q`. As
variáveis aceitas pela suíte (com os defaults de `tests/conftest.py`) são
`DATABASE_URL`, `TEST_DATABASE_URL`, `ANALYSIS_PROVIDER_URL`, `MOCKSERVER_URL`,
`SERVER_LOCALHOST`, `API_PORT`, `INTERNAL_TOKEN` e `ANALYSIS_PROVIDER_TIMEOUT`.
Elas precisam apontar para os serviços que você subiu. O workflow
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) é a referência exata desse
mapeamento, pois executa o mesmo `pytest` contra uma stack totalmente provisionada.

**Resultado dos testes:** a evidência reprodutível e autoritativa é o workflow de
CI. O último run verde da `main` é
[`43735514804`](https://github.com/joaovitormiranda-eng/bootcamp-qitech-bank-api/actions/runs/43735514804),
com **`554 passed`** no job `test` e `migration`/`security` também em `success`.
Nos runs do job `test`, o banco da API roda em `127.0.0.1:5432` (`bootcamp`) e o
banco descartável de testes em `127.0.0.1:5433` (`bootcamp_test`), em clusters
PostgreSQL **fisicamente separados** — exigência das fixtures que comparam o
`system_identifier` por cluster. Leia o número de testes aprovados e o tempo na
aba **Actions** do repositório, a fonte autoritativa. (Referência histórica: a
baseline inicial do P0 era `442 passed`, run `43474403332`.)

**Isolamento e segurança do reset destrutivo:** o reset de esquema em
`tests/utils/db_utils.py` executa **`DROP SCHEMA public CASCADE`** e recria o
schema a partir de `database/database.sql`. Isso **apaga todas as tabelas** do
banco apontado. Por isso a função só prossegue quando o nome do banco termina em
`_test`, e o `TEST_DATABASE_URL` deve **sempre** apontar para o banco efêmero
`bootcamp_test`, **nunca** para um banco compartilhado, principal ou de produção.
Além disso, certos testes HTTP de integração podem criar **dados exclusivamente de
teste** no banco principal por meio da API; não execute a suíte apontando a
aplicação para um banco com dados reais. Para parar somente o banco de testes:

```powershell
docker compose -f compose.test.yml stop db_test
```

## Estrutura do repositório

```text
bootcamp-qitech-bank-api/
├── .github/
│   └── workflows/
│       └── ci.yml             # Pipeline de CI: jobs test, migration e security
├── src/                       # API, regras de negócio e persistência
│   ├── app.py                 # Composition root (middlewares, rotas, handlers)
│   ├── constants.py           # Config por ambiente; BYPASS_ENDPOINTS; timeouts
│   ├── database.py            # Engine/sessão SQLAlchemy; lock/statement_timeout
│   ├── middlewares/           # request_context, request_logger, internal_token, session_manager
│   ├── resources/             # Camada HTTP (um resource por domínio) + health_check
│   ├── controllers/           # Regras de negócio e fronteira transacional
│   ├── services/              # Puro: transfer_fee (HALF_UP), transaction_hash (SHA-256)
│   ├── repositories/          # Acesso a dados (SQLAlchemy)
│   ├── connectors/            # HTTP externo: rest_connector, client_analysis_connector
│   ├── models/                # ORM (domínio + lookups)
│   ├── dtos/                  # Projeções de resposta
│   ├── errors/                # QIException, catálogo de erros e handlers
│   ├── schemas/               # JSON Schema de validação de entrada
│   └── utils/                 # logger (allowlist), request_context, database_errors
├── database/
│   ├── database.sql           # Esquema PostgreSQL alvo (15 tabelas, pós-P1-D)
│   └── migrations/            # Migração versionada 0001 + ROLLBACK + README
├── tests/                     # Testes unitários, HTTP, integração e banco
├── docs/
│   ├── RFC.md / RFC.pdf       # RFC v2.1 (histórica)
│   ├── ERD.md                 # Modelo de dados (15 tabelas) e decisões
│   ├── ROTAS.md               # Contratos HTTP R01–R10
│   ├── FLUXOS.md              # Fluxos Mermaid e cenários de falha
│   ├── ARQUITETURA.md         # Camadas, componentes e sequências
│   ├── SEGURANCA.md           # Modelo de confiança e riscos residuais
│   ├── CI-DEVSECOPS.md        # Jobs de CI e verificações de segurança
│   ├── MIGRACOES.md           # Migração, idempotência e rollback
│   ├── AUDITORIAS.md          # Histórico P1/P2 e rastreabilidade
│   └── P1*/P2A*               # Relatórios de auditoria por fase (históricos)
├── docker-compose.yml         # Ambiente principal (API + Postgres + MockServer)
├── compose.test.yml           # Banco isolado para testes de esquema
├── requirements.txt / requirements-dev.txt
└── README.md
```

A documentação complementar descreve as decisões e os trade-offs arquiteturais com mais profundidade. **Para conhecer o projeto, comece pela [RFC](docs/RFC.md); para integrar a API, consulte [ROTAS](docs/ROTAS.md); para entender a persistência, veja o [ERD](docs/ERD.md) e os [FLUXOS](docs/FLUXOS.md).**

---

**Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Projeto acadêmico:** Bootcamp QI Tech 2026 — BaaS Simplificado.
