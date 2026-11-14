# P2-A - Auditoria Independente de Cibersegurança

> **Rodada:** P2-A (somente auditoria, sem remediação).
> **Repositório:** `joaovitormiranda-eng/bootcamp-qitech-bank-api` (fork).
> **Branch da auditoria:** `audit/p2a-security-assessment`.
> **Baseline:** `main` no SHA `0c2259916cf46336b5d241e3b68e93423ae3441a` (merge do PR #6).
> **CI de referência:** run verde com os jobs `test` e `migration`; a suíte de referência é **544 testes**.
> **Natureza:** análise estática + leitura de configuração e de histórico Git. Sem teste de invasão dinâmico, sem ação destrutiva, sem uso de credenciais.

Esta auditoria não altera código de produção, testes, SQL, migrações, dependências, Docker, workflows nem configurações do GitHub. O único artefato produzido é este documento.

---

## 1. Resumo executivo

A Bank API é um MVP acadêmico de BaaS com um modelo de confiança explícito na RFC v2.1: **uma plataforma parceira por implantação**, chamador interno confiável, autenticação por um **segredo compartilhado** no header `INTERNAL-TOKEN`, sem autenticação por usuário final e sem multi-tenancy. Lido sob esse modelo, o código tem postura de segurança **boa para o escopo declarado**: não há SQL dinâmico (tudo via ORM parametrizado), os connectors têm timeout obrigatório, os logs são estruturados com allowlist de campos (sem PII/segredo), o reset destrutivo de schema é guardado por sufixo `_test`, a imagem roda como usuário sem privilégio, o `.gitignore`/`.dockerignore` barram segredos e dados, e a concorrência financeira usa locks pessimistas ordenados com commit único.

Nenhum segredo real foi encontrado em arquivos versionados nem no histórico Git acessível: todos os valores de token são o placeholder demonstrativo `default_token`. **O relatório é seguro para publicação como PR documental.**

Os achados materiais são de severidade **média para baixo**, todos coerentes com o que a P1 já havia sinalizado para a P2:

| Severidade | Qtde | Achados |
|---|---|---|
| Crítica | 0 | nenhum |
| Alta | 0 | nenhum |
| Média | 3 | SEC-01 (comparação de token não constante), SEC-02 (`requests` com CVEs conhecidas), SEC-05 (documentação interativa `/docs`,`/redoc`,`/openapi.json` habilitada) |
| Baixa | 4 | SEC-03 (dependências de dev vulneráveis), SEC-04 (sem rate limiting / anti-brute-force), SEC-06 (`/` expõe PID do processo), SEC-07 (sem bound superior em `page` do extrato) |
| Informativa | 5 | SEC-08 a SEC-12 (hardening de CI, pinning por SHA, proteção de branch não verificável, ausência de TLS/segregação de usuário de banco no MVP, falta de token interno no connector de análise) |

Ferramentas que **rodaram de verdade**: `bandit` (0 achados), `pip-audit` (achados reais com advisories verificáveis), `semgrep` com **regras locais** (confirmou SEC-01). Ferramentas **indisponíveis**: gitleaks, trivy, trufflehog (binários Go, não instaláveis), e o ruleset remoto do semgrep (`semgrep.dev` bloqueado pelo proxy, HTTP 403). O sweep de segredos foi feito manualmente e está marcado como tal.

---

## 2. Escopo e metodologia

**Escopo.** Código em `src/`, testes em `tests/`, esquema e migrações em `database/`, Docker (`Dockerfile`, `docker-compose.yml`, `compose.test.yml`, `database/Dockerfile`, `mockserver/`), workflow de CI (`.github/workflows/ci.yml`), arquivos de configuração versionados (`.env.example`, `.gitignore`, `.dockerignore`, `.flake8`, `.gitattributes`), dependências (`requirements.txt`, `requirements-dev.txt`) e o histórico Git acessível (115 commits, branches locais e `remotes/origin/*`).

**Modelo de confiança (fonte autoritativa).** `docs/RFC.md §Contexto` e `docs/ROTAS.md §2.1`: R01–R09 exigem `INTERNAL-TOKEN`; R10 (`/health_check`) é pública; o chamador é a plataforma parceira, confiável; multi-tenancy, PIX/TED/boleto/saque, estorno e KYC comercial real estão fora do escopo. **Consequência metodológica:** a ausência de autenticação por usuário final e a ausência de autorização por titular de conta **não são tratadas como vulnerabilidade**, por decisão explícita de arquitetura (ver §4 STRIDE e §5, discussão de BOLA/IDOR).

**Procedimento.**
1. Leitura integral das camadas (middlewares, resources, controllers, repositories, connectors, errors, utils, services, models, schemas).
2. Rastreamento dos fluxos R01–R10 e dos pontos de decisão financeira (locks, idempotência, hash, HALF_UP).
3. Sweep manual de segredos sobre a árvore versionada e sobre o histórico (`git grep`, `git log -S`, varredura de padrões `AKIA…`, `ghp_…`, `-----BEGIN`).
4. SAST com `bandit`; auditoria de dependências com `pip-audit`; SAST dirigido com `semgrep` usando regra local (registro remoto bloqueado).
5. Segunda passada de revisão para eliminar falsos positivos e separar risco real de escolha legítima de MVP.

**Limites assumidos.** Docker, PostgreSQL (`psql`/`initdb`) e `psycopg2` não estão disponíveis localmente; a suíte completa (544 testes) só roda verde no GitHub Actions. Nenhuma validação dinâmica foi executada. Detalhes em §7.

---

## 3. Inventário dos ativos e fronteiras de confiança

**Ativos protegidos.**
- Dados pessoais: CPF (`individual_client.cpf`), CNPJ (`company_client.cnpj`), nome, data de nascimento, e-mail, timezone.
- Dados financeiros: `account.balance_cents`, lançamentos (`transaction_entry`), transações (`financial_transaction`), tarifas.
- Controle de idempotência: `financial_transaction.request_control_key` (UUID) e `request_hash` (SHA-256).
- Segredo de autenticação: `INTERNAL_TOKEN` (ambiente); `BANKSLIP_API_INTERNAL_TOKEN`.
- Configuração: `DATABASE_URL`, URLs e timeouts de integração.

**Atores.**
- **Plataforma parceira** (chamador externo confiável): porta todos os endpoints R01–R09 com o token.
- **Orquestração/Docker:** consulta `/` e `/health_check` (públicos).
- **Provedor de análise** (MockServer no local/CI): chamado por `src/connectors/client_analysis_connector.py`.
- **GitHub Actions:** executa a suíte com Postgres + MockServer + API viva.

**Fronteiras de confiança (de fora para dentro).**
```
Cliente HTTP (parceiro)
  │  TLS terminado por infra externa (fora do escopo do repo)
  ▼
request_context → request_logger → internal_token (GATE 403) → session_manager
  ▼
resources (validação JSON Schema)  ──►  controllers (regra + transação)
  ▼
repositories (ORM parametrizado) ──► PostgreSQL
  ▼
connectors (HTTP com timeout) ──► Provedor de análise / API de boletos
```
A única fronteira de autenticação é o middleware `internal_token`. Tudo que passa por ele é tratado como plenamente autorizado, coerente com a RFC.

---

## 4. Modelo de ameaças (STRIDE × OWASP API Security)

| STRIDE | Ameaça plausível na implementação | Tratamento atual | Resíduo |
|---|---|---|---|
| **S**poofing | Falsificar o chamador interno sem o token | `internal_token` exige valor exato do ambiente; 403 antes de tocar recurso | Comparação não constante (SEC-01); sem rate limit no brute-force (SEC-04) |
| **T**ampering | Alterar saldo/estado por corrida ou payload forjado | Locks pessimistas ordenados por `account.id`; `CHECK (balance_cents>=0)`; JSON Schema + validação de domínio | Nenhum material no escopo |
| **R**epudiation | Operação sem rastro | `client_status_event`/`account_status_event`; `request_id` propagado; logs estruturados | Logs sem identidade do operador (aceitável no modelo single-tenant) |
| **I**nformation disclosure | Vazar PII/segredo/stack trace | Allowlist de campos de log; erros padronizados `QITxxxxxx` sem stack; `hide_parameters=True` na engine | `/docs` e `/openapi.json` expostos (SEC-05); `/` expõe PID (SEC-06) |
| **D**enial of service | Esgotar recursos | Timeout de conexão, `lock_timeout`, `statement_timeout`; `limit` do extrato limitado a 100 | Sem rate limit (SEC-04); `page` sem teto (SEC-07) |
| **E**levation of privilege | Ganhar poder além do token | Sem papéis internos; usuário de SO sem privilégio na imagem | Usuário de banco único com DDL (SEC-11, aceito no MVP) |

**OWASP API Security (leitura dirigida).**
- **API1 BOLA / API5 BFLA:** no modelo single-tenant da RFC não há titular por usuário; qualquer portador do token é confiável. **Não é vulnerabilidade comprovada** (ver §5). Registrado como premissa a revalidar caso o produto evolua para multi-parceiro.
- **API2 Broken Authentication:** um único segredo compartilhado; SEC-01 e SEC-04 endereçam a higiene desse gate.
- **API3 Property-level:** DTOs projetam apenas campos de resposta; sem mass-assignment (JSON Schema com `additionalProperties:false`).
- **API4 Resource Consumption:** SEC-04/SEC-07.
- **API7 SSRF:** URLs de integração vêm do ambiente, não de entrada do usuário; sem SSRF controlável pelo cliente (ver §5).
- **API8 Security Misconfiguration:** SEC-05, SEC-08..SEC-10.
- **API9 Inventory:** `/openapi.json` e `/docs` habilitados divergem do comentário do código (SEC-05).

---

## 5. Achados confirmados, sanitizados e classificados

Esquema por achado: ID · Categoria · Severidade · Arquivo:linha · Evidência sanitizada · Cenário · Condições de exploração · Impacto · Probabilidade/Confiança · Mitigação · Risco de regressão · Teste de comprovação.

### SEC-01 - Comparação de token não é em tempo constante (timing side-channel)
- **Categoria:** Broken Authentication (OWASP API2) / observação de canal lateral.
- **Severidade:** Média.
- **Local:** `src/middlewares/internal_token.py:27`.
- **Evidência:** `if request.headers.get("INTERNAL-TOKEN") != INTERNAL_TOKEN:`, comparação com `!=`. Confirmado por `semgrep` (regra local `non-constant-time-token-compare`, finding bloqueante na linha 27).
- **Cenário:** um atacante com acesso de rede ao endpoint mede diferenças de tempo de resposta para inferir o token byte a byte.
- **Condições de exploração:** exige medir latência com baixo ruído, muitas tentativas e sem rate limit; a comparação curta de strings em Python torna o sinal pequeno. Risco real **baixo**, mas é higiene barata.
- **Impacto:** recuperação do segredo compartilhado → acesso total às rotas protegidas.
- **Probabilidade/Confiança:** confiança **alta** de que o padrão existe; probabilidade de exploração prática **baixa**.
- **Mitigação:** `hmac.compare_digest(received or "", INTERNAL_TOKEN)` codificando ambos os lados; preservar o 403 e o fluxo de BYPASS_ENDPOINTS.
- **Risco de regressão:** baixo (mesma semântica de aceitação/recusa); risco se a codificação de bytes ou o tratamento de `None` mudar o 403.
- **Teste de comprovação:** R01 autenticação (`tests/integration/client/r01/test_authentication.py`) e `tests/integration/contracts/test_route_contracts.py` continuam verdes (token ausente/ inválido → 403; válido → sucesso).

### SEC-02 - `requests==2.32.3` com vulnerabilidades conhecidas (dependência de produção)
- **Categoria:** Vulnerable & Outdated Components (supply-chain).
- **Severidade:** Média (pela presença em produção; exploração improvável no uso atual).
- **Local:** `requirements.txt` (`requests==2.32.3`).
- **Evidência (pip-audit real):**
  - `PYSEC-2026-1872` (GHSA-9hjg-9r4m-mvj7 / CVE-2024-47081): vazamento de credenciais `.netrc` para terceiros via URL maliciosa. **Fix: 2.32.4**.
  - `PYSEC-2026-2275` (GHSA-gc5v-m9x4-r6x2 / CVE-2026-25645): nome de arquivo previsível em `extract_zipped_paths()`. **Fix: 2.33.0**.
- **Cenário:** uma dependência com CVE entra na imagem de produção.
- **Condições de exploração:** o código **não** usa `.netrc` (nenhum `trust_env`/arquivo netrc no projeto) nem `extract_zipped_paths()`; os connectors montam a URL a partir de `base_url` de ambiente + endpoint fixo, sem URL vinda do usuário. Exploração pelo uso atual **não demonstrada**.
- **Impacto:** teórico no uso atual; relevante como postura de supply-chain.
- **Probabilidade/Confiança:** advisories **confirmadas**; exploração no contexto **improvável**.
- **Mitigação:** atualizar para `requests>=2.33.0` (cobre ambas) em PR controlado.
- **Risco de regressão:** baixo (API estável do `requests`); revalidar connectors (R03) e timeouts.
- **Teste de comprovação:** suíte R03 (contrato/decisões do provedor) verde; novo `pip-audit -r requirements.txt` sem achados para `requests`.

### SEC-03 - Dependências de desenvolvimento com vulnerabilidades conhecidas
- **Categoria:** Vulnerable Components (apenas dev/CI).
- **Severidade:** Baixa.
- **Local:** `requirements-dev.txt`.
- **Evidência (pip-audit real):**
  - `pytest==7.4.4` → `PYSEC-2026-1845` (CVE-2025-71176): diretório `/tmp/pytest-of-{user}` previsível em UNIX, DoS/escalonamento local. **Fix: 9.0.3**.
  - `python-dotenv==1.0.1` → `PYSEC-2026-2270` (CVE-2026-28684): `set_key()`/`unset_key()` seguem symlink ao reescrever `.env`. **Fix: 1.2.2**.
  - `requests` (herdado de `-r requirements.txt`): mesmas CVEs do SEC-02.
- **Cenário:** vetores **locais**, exigindo acesso ao host de teste/CI; não afetam o serviço em produção (dependências não entram na imagem: ver `requirements-dev.txt` e `Dockerfile`, que instala só `requirements.txt`).
- **Condições de exploração:** atacante local no runner; o projeto não chama `set_key`/`unset_key`.
- **Impacto:** baixo; superfície restrita ao ambiente de teste.
- **Probabilidade/Confiança:** advisories confirmadas; impacto prático baixo.
- **Mitigação:** bump controlado de `pytest`/`python-dotenv` (atenção: `pytest` 7 para 9 é major; validar a suíte inteira antes).
- **Risco de regressão:** **médio** para `pytest` (salto de major pode exigir ajustes de fixtures/API); baixo para `python-dotenv`.
- **Teste de comprovação:** suíte completa verde no CI (544) após o bump; `pip-audit -r requirements-dev.txt` limpo.

### SEC-04 - Ausência de rate limiting / proteção anti-brute-force no gate de token
- **Categoria:** Unrestricted Resource Consumption / Broken Authentication.
- **Severidade:** Baixa (no modelo de confiança da RFC).
- **Local:** `src/middlewares/internal_token.py` (gate); nenhum middleware de throttling em `src/app.py`.
- **Evidência:** o log registra 403 em WARNING justamente para detectar “mil tentativas seguidas” (comentário em `src/app.py`), mas não há bloqueio automático nem contador.
- **Cenário:** adivinhação do token por força bruta, ou flood de requisições.
- **Condições de exploração:** acesso de rede; sem WAF/limite na frente.
- **Impacto:** facilita SEC-01 e DoS de aplicação.
- **Probabilidade/Confiança:** confiança alta na ausência; impacto depende da infra à frente (normalmente há WAF/gateway, fora do repo).
- **Mitigação:** throttling por origem/token na borda (infra) ou middleware; alerta sobre taxa de 403. **Decisão de infra, não necessariamente de código**; pode ser risco residual aceito.
- **Risco de regressão:** médio se implementado em código (pode afetar testes de concorrência); baixo se tratado na borda.
- **Teste de comprovação:** teste negativo de N tentativas → bloqueio/alerta, sem quebrar R01–R10.

### SEC-05 - Documentação interativa e OpenAPI habilitadas (divergência de configuração)
- **Categoria:** Security Misconfiguration / Improper Inventory Management (OWASP API8/API9).
- **Severidade:** Média (exposição de superfície e de inventário).
- **Local:** `src/app.py` (`docs_url="/docs"`, `redoc_url="/redoc"`, `openapi_url="/openapi.json"`).
- **Evidência:** o comentário imediatamente acima afirma “Os três None desligam a documentação automática… aqui elas não existem”, mas os três parâmetros estão **habilitados**. Como não há BYPASS para esses caminhos, eles exigem token; ainda assim o inventário de rotas fica acessível a qualquer portador do token e o comentário induz a conclusão errada em auditoria.
- **Cenário:** exposição não intencional do mapa de endpoints/esquemas.
- **Condições de exploração:** acesso autenticado (ou público, caso alguma infra à frente libere `/docs`).
- **Impacto:** facilita reconhecimento; baixo valor ofensivo direto.
- **Probabilidade/Confiança:** **alta** (observável no código); a divergência comentário↔código é o ponto principal.
- **Mitigação:** decidir deliberadamente: desligar em produção (`docs_url=None, redoc_url=None, openapi_url=None`) por `APP_ENV`, ou manter e corrigir o comentário. Não é cosmético: alinha configuração, comentário e intenção.
- **Risco de regressão:** baixo; nenhuma rota de negócio depende de `/docs`.
- **Teste de comprovação:** teste que `/openapi.json` responde o esperado conforme `APP_ENV` (404 em prod se desligado).

### SEC-06 - `GET /` expõe o PID do processo
- **Categoria:** Information Disclosure.
- **Severidade:** Baixa.
- **Local:** `src/resources/health_check.py:14` (`"id": str(os.getpid())`).
- **Evidência:** a rota pública `/` devolve `{"service": ..., "id": "<pid>"}`.
- **Cenário:** vazamento de detalhe interno do runtime.
- **Condições de exploração:** rota pública (BYPASS), sem token.
- **Impacto:** mínimo; PID por si não habilita ataque.
- **Probabilidade/Confiança:** alta de que expõe; impacto baixo.
- **Mitigação:** remover o PID da resposta pública (manter só o nome do serviço).
- **Risco de regressão:** baixo; verificar se nenhum teste depende do campo `id`.
- **Teste de comprovação:** contrato de `/` sem PID; `/health_check` segue 204.

### SEC-07 - `page` do extrato sem limite superior
- **Categoria:** Unrestricted Resource Consumption (DoS por paginação profunda).
- **Severidade:** Baixa.
- **Local:** `src/schemas/get_account_transactions.json` (`page` = `^[1-9][0-9]*$`, sem teto); offset calculado em `src/controllers/transaction_controller.py` (`(page-1)*limit`).
- **Evidência:** `limit` é limitado a 100 pelo schema, mas `page` aceita qualquer inteiro positivo, gerando `OFFSET` arbitrariamente grande.
- **Cenário:** requisições com `page` enorme forçam offsets caros no PostgreSQL.
- **Condições de exploração:** chamador autenticado; mitigado em parte por `statement_timeout`.
- **Impacto:** custo de query elevado; limitado pelo timeout de statement.
- **Probabilidade/Confiança:** média de existência; impacto baixo dado o timeout.
- **Mitigação:** limitar `page` por regex/validação ou adotar keyset pagination (preservar semântica e ordenação determinística do extrato, invariante §11).
- **Risco de regressão:** médio se mudar a semântica de paginação; baixo se só adicionar teto.
- **Teste de comprovação:** R08 paginação continua verde; novo teste de `page` fora do teto → 400.

### SEC-08 - CI: ausência de `permissions` explícitas para o `GITHUB_TOKEN`
- **Categoria:** CI/CD Security.
- **Severidade:** Informativa.
- **Local:** `.github/workflows/ci.yml` (sem bloco `permissions:`).
- **Evidência:** o workflow não declara `permissions`, herdando o default do repositório. Dispara em `push` e `pull_request` para `main`.
- **Mitigação:** adicionar `permissions: contents: read` no topo (least privilege). PRs de forks já recebem token read-only por padrão, mas a declaração torna a postura explícita e resistente a mudança de default.
- **Teste de comprovação:** CI continua verde; inspeção do YAML.

### SEC-09 - CI: Actions de terceiros pinadas por tag flutuante, não por SHA
- **Categoria:** Supply-chain (CI).
- **Severidade:** Informativa.
- **Local:** `.github/workflows/ci.yml` (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`).
- **Evidência:** pinagem por major tag, que é mutável. As imagens de serviço usam `postgres:16` e `mockserver/mockserver:8.0.0` (esta última, pinada por versão exata).
- **Mitigação:** pinar Actions por SHA de commit (hardening recomendado pelo GitHub). Risco baixo por serem Actions oficiais; é postura preventiva.
- **Teste de comprovação:** CI verde com os SHAs pinados.

### SEC-10 - CI: artefato publicado contém `api.log`
- **Categoria:** Exposição de log/artefato.
- **Severidade:** Informativa.
- **Local:** `.github/workflows/ci.yml` (`upload-artifact` com `api.log`).
- **Evidência:** o passo publica `pytest-results.xml` e `api.log`. O logger usa allowlist estruturada e há `tests/integration/test_observability.py` assertando que CPF/CNPJ/e-mail/segredos e o `INTERNAL_TOKEN` **não** aparecem nos logs; o risco de PII no artefato é, portanto, baixo. Como os dados do CI são sintéticos, risco residual mínimo.
- **Mitigação:** manter a disciplina de allowlist; opcionalmente restringir retenção do artefato. Preventivo.
- **Teste de comprovação:** `test_observability.py` verde (garante ausência de segredo/PII nos logs).

### SEC-11 - Banco com usuário único e privilégio de DDL; sem TLS declarado no repo
- **Categoria:** Hardening de banco / defesa em profundidade.
- **Severidade:** Informativa (escolha legítima de MVP).
- **Local:** `docker-compose.yml`/`database/Dockerfile` (usuário `bootcamp`, superusuário do container); `.env.example`/`DATABASE_URL` sem `sslmode`.
- **Evidência:** a aplicação conecta com o mesmo usuário que cria/altera o schema; TLS do banco é responsabilidade da infra de implantação (fora do repo). Credencial `bootcamp:bootcamp` é **demonstrativa** e local.
- **Mitigação (produção, fora desta rodada):** usuário de aplicação com privilégios mínimos (DML, sem DDL); `sslmode=require`. Em MVP local é aceitável.
- **Teste de comprovação:** não aplicável à baseline de 544; verificação de infra na implantação real.

### SEC-12 - Connector de análise não envia `INTERNAL-TOKEN`
- **Categoria:** Observação de consistência de autenticação de serviço a serviço.
- **Severidade:** Informativa.
- **Local:** `src/connectors/client_analysis_connector.py` (não passa `internal_token`), contra `src/connectors/bankslip_connector.py` (passa).
- **Evidência:** o provedor de análise é o MockServer local/CI, que não exige token; é coerente com o ambiente simulado. Registrar caso o provedor real passe a exigir autenticação.
- **Mitigação:** quando houver provedor real, parametrizar o token do provedor por ambiente, como já faz o connector de boletos.
- **Teste de comprovação:** R03 (contrato do provedor) verde.

---

## 6. Resultados reais das ferramentas de segurança

Todas as execuções foram locais, nesta branch, sobre o SHA da baseline. Sem fabricação de CVE, versão ou severidade.

### 6.1 bandit (SAST Python): executado
```
bandit -r src   →  No issues identified.
Total lines of code scanned: 3837
Issues by severity:  Undefined 0 · Low 0 · Medium 0 · High 0
```
Zero achados, inclusive em severidade/confiança baixas. Consistente com a ausência de `eval`/`exec`, de SQL por concatenação e de uso inseguro de `subprocess`/`pickle`.

### 6.2 pip-audit (dependências): executado
Produção (`requirements.txt`): **4 ocorrências em 1 pacote** (`requests 2.32.3`).

| Pacote | Versão | Advisory | Aliases | Fix |
|---|---|---|---|---|
| requests | 2.32.3 | PYSEC-2026-1872 | GHSA-9hjg-9r4m-mvj7, CVE-2024-47081 | 2.32.4 |
| requests | 2.32.3 | PYSEC-2026-2275 | GHSA-gc5v-m9x4-r6x2, CVE-2026-25645 | 2.33.0 |

Desenvolvimento (`requirements-dev.txt`): **8 ocorrências em 3 pacotes**.

| Pacote | Versão | Advisory | Aliases | Fix |
|---|---|---|---|---|
| requests | 2.32.3 | PYSEC-2026-1872 / PYSEC-2026-2275 | (acima) | 2.32.4 / 2.33.0 |
| pytest | 7.4.4 | PYSEC-2026-1845 | GHSA-6w46-j5rx-g56g, CVE-2025-71176 | 9.0.3 |
| python-dotenv | 1.0.1 | PYSEC-2026-2270 | GHSA-mf9w-mj56-hr94, CVE-2026-28684 | 1.2.2 |

Pacotes verificados **sem** advisories conhecidas no ambiente resolvido: `fastapi 0.141.1`, `uvicorn 0.52.3`, `pydantic 2.13.4`, `jsonschema 4.17.3`, `SQLAlchemy 2.0.23`, `psycopg2-binary 2.9.10`, além de transitivos (`starlette`, `urllib3`, `idna`, `certifi`, `pyyaml`, etc.). Resultado dependente da base de advisories disponível no momento (ver §7).

### 6.3 semgrep (SAST dirigido): executado com regras locais
O ruleset remoto (`p/python`) **não pôde ser baixado**: `semgrep.dev` retorna HTTP 403 pelo proxy (modo COMMON_DEPENDENCIES). Foi criada uma regra local mínima e a varredura rodou com sucesso:
```
non-constant-time-token-compare  →  src/middlewares/internal_token.py:27  (1 finding, blocking)
requests-call-without-timeout    →  0 findings (connector sempre passa timeout=self.timeout)
```
Isso **confirma SEC-01** com SAST e **corrobora** a ausência de chamada HTTP sem timeout (reforça o tratamento de DoS por integração pendurada). Cobertura de regras limitada ao conjunto local; não substitui um ruleset completo.

### 6.4 Sweep manual de segredos: executado (ferramentas dedicadas indisponíveis)
gitleaks/trufflehog/trivy não instaláveis (binários Go). Varredura manual:
- `git grep` por `password|secret|token|api_key|private key|AKIA…|ghp_…|-----BEGIN` em arquivos versionados: todas as ocorrências são o placeholder `default_token` (em `.env.example`, defaults do Compose, CI e fixtures de teste) ou referências textuais ao mecanismo de token.
- Histórico Git (`git log -S`, varredura de padrões de chave sobre `git rev-list --all`): **nenhum** segredo real, nenhuma chave privada, nenhum arquivo `.env`/dump/credencial.
- `git ls-files` por extensões sensíveis (`.env`, `.pem`, `.key`, `.p12`, `.csv`, `.dump`, `.sqlite`…): **nenhum** arquivo desse tipo versionado.
- `.gitignore` e `.dockerignore` barram explicitamente `.env*` (exceto `.env.example`), chaves, dumps e dados; `.dockerignore` exclui `.git`, `.github` e `.env*` da imagem.

**Classificação:** `default_token` e `bootcamp:bootcamp` são **demonstrativos** (documentados como “somente ambiente local” no README e no `.env.example`, e injetados por variável de ambiente no Compose). **Nenhuma credencial potencialmente real foi encontrada.**

---

## 7. Limitações e pontos não verificáveis

- **Sem execução dinâmica.** Docker, PostgreSQL (`psql`/`initdb`) e `psycopg2` indisponíveis; a suíte de 544 só é verde no GitHub Actions. Nenhum pentest dinâmico, nenhuma confirmação de timing real de SEC-01, nenhuma medição de custo real de SEC-07.
- **semgrep registry bloqueado.** `p/python`, `p/owasp-top-ten`, `p/security-audit` não baixáveis (proxy 403). A cobertura SAST do semgrep aqui é **apenas** a das regras locais; não interprete a ausência de outros achados como prova de segurança.
- **gitleaks/trivy/trufflehog ausentes.** Varredura de segredos e de imagem feita manualmente/por inspeção; uma varredura dedicada de imagem (camadas, CVEs do SO base `python:3.11-slim`/`postgres:16`) **não foi executada**.
- **pip-audit depende da base de advisories do momento.** Pacotes marcados “sem advisory” podem receber avisos futuros; reexecutar periodicamente.
- **Configurações privadas do GitHub não verificáveis pelo token desta sessão:** proteção de branch da `main`, exigência de review/checks obrigatórios, habilitação de Dependabot, secret scanning, push protection e code scanning, e os segredos/variáveis de Actions. **Passos para o proprietário conferir** (UI do repositório):
  - *Settings → Branches → Branch protection rules*: exigir PR + review, status checks obrigatórios (`test` e `migration`), bloquear force-push.
  - *Settings → Code security and analysis*: ativar Dependabot alerts + security updates, Secret scanning + push protection, CodeQL (code scanning).
  - *Settings → Actions → General*: “Workflow permissions” em *Read repository contents* por padrão; revisar fork PR approvals.
  - *Settings → Secrets and variables → Actions*: confirmar que não há segredo real exposto; o CI atual não referencia nenhum `secrets.*`.

---

## 8. Matriz de riscos residuais

| ID | Risco residual | Severidade | Probabilidade | Tratamento proposto | Decisão |
|---|---|---|---|---|---|
| SEC-01 | Timing side-channel no token | Média | Baixa | `hmac.compare_digest` (P2-A-PR-1) | Corrigir |
| SEC-02 | CVEs em `requests` (prod) | Média | Baixa | bump `>=2.33.0` (P2-A-PR-2) | Corrigir |
| SEC-05 | `/docs`/OpenAPI + comentário divergente | Média | Alta (exposição) | desligar por ambiente ou corrigir comentário (P2-A-PR-3) | Corrigir |
| SEC-03 | CVEs em deps de dev | Baixa | Baixa | bump controlado (`pytest` major → cautela) | Corrigir com cautela |
| SEC-04 | Sem rate limit | Baixa | Média | throttling na borda/infra | Aceitar na borda (residual) |
| SEC-06 | PID em `/` | Baixa | Baixa | remover PID (P2-A-PR-3) | Corrigir |
| SEC-07 | `page` sem teto | Baixa | Média | teto de `page`/keyset | Corrigir |
| SEC-08..10 | Hardening de CI | Informativa | n/a | `permissions`, pin por SHA, retenção de artefato | Hardening P2-A-PR-4 |
| SEC-11 | Usuário de banco com DDL / sem TLS | Informativa | n/a | usuário DML + `sslmode` em produção | Aceitar no MVP, documentar |
| SEC-12 | Connector de análise sem token | Informativa | n/a | parametrizar quando houver provedor real | Aceitar no MVP |

**Riscos residuais aceitos e justificados:** ausência de autenticação por usuário final e de autorização por titular (modelo single-tenant da RFC); SEC-04 tratado na borda; SEC-11/SEC-12 por ser MVP local com provedor simulado.

---

## 9. Backlog priorizado de correções

Ordem por prioridade da §10 do briefing (segredos/críticos → correções simples de baixo risco → dependências → hardening de CI → testes/observabilidade → residuais aceitos).

1. **Segredos reais / críticos:** nenhum. (Sweep limpo.)
2. **Correções simples de baixo risco:** SEC-01 (`compare_digest`), SEC-06 (remover PID), SEC-05 (alinhar `/docs`/comentário), SEC-07 (teto de `page`).
3. **Dependências:** SEC-02 (`requests>=2.33.0`), depois SEC-03 (dev-deps; `pytest` major com validação integral).
4. **Hardening de CI:** SEC-08 (`permissions`), SEC-09 (pin por SHA), SEC-10 (retenção de artefato).
5. **Testes negativos/observabilidade:** teste de brute-force/rate (SEC-04), testes de `page` fora do teto (SEC-07), teste de configuração de `/docs` por ambiente (SEC-05).
6. **Residuais aceitos:** SEC-04 (borda), SEC-11, SEC-12, e a premissa single-tenant, documentados e revalidáveis se o produto evoluir.

---

## 10. Plano de PRs da P2-A

Cada PR é pequeno, independente e respeita os invariantes da §11. Nenhum é iniciado nesta rodada.

### P2-A-PR-1 - Token em tempo constante (SEC-01)
- **Escopo:** trocar `!=` por `hmac.compare_digest` no gate de token.
- **Arquivos:** `src/middlewares/internal_token.py`.
- **Justificativa:** eliminar canal lateral de tempo; higiene de autenticação barata (já previsto como P2-05 na P1).
- **Testes obrigatórios:** R01 autenticação e `test_route_contracts.py` (token ausente/inválido → 403; válido → sucesso); novo teste de equivalência de comportamento.
- **Critérios de aprovação:** 544 testes + jobs `test` e `migration` verdes; `semgrep` regra local sem finding; comportamento 403/sucesso idêntico.

### P2-A-PR-2 - Atualizar `requests` (SEC-02)
- **Escopo:** `requests==2.32.3` → `>=2.33.0` (pin exato novo).
- **Arquivos:** `requirements.txt`.
- **Justificativa:** fechar PYSEC-2026-1872 e PYSEC-2026-2275.
- **Testes obrigatórios:** suíte completa; foco em R03 (connectors).
- **Critérios:** `pip-audit -r requirements.txt` sem achados para `requests`; CI verde.

### P2-A-PR-3 - Reduzir exposição de superfície (SEC-05, SEC-06)
- **Escopo:** decidir `/docs`/`/redoc`/`/openapi.json` por `APP_ENV` (ou corrigir o comentário se mantidos); remover PID de `GET /`.
- **Arquivos:** `src/app.py`, `src/resources/health_check.py`.
- **Justificativa:** alinhar configuração à intenção documentada; reduzir info disclosure.
- **Testes obrigatórios:** contrato de `/` e `/health_check`; teste de `/openapi.json` conforme ambiente.
- **Critérios:** CI verde; contratos atualizados coerentes com a RFC/ROTAS.

### P2-A-PR-4 - Hardening de CI (SEC-08, SEC-09, SEC-10)
- **Escopo:** adicionar `permissions: contents: read`; pinar Actions por SHA; revisar retenção do artefato `api.log`.
- **Arquivos:** `.github/workflows/ci.yml`.
- **Justificativa:** least privilege e supply-chain de CI.
- **Testes obrigatórios:** re-execução do workflow (jobs `test` e `migration`).
- **Critérios:** CI verde sem alteração de comportamento da suíte.

### P2-A-PR-5 - Deps de dev e teto de `page` (SEC-03, SEC-07)
- **Escopo:** bump `python-dotenv>=1.2.2`; avaliar `pytest` 9.x em PR isolado (major); teto/validação de `page` no extrato preservando semântica e ordenação.
- **Arquivos:** `requirements-dev.txt`, `src/schemas/get_account_transactions.json` (+ teste).
- **Justificativa:** fechar CVEs de dev e limitar consumo de recursos no extrato.
- **Testes obrigatórios:** R08 paginação; `pip-audit -r requirements-dev.txt` limpo.
- **Critérios:** 544 verdes; novo teste de `page` fora do teto → 400; sem regressão de paginação.

> **Observação de merge:** sem merge automático. SEC-01, SEC-02, SEC-03, SEC-05, SEC-06, SEC-07 e os ajustes de CI tocam código/deps/workflows e **não** fazem parte desta rodada de auditoria.

---

## 11. Checklist de revalidação e critérios de encerramento

**Invariantes a preservar em qualquer remediação futura (§11 do briefing):**
- [ ] Requisitos da RFC v2.1 inalterados.
- [ ] Comportamento de R01–R10 preservado (códigos HTTP e envelope de erro `QITxxxxxx`).
- [ ] Regras financeiras PF/PJ e arredondamento HALF_UP (`src/services/transfer_fee.py`) intactas.
- [ ] Idempotência, `request_hash` e SHA-256 (`src/services/transaction_hash.py`) inalterados.
- [ ] Ordem dos locks por `ACCOUNT.id` (`get_by_ids_for_update` com `sorted(...)`) preservada.
- [ ] Atomicidade: commit único no controller, rollback no `session_manager`.
- [ ] Integridade referencial do PostgreSQL (FKs `ON DELETE RESTRICT`, `CHECK`s de saldo/valor).
- [ ] Fluxos cadastrais e MockServer (R03) sem regressão.
- [ ] Semântica e paginação determinística do extrato (R08).

**Critérios de encerramento da P2-A (esta rodada):**
- [x] Auditoria concluída sem alterar código/testes/SQL/migrações/deps/Docker/workflows/GitHub.
- [x] Único artefato: `docs/P2A-SECURITY-AUDIT.md`.
- [x] Sweep de segredos (árvore + histórico) executado; nenhum segredo real; relatório seguro para publicação.
- [x] Ferramentas reais executadas (bandit, pip-audit, semgrep local) e limitações documentadas.
- [x] Achados classificados, revisados em segunda passada e separados de escolhas legítimas de MVP.
- [ ] Remediação **não** iniciada (reservada para rodadas P2-A-PR-*).

**Revalidação de cada PR futuro:** 544 testes + jobs `test` e `migration` verdes no GitHub Actions; `pip-audit` limpo para o pacote alterado; `semgrep` (regra local) sem o finding correspondente; checklist de invariantes acima integralmente marcado.

---

### Anexo A - Confirmações da baseline
- PRs #1–#6 integrados à `main` (tip = merge do PR #6, SHA `0c2259916cf46336b5d241e3b68e93423ae3441a`).
- `docs/P1-CONSOLIDATED-AUDIT.md` presente; SEC-01 corresponde ao item P2-05 já previsto na P1.
- Suíte de referência: 544 testes + jobs `test` e `migration` (fonte autoritativa: aba Actions).
- Nenhuma modificação feita ao upstream `mohamad347/bootcamp-qitech-bank-api`.
