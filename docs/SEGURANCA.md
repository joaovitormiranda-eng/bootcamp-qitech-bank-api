# Segurança e modelo de confiança — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Documentos relacionados:** [RFC](RFC.md) · [ROTAS](ROTAS.md) · [Arquitetura](ARQUITETURA.md) · [CI e DevSecOps](CI-DEVSECOPS.md)

Este documento descreve os controles de segurança implementados no código e os riscos que permanecem. Ele não é uma certificação: as verificações automatizadas descritas aqui (testes, Bandit e pip-audit) reduzem riscos conhecidos, mas não provam ausência de vulnerabilidades.

## Sumário

1. [Modelo de confiança](#1-modelo-de-confiança)
2. [Autenticação por INTERNAL-TOKEN](#2-autenticação-por-internal-token)
3. [Superfície pública e documentação OpenAPI](#3-superfície-pública-e-documentação-openapi)
4. [Validação de entrada e erros](#4-validação-de-entrada-e-erros)
5. [Logs e dados sensíveis](#5-logs-e-dados-sensíveis)
6. [Integridade financeira](#6-integridade-financeira)
7. [Dependências e imagem](#7-dependências-e-imagem)
8. [Riscos residuais](#riscos-residuais)

## 1. Modelo de confiança

A RFC define **uma plataforma parceira por implantação**. As rotas R01–R09 são chamadas pelo backend dessa plataforma, autenticado por um **segredo compartilhado** no header `INTERNAL-TOKEN`.

O sistema **não** tem autenticação de usuário final, autorização por titular de conta nem multi-tenancy. Qualquer portador do token tem acesso a todos os clientes e contas da implantação. Isso é uma decisão de escopo; se o produto passar a atender vários parceiros ou usuários finais, o modelo precisa ser revisto.

## 2. Autenticação por INTERNAL-TOKEN

Implementação: `src/middlewares/internal_token.py`.

- O token esperado vem da variável de ambiente `INTERNAL_TOKEN`; a aplicação não sobe se ela estiver ausente (`check_variables()`).
- A comparação usa `hmac.compare_digest` sobre os dois valores codificados em `latin-1`, o que evita diferenças de tempo dependentes do conteúdo e aceita qualquer byte que o Starlette tenha decodificado do header.
- Se o header ou o token configurado forem vazios ou ausentes, a comparação retorna falso antes de `compare_digest`. Um header vazio nunca é aceito.
- Token ausente ou incorreto responde `403` com código `QIT000002`, antes de qualquer acesso a recurso ou abertura de sessão de banco.
- O valor do token não é registrado em logs nem incluído em respostas.
- Requisições `OPTIONS` e os caminhos em `BYPASS_ENDPOINTS` (`/` e `/health_check`) não exigem token.

Testes: `tests/integration/client/r01/test_authentication.py` e `tests/integration/contracts/test_route_contracts.py`.

## 3. Superfície pública e documentação OpenAPI

| Caminho | Exige token | Observação |
|---|---|---|
| `GET /health_check` | Não | `204` sem corpo; não consulta banco |
| `GET /` | Não | Retorna apenas `{"service": ...}`; o PID do processo não é exposto |
| `/docs`, `/redoc`, `/openapi.json` | Sim | Registradas apenas em ambientes de desenvolvimento explícitos |

A documentação OpenAPI segue uma política **fail-closed** (`src/app.py`):

```python
docs_enabled = os.environ.get("APP_ENV") in {"local", "test"}
```

| `APP_ENV` | Documentação |
|---|---|
| `local` | Habilitada |
| `test` | Habilitada |
| `production` | Desabilitada |
| ausente | Desabilitada |
| vazio ou outro valor (ex.: `staging`, `LOCAL`) | Desabilitada |

O valor é lido diretamente do ambiente, e não de `constants.APP_ENV`, porque `constants.py` usa `"local"` como fallback quando a variável não existe; usar esse fallback habilitaria a documentação por omissão. O `docker-compose.yml` define `APP_ENV=local` na API principal e `APP_ENV=test` na API de testes.

Mesmo habilitadas, essas rotas passam pelo `INTERNAL-TOKEN`. Testes: `tests/integration/test_openapi_exposure.py` (os cinco cenários acima) e `tests/integration/test_healthcheck.py`.

## 4. Validação de entrada e erros

- Corpos de requisição e a query do extrato são validados por JSON Schema (`src/schemas/`), com `additionalProperties: false` onde aplicável.
- Identificadores de path são UUIDs; valores malformados retornam `400`.
- O acesso a dados usa o ORM do SQLAlchemy com parâmetros, sem SQL montado por concatenação de entrada do usuário.
- Todas as respostas de erro usam o envelope `{title, description, translation, code}`. Erros inesperados retornam `500 QIT000500` sem stack trace nem detalhes do banco.

## 5. Logs e dados sensíveis

- `src/utils/logger.py` emite JSON com uma **lista fixa de campos** (`event`, `request_id`, `method`, `route`, `status_code`, `duration_ms`, `error_code`, `exception_type`, `timeout_type`, `sqlstate`, `operation`, `reason_type`). Corpo, headers e valores reais de path não fazem parte dessa lista.
- O campo `route` registra o template da rota (por exemplo `/account/{account_key}`), não a chave real.
- `tests/integration/test_observability.py` verifica que CPF, CNPJ, e-mail, valores de query e o `INTERNAL_TOKEN` não aparecem nos logs.

## 6. Integridade financeira

Controles que impedem perda ou duplicação de dinheiro (detalhes em [ARQUITETURA.md](ARQUITETURA.md#4-fronteira-transacional-e-locks) e [FLUXOS.md](FLUXOS.md)):

- **Idempotência:** `Idempotency-Key` obrigatória na R07, persistida em `financial_transaction.request_control_key` com `UNIQUE` global e associada ao SHA-256 da intenção canônica. Mesma chave e mesma intenção devolvem a transação original; mesma chave e intenção diferente retornam `409 TRX0003`.
- **Concorrência:** locks `FOR UPDATE` em ordem crescente de `ACCOUNT.id`, com revalidação de status e saldo após o lock.
- **Atomicidade:** um único `COMMIT` por operação; qualquer falha anterior provoca `ROLLBACK` integral.
- **Restrições no banco:** `CHECK (balance_cents >= 0)`, `CHECK (amount_cents > 0)`, `CHECK (balance_after_cents >= 0)` e FKs `ON DELETE RESTRICT`.

## 7. Dependências e imagem

- Versões fixadas com `==` em `requirements.txt` (aplicação) e `requirements-dev.txt` (testes).
- O job `security` do CI executa pip-audit sobre os dois arquivos e Bandit sobre `src/`; ver [CI-DEVSECOPS.md](CI-DEVSECOPS.md).
- O `Dockerfile` instala apenas `requirements.txt` e executa a aplicação com um usuário sem privilégios. O uvicorn roda com `--no-server-header`.
- `.gitignore` e `.dockerignore` excluem arquivos `.env`; `.gitignore` também exclui chaves e dumps.
- `default_token` e `bootcamp:bootcamp` são valores de demonstração para uso local. Uma implantação real deve definir segredos próprios fora do repositório.

## Riscos residuais

Os itens abaixo continuam abertos e dependem de decisões de produto ou de infraestrutura que não fazem parte deste repositório.

| Risco | Situação | Mitigação esperada |
|---|---|---|
| Sem rate limiting ou bloqueio de tentativas no gate de token | Um atacante com acesso de rede pode tentar adivinhar o token sem limite de taxa | Limitar requisições na borda (gateway/WAF) e alertar sobre taxa de `403` |
| Segredo único e compartilhado | Vazamento do token concede acesso total à implantação | Rotação do segredo e armazenamento em cofre na infraestrutura |
| `page` do extrato sem limite superior | Páginas muito altas geram `OFFSET` caro | O custo é limitado pelo `statement_timeout`; o contrato exige `200` com lista vazia além do fim, então não há rejeição por `page` alto. Paginação por cursor exigiria mudar o contrato |
| Usuário de banco único com permissão de DDL; TLS não configurado no repositório | A aplicação conecta com o mesmo usuário que cria o schema | Usuário de aplicação sem DDL e `sslmode=require` na implantação |
| Connector de análise sem autenticação | O MockServer não exige token | Configurar credenciais quando houver um provedor real |
| Escopo das verificações automatizadas | Bandit roda com piso de severidade média (`-ll`); não há teste de invasão dinâmico | Revisões de segurança adicionais antes de qualquer implantação real |
