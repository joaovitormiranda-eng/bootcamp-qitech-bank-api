# Segurança e modelo de confiança — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Versão:** P2-Final

**Documentos relacionados:** [RFC](RFC.md) · [ROTAS](ROTAS.md) · [Arquitetura](ARQUITETURA.md) · [CI/DevSecOps](CI-DEVSECOPS.md) · [Auditoria P2-A](P2A-SECURITY-AUDIT.md) · [Auditorias](AUDITORIAS.md)

> Distinção mantida ao longo do documento: **fato verificado** (contra código/CI),
> **limitação** (do MVP) e **recomendação** (trabalho futuro, não implementado).

## 1. Modelo de confiança (single-tenant)

Fato verificado. A RFC v2.1 define o modelo: **uma plataforma parceira por
implantação**, no Brasil, em BRL. O chamador das rotas R01–R09 é a **plataforma
parceira confiável**, autenticada por um **segredo compartilhado** no header
`INTERNAL-TOKEN`. **Não há** autenticação por usuário final, autorização por
titular de conta nem multi-tenancy — por **decisão de arquitetura**, não por
omissão.

Consequência metodológica (alinhada à auditoria P2-A): a ausência de
autenticação por usuário final e de autorização por titular **não** é tratada
como vulnerabilidade. Qualquer portador do token é a plataforma parceira. Se o
produto evoluir para multi-parceiro, esta premissa deve ser reavaliada.

A única fronteira de autenticação é o middleware `internal_token`. A rota pública
`/` (identificação do serviço) e `/health_check` (R10, liveness) estão em
`BYPASS_ENDPOINTS` e **não** exigem token; nenhuma outra rota é pública.

## 2. Autenticação `INTERNAL-TOKEN` — comparação em tempo constante

Fato verificado (`src/middlewares/internal_token.py`). A comparação do token usa
`hmac.compare_digest` (tempo constante), com guarda de `None`/vazio e codificação
`latin-1` dos dois lados:

```python
def _tokens_match(provided: str | None, expected: str | None) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(
        provided.encode("latin-1"), expected.encode("latin-1")
    )
```

- **Tempo constante (SEC-01):** `hmac.compare_digest` evita o canal lateral de
  *timing* da comparação `!=` ingênua. Corrigido no PR #8 (SEC-01).
- **`None`/vazio:** o *short-circuit* `if not provided or not expected` impede o
  `TypeError` que `compare_digest` levantaria com `None` e garante que um header
  ausente/vazio **nunca** case com um token ausente/vazio (sem bypass de auth).
- **latin-1:** o Starlette decodifica headers HTTP como Latin-1; codificar ambos
  os lados em Latin-1 evita `UnicodeEncodeError`/`TypeError` (→ 500) diante de
  bytes não-ASCII no header, preservando o `403` correto.
- **Bypass:** o middleware ignora `OPTIONS` e os caminhos de `BYPASS_ENDPOINTS`.
  Em mismatch, **retorna** (não levanta) `ForbiddenNotInternal()` → `403 QIT000002`.

## 3. Superfície e configuração

- **Documentação OpenAPI (SEC-05):** `/docs`, `/redoc` e `/openapi.json` **não**
  estão em `BYPASS_ENDPOINTS`, logo ficam atrás do `INTERNAL-TOKEN` (sem exposição
  pública não autenticada). Como defesa em profundidade, são **desligados** quando
  `APP_ENV == "production"` (`src/app.py`). Em `local`/`test` permanecem ligados.
- **Raiz `/` (SEC-06):** responde apenas `{"service": ...}`; o PID do processo foi
  removido da resposta pública (era detalhe interno de runtime sem valor ao
  chamador).
- **Erros:** envelope padronizado `QITxxxxxx` sem *stack trace*; `500` não expõe
  detalhe interno de banco. Catálogo completo em [ROTAS.md](ROTAS.md) §5.

## 4. Dados, logs e segredos

Fato verificado.
- **Logs com allowlist estruturada** (`src/utils/logger.py`): apenas campos
  técnicos (`event`, `request_id`, `method`, `route`, `status_code`,
  `duration_ms`, `error_code`, `exception_type`, `timeout_type`, `sqlstate`,
  `operation`, `reason_type`). Nunca corpo, *path params* reais ou headers. O
  `route` logado é o **template** (`/account/{account_key}`), não a chave real.
- **Teste de não vazamento:** `tests/integration/test_observability.py` assere que
  CPF/CNPJ/e-mail/segredos de query e o `INTERNAL_TOKEN` **não** aparecem nos logs,
  e que a chave real não é logada.
- **Sem SQL dinâmico:** acesso a dados via ORM parametrizado (SQLAlchemy).
- **Segredos:** nenhum segredo real versionado; `default_token` e
  `bootcamp:bootcamp` são **demonstrativos e somente locais** (documentado em
  `.env.example`). `.gitignore`/`.dockerignore` barram `.env*`, chaves e dumps.
- **Imagem:** o `Dockerfile` instala apenas `requirements.txt` (dependências de
  dev/CI não entram em produção) e roda como usuário sem privilégio.

## 5. Dependências (supply-chain) — estado atual

Fato verificado (pip-audit sobre a `main` integrada; job `security` do CI):

| Arquivo | Estado | Observação |
|---|---|---|
| `requirements.txt` | **No known vulnerabilities found** | `requests==2.33.0` (SEC-02 corrigiu CVE-2024-47081 e CVE-2026-25645) |
| `requirements-dev.txt` | **No known vulnerabilities found** | `pytest==9.0.3` (CVE-2025-71176), `python-dotenv==1.2.2` (CVE-2026-28684) — SEC-03 |

O pip-audit roda **bloqueante** no CI (sem `continue-on-error`): uma advisory nova
reprova o job. Detalhes em [CI-DEVSECOPS.md](CI-DEVSECOPS.md).

## 6. Concorrência e integridade financeira (resumo de segurança)

Fato verificado. Locks pessimistas `FOR UPDATE` ordenados por `ACCOUNT.id`
crescente (anti-deadlock), revalidação de estado/saldo sob lock, `COMMIT` único,
`ROLLBACK` integral em falha, `CHECK (balance_cents >= 0)` e idempotência global
por `request_control_key` + `request_hash` SHA-256. Ver [FLUXOS.md](FLUXOS.md) §4
e [ROTAS.md](ROTAS.md) §R07.

## 7. Riscos residuais aceitos (limitações do MVP)

Os itens abaixo são **limitações conscientes** do MVP, não defeitos. São
registrados aqui — e **não** foram transformados em refatorações obrigatórias —
porque cada alternativa teria custo/risco desproporcional ao escopo acadêmico ou
quebraria um contrato.

| ID | Tema | Decisão e justificativa |
|---|---|---|
| **SEC-04** | Sem *rate limiting* / anti-brute-force no gate de token | Mitigação natural é na **borda/infra** (WAF/gateway), fora do repositório. Em código, arriscaria os testes de concorrência. Risco residual aceito; a comparação em tempo constante (SEC-01) já reduz o canal lateral. |
| **SEC-07** | `page` do extrato sem teto superior (OFFSET profundo) | **Não** se introduz teto com `400`: a RFC exige **HTTP 200 + lista vazia** para páginas válidas além do fim. O custo de OFFSET profundo é limitado pelo `statement_timeout` (padrão 10 s; SQLSTATE 57014 tratado). *Keyset/seek* mudaria a semântica de página numerada (quebra de contrato). Recomendação futura: avaliar keyset se o volume justificar. |
| **SEC-11** | Usuário único de banco com DDL; TLS não declarado no repo | Responsabilidade da **infra de implantação** (usuário de app sem DDL, `sslmode=require`). Em MVP local é aceitável; credenciais são demonstrativas. |
| **SEC-12** | `client_analysis_connector` não envia `INTERNAL-TOKEN` | O provedor de análise é o **MockServer**, que não exige token. Quando houver provedor real com contrato, parametrizar o token por ambiente (como já faz o connector de boletos). |

## 8. Limitações da análise e o que NÃO é afirmado

- **Sem pentest dinâmico.** As verificações são SAST (Bandit), auditoria de
  dependências (pip-audit) e leitura de código/CI. Não há teste de invasão.
- **Não se declara "segurança absoluta".** O escopo é um **MVP acadêmico
  validado em CI**, distinto de um **serviço implantado em produção** (sem CD,
  Kubernetes, AWS ou GCP neste projeto).
- **Configurações privadas do GitHub** (proteção de branch, Dependabot, secret
  scanning, segredos de Actions) não são verificáveis a partir do código e ficam
  a cargo do proprietário do repositório.
