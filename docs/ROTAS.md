# Contratos da API — BaaS Simplificado

**Bootcamp QI Tech 2026**

**Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Versão:** 2.1 · contratos conferidos com o código atual · versão original de 12/10/2026

**Documentos relacionados:** [RFC](RFC.md) · [Modelo de dados (ERD)](ERD.md) · [Fluxos de negócio](FLUXOS.md) · [Arquitetura](ARQUITETURA.md) · [Segurança](SEGURANCA.md)

> Os contratos R01–R10, o catálogo de erros e as regras de idempotência e paginação descritos aqui correspondem às rotas registradas em `src/app.py`. A validação do `INTERNAL-TOKEN` usa comparação em tempo constante; detalhes em [SEGURANCA.md](SEGURANCA.md).

## 1. Visão geral

O BaaS Simplificado disponibiliza dez rotas HTTP para cadastro e análise cadastral, abertura e gerenciamento de contas, depósitos, transferências, consulta de extrato e verificação de vida da API. Os contratos preservam a identidade pública dos recursos por UUID, os estados de domínio e a rastreabilidade das operações financeiras.

O produto opera em **BRL**, para clientes **pessoa física (`INDIVIDUAL`)** e **pessoa jurídica (`COMPANY`)**. Valores monetários são representados por **inteiros em centavos**, sem ponto flutuante. A solução utiliza PostgreSQL como fonte persistente de estados, saldos e histórico.

### 1.1 Inventário de endpoints

| ID | Método | Endpoint | Sucesso | Finalidade |
|---|---|---|---:|---|
| R01 | `POST` | `/client` | `201` | Cadastrar cliente PF ou PJ |
| R02 | `GET` | `/client/{client_key}` | `200` | Consultar cadastro atual |
| R03 | `POST` | `/client/{client_key}/analysis` | `200` | Executar análise cadastral externa |
| R04 | `POST` | `/client/{client_key}/account` | `201` | Abrir a única conta do cliente |
| R05 | `GET` | `/account/{account_key}` | `200` | Consultar conta e saldo |
| R06 | `PATCH` | `/account/{account_key}` | `200` | Alterar estado da conta e coordenar o cliente |
| R07 | `POST` | `/account/{account_key}/transaction` | `201` | Realizar depósito ou transferência |
| R08 | `GET` | `/account/{account_key}/transactions` | `200` | Consultar extrato paginado |
| R09 | `PATCH` | `/client/{client_key}` | `200` | Alterar estado do cliente ou solicitar reanálise |
| R10 | `GET` | `/health_check` | `204` | Verificar se o processo HTTP responde |

## 2. Convenções compartilhadas

### 2.1 Autenticação e identificadores

- **R01–R09:** exigem `INTERNAL-TOKEN: <token>`. Token ausente ou inválido resulta em `403`, antes de consultar recursos protegidos.
- **R10:** pública, sem `INTERNAL-TOKEN`, inclusive quando o header é enviado com valor inválido.
- **Identificadores públicos:** `client_key`, `account_key` e `transaction_key` são UUIDs; as chaves internas `BIGINT` não fazem parte das URLs nem dos corpos públicos.
- **UUID inválido:** erro HTTP `400`. **UUID válido não encontrado:** HTTP `404` com código do recurso correspondente.
- **JSON:** requests com corpo utilizam `Content-Type: application/json`; campos não autorizados ou tipos inválidos são rejeitados pelo contrato de validação.

### 2.2 Respostas e erros

As respostas de erro de domínio utilizam o envelope:

```json
{
  "title": "Invalid request",
  "description": "Description of the error",
  "translation": "Descrição do erro",
  "code": "QIT000001"
}
```

Os textos acima são ilustrativos; o contrato relevante é o conjunto de campos e o código do erro.

| HTTP | Semântica |
|---:|---|
| `200` | Leitura ou mudança de estado realizada |
| `201` | Recurso/operação criada; na R07, também replay financeiro idêntico |
| `204` | Liveness respondendo, sem corpo |
| `400` | Formato, esquema, UUID ou parâmetros inválidos |
| `403` | Autenticação interna ausente ou inválida |
| `404` | Cliente ou conta inexistente |
| `409` | Conflito de unicidade, estado, conta ou idempotência |
| `422` | Regra monetária ou intervalo de datas semanticamente inválido |
| `500` | Falha interna inesperada; não expõe detalhes internos de banco ou stack trace |

**Códigos transversais:** `QIT000001` (requisição inválida), `QIT000002` (token inválido) e `QIT000500` (falha interna). Os códigos de domínio estão reunidos na [Seção 5](#5-catálogo-de-erros-de-domínio).

### 2.3 Datas, valores e consistência

- Valores `amount_cents`, `balance_cents`, `fee_cents` e `balance_after_cents` representam **centavos de BRL**.
- Timestamps são persistidos em `TIMESTAMPTZ` e expostos em **UTC, ISO 8601/RFC 3339, com sufixo `Z`**.
- `CLIENT.timezone` é um identificador IANA obrigatório, usado para interpretar datas civis no extrato.
- Estados e movimentações confirmadas geram histórico; atualizações relacionadas são persistidas de forma **atômica**, com rollback integral em caso de falha antes do commit.
- Consultas (`GET`) não criam eventos, alteram saldos nem adquirem locks exclusivos de escrita.

## 3. Contratos por rota

### R01 — `POST /client`

**Objetivo.** Cadastrar um cliente `INDIVIDUAL` ou `COMPANY`, inicialmente em `PENDING`. A criação do cadastro, da especialização PF/PJ e do primeiro `CLIENT_STATUS_EVENT` (`NULL → PENDING`, ator `SYSTEM`) ocorre em uma única transação.

**Headers:** `INTERNAL-TOKEN`, `Content-Type: application/json`.

**Exemplo de requisição PF:**

```json
{
  "client_type": "INDIVIDUAL",
  "email": "cliente@example.com",
  "cpf": "52998224725",
  "full_name": "Cliente Exemplo",
  "birth_date": "1995-05-10",
  "timezone": "America/Sao_Paulo"
}
```

**Exemplo de requisição PJ:**

```json
{
  "client_type": "COMPANY",
  "email": "empresa@example.com",
  "cnpj": "11222333000181",
  "legal_name": "Empresa Exemplo Ltda.",
  "trade_name": "Empresa Exemplo",
  "timezone": "America/Sao_Paulo"
}
```

**Sucesso — `201 Created`:**

```json
{
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "client_type": "INDIVIDUAL",
  "status": "PENDING"
}
```

**Regras essenciais.** E-mail normalizado por `trim` e `lowercase`, com unicidade global; CPF/CNPJ normalizados para dígitos e verificados por dígitos de controle; idade mínima de 18 anos para PF; `timezone` IANA brasileiro suportado; perfil PF/PJ exclusivo. `trade_name` é opcional. IDs internos e histórico não integram a resposta.

**Falhas:** `400` para body/documento/timezone inválido; `403` para token; `409` para e-mail, CPF ou CNPJ duplicado; `422` para PF abaixo da idade mínima; `500` para falha interna. **Não há replay idempotente:** uma segunda criação com dados únicos já ocupados é conflito.

### R02 — `GET /client/{client_key}`

**Objetivo.** Consultar o estado cadastral atual, sem mutação, de um cliente em `PENDING`, `ACTIVE`, `REJECTED` ou `INACTIVE`.

**Headers:** `INTERNAL-TOKEN`. **Path:** `client_key` UUID.

**Sucesso — `200 OK` (exemplo PF):**

```json
{
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "client_type": "INDIVIDUAL",
  "email": "cliente@example.com",
  "timezone": "America/Sao_Paulo",
  "status": "ACTIVE",
  "cpf": "52998224725",
  "full_name": "Cliente Exemplo",
  "birth_date": "1995-05-10",
  "created_at": "2026-10-12T09:00:00Z",
  "updated_at": "2026-10-12T09:10:00Z"
}
```

Para PJ, os campos específicos são `cnpj`, `legal_name` e `trade_name` (que pode ser `null`), no lugar de `cpf`, `full_name` e `birth_date`.

**Regras essenciais.** Resposta derivada do cadastro persistido, sem IDs internos, conta associada ou eventos de status. A leitura é idempotente.

**Falhas:** `400` UUID inválido; `403` token; `404 CLI0001` cliente inexistente; `500` falha interna.

### R03 — `POST /client/{client_key}/analysis`

**Objetivo.** Solicitar análise de um cliente `PENDING` a um provedor externo, integrado por HTTP e representado pelo **MockServer** no ambiente do projeto. O caller não escolhe a decisão nem a fornece no body.

**Headers:** `INTERNAL-TOKEN`. **Path:** `client_key` UUID. **Body:** não requerido.

**Integração externa:**

```http
POST /v1/client-analysis
Content-Type: application/json
```

```json
{
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "client_type": "INDIVIDUAL",
  "document": "52998224725"
}
```

O provedor devolve `APPROVE` ou `REJECT` e, quando aplicável, um motivo. A API aplica `PENDING → ACTIVE` ou `PENDING → REJECTED`, registrando `CLIENT_STATUS_EVENT` com ator `INTERNAL`.

**Sucesso — `200 OK`:**

```json
{
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ACTIVE"
}
```

**Concorrência.** A chamada HTTP ao provedor é realizada sem manter um lock de banco aberto. Após receber a decisão, a aplicação adquire lock do cliente, revalida o estado `PENDING` e grava estado + evento atomicamente. Uma segunda análise após consumo do estado resulta em conflito, não em replay.

**Falhas:** `400` UUID inválido; `403` token; `404 CLI0001`; `409 CLI0002` se cliente não estiver `PENDING`; `500` para erro inesperado ou falha/timeout/resposta inválida do provedor.

### R04 — `POST /client/{client_key}/account`

**Objetivo.** Abrir a única conta permitida para um cliente `ACTIVE`.

**Headers:** `INTERNAL-TOKEN`. **Path:** `client_key` UUID. **Body:** não requerido.

**Sucesso — `201 Created`:**

```json
{
  "account_key": "2c7b4ad1-91b6-4d4f-95b5-d185f262cc9b",
  "status": "ACTIVE",
  "balance_cents": 0
}
```

**Regras essenciais.** O cliente deve existir, estar `ACTIVE` e **nunca ter tido outra conta**, inclusive uma já `CLOSED`. Cria `ACCOUNT` ativa com saldo zero e `ACCOUNT_STATUS_EVENT` inicial (`NULL → ACTIVE`, ator `SYSTEM`). A unicidade de `ACCOUNT.client_id` no PostgreSQL protege a cardinalidade vitalícia; criação concorrente também é serializada por lock no cliente.

**Falhas:** `400` entrada inválida; `403` token; `404 CLI0001`; `409 CLI0002` se cliente inelegível ou `ACC0002` se já possui conta; `500` falha interna. Não há replay de criação.

### R05 — `GET /account/{account_key}`

**Objetivo.** Consultar o snapshot da conta, incluindo saldo corrente e chave pública do cliente proprietário.

**Headers:** `INTERNAL-TOKEN`. **Path:** `account_key` UUID.

**Sucesso — `200 OK`:**

```json
{
  "account_key": "2c7b4ad1-91b6-4d4f-95b5-d185f262cc9b",
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ACTIVE",
  "balance_cents": 125000,
  "created_at": "2026-10-12T09:30:00Z",
  "updated_at": "2026-10-12T10:00:00Z"
}
```

**Regras essenciais.** Contas `ACTIVE`, `INACTIVE` e `CLOSED` continuam consultáveis. O saldo retornado é `ACCOUNT.balance_cents`; a rota não recalcula lançamentos nem altera o histórico.

**Falhas:** `400` UUID inválido; `403` token; `404 ACC0001`; `500` falha interna. Leitura idempotente.

### R06 — `PATCH /account/{account_key}`

**Objetivo.** Alterar o ciclo de vida da conta e, quando necessário, atualizar o estado do cliente associado na **mesma transação PostgreSQL**.

**Headers:** `INTERNAL-TOKEN`, `Content-Type: application/json`. **Path:** `account_key` UUID.

**Requisição:**

```json
{
  "status": "INACTIVE",
  "reason": "Solicitação operacional de suspensão"
}
```

**Sucesso — `200 OK`:**

```json
{
  "account_key": "2c7b4ad1-91b6-4d4f-95b5-d185f262cc9b",
  "status": "INACTIVE"
}
```

**Transições permitidas:**

| Conta — origem | Conta — destino | Efeito sobre CLIENT |
|---|---|---|
| `ACTIVE` | `INACTIVE` | `ACTIVE → INACTIVE` |
| `INACTIVE` | `ACTIVE` | `INACTIVE → ACTIVE` |
| `ACTIVE` | `CLOSED` | `ACTIVE → INACTIVE` |
| `INACTIVE` | `CLOSED` | Cliente permanece `INACTIVE` |

**Regras essenciais.** `CLOSED` é terminal e só é permitido quando `balance_cents == 0`; a rota **não zera saldo**. `reason` é obrigatório, normalizado por `trim`, não vazio e limitado a 500 caracteres. Os eventos de status são criados somente quando há mudança real; o fechamento de conta já inativa não produz um evento artificial `INACTIVE → INACTIVE` para CLIENT. Locks obedecem à ordem global **CLIENT → ACCOUNT**.

**Falhas:** `400` body/UUID/status/reason inválido; `403` token; `404 ACC0001`; `409 ACC0003` transição indevida, `ACC0004` saldo impede encerramento ou `CLI0002` incompatibilidade de estados; `500` falha interna.

### R07 — `POST /account/{account_key}/transaction`

**Objetivo.** Executar **depósito** ou **transferência** de forma atômica e idempotente, com registro durável da transação, dos lançamentos e do saldo após cada lançamento.

**Headers obrigatórios:** `INTERNAL-TOKEN`, **`Idempotency-Key: <UUID>`**, `Content-Type: application/json`. **Path:** `account_key` UUID (conta creditada no depósito; origem na transferência).

**DEPOSIT — requisição:**

```json
{
  "transaction_type": "DEPOSIT",
  "amount_cents": 50000
}
```

**TRANSFER — requisição:**

```json
{
  "transaction_type": "TRANSFER",
  "target_account_key": "947a419c-f31f-4440-90ac-84293b15a70d",
  "amount_cents": 50000
}
```

**Sucesso — `201 Created` (transferência PF de R$ 500):**

```json
{
  "transaction_key": "610986d2-ab9d-42f1-a6a5-e4cd1dc3a4c9",
  "transaction_type": "TRANSFER",
  "account_key": "2c7b4ad1-91b6-4d4f-95b5-d185f262cc9b",
  "counterparty_account_key": "947a419c-f31f-4440-90ac-84293b15a70d",
  "amount_cents": 50000,
  "fee_cents": 250,
  "created_at": "2026-10-12T10:15:00Z"
}
```

No depósito, `counterparty_account_key` é `null` e `fee_cents` é `0`. `transaction_key` e `created_at` são produzidos pelo servidor e reaproveitados em replay da mesma operação.

**Tarifas da transferência:**

| Proprietário da conta de origem | Taxa | Tarifa mínima | Tarifa máxima |
|---|---:|---:|---:|
| `INDIVIDUAL` (PF) | `0,50%` (50 bps) | 50 centavos | 1.000 centavos |
| `COMPANY` (PJ) | `1,00%` (100 bps) | 100 centavos | 1.500 centavos |

A tarifa é calculada com aritmética inteira, **arredondamento `HALF_UP`**, seguida dos limites mínimo e máximo. O tipo do cliente **da origem** determina a tarifa; o destino não altera o pricing. Transferência exige `amount_cents >= 1000` (R$ 10,00); depósito exige `amount_cents >= 1`.

**Efeitos financeiros persistidos:**

| Operação | Lançamentos `TRANSACTION_ENTRY` | Saldo |
|---|---|---|
| `DEPOSIT` | `CREDIT / PRINCIPAL` | Conta recebe `amount_cents` |
| `TRANSFER` | 1. origem `DEBIT / PRINCIPAL`; 2. origem `DEBIT / FEE`; 3. destino `CREDIT / PRINCIPAL` | Origem perde principal + tarifa; destino recebe principal integral |

Ambas as contas de uma transferência devem estar `ACTIVE`, não podem ser a mesma conta e o saldo da origem deve cobrir **principal + tarifa**. Locks de contas são adquiridos por **`ACCOUNT.id` crescente**, com revalidação de estados e saldos sob lock. Transação financeira, lançamentos e saldos são confirmados em um único commit; erros provocam rollback integral.

**Idempotência financeira.** A `Idempotency-Key` do header é persistida como `financial_transaction.request_control_key` e é **única globalmente**. O servidor associa a chave a um `request_hash` SHA-256 da intenção canônica:

```text
DEPOSIT|{source_account_key}|{amount_cents}
TRANSFER|{source_account_key}|{target_account_key}|{amount_cents}
```

| Nova tentativa | Comportamento |
|---|---|
| Chave inédita | Executa e persiste operação nova (`201`) |
| Mesma chave + mesma intenção | Responde `201` com a transação original, sem nova movimentação |
| Mesma chave + intenção diferente | Responde `409 TRX0003` |

O replay não recalcula tarifa nem exige que a conta continue `ACTIVE` depois da execução original. `Idempotency-Key` **não integra o body** e não é gerada automaticamente pelo servidor.

**Falhas:** `400` path/header/body inválido; `403` token; `404 ACC0001` conta de origem ou destino ausente; `409 ACC0005` conta indisponível, `TRX0002` transferência para si ou `TRX0003` conflito de chave; `422 TRX0004` valor abaixo do mínimo ou tecnicamente inválido, `TRX0001` saldo insuficiente; `500` erro interno.

### R08 — `GET /account/{account_key}/transactions`

**Objetivo.** Consultar o extrato **por lançamento** (`TRANSACTION_ENTRY`), sem recalcular saldos ou tarifas. É uma rota somente leitura.

**Headers:** `INTERNAL-TOKEN`. **Path:** `account_key` UUID.

**Parâmetros de consulta:**

| Parâmetro | Padrão | Restrições |
|---|---|---|
| `page` | `1` | Inteiro ≥ 1 |
| `limit` | `20` | Inteiro de 1 a 100 |
| `order_by` | `desc` | `asc` ou `desc` (minúsculas) |
| `date_from` | — | Data civil `YYYY-MM-DD`, inclusiva |
| `date_to` | — | Data civil `YYYY-MM-DD`, inclusiva |

Exemplo:

```http
GET /account/2c7b4ad1-91b6-4d4f-95b5-d185f262cc9b/transactions?page=1&limit=20&order_by=desc
INTERNAL-TOKEN: <token>
```

**Sucesso — `200 OK`:**

```json
{
  "data": [
    {
      "transaction_key": "610986d2-ab9d-42f1-a6a5-e4cd1dc3a4c9",
      "transaction_type": "TRANSFER",
      "entry_type": "PRINCIPAL",
      "direction": "DEBIT",
      "amount_cents": 50000,
      "balance_after_cents": 50000,
      "counterparty_account_key": "947a419c-f31f-4440-90ac-84293b15a70d",
      "created_at": "2026-10-12T10:15:00Z"
    }
  ],
  "pagination": {
    "current_page": 1,
    "next_page": null,
    "rows_per_page": 20
  }
}
```

Cada depósito produz um item `CREDIT / PRINCIPAL`. Uma transferência pode produzir **dois itens** no extrato da origem (`DEBIT / PRINCIPAL` e `DEBIT / FEE`) e **um item** no extrato do destino (`CREDIT / PRINCIPAL`). O valor `amount_cents` é positivo, e `direction` determina o sentido econômico. A contraparte é `null` em depósitos e tarifas.

**Ordenação e paginação.** `FINANCIAL_TRANSACTION.created_at`, depois `FINANCIAL_TRANSACTION.id`, são ordenados conforme `order_by`; o desempate final é sempre `TRANSACTION_ENTRY.id ASC`. Isso mantém `PRINCIPAL` antes de `FEE` inclusive na ordem descendente. A implementação verifica a existência de próxima página buscando `limit + 1`, sem exigir `COUNT(*)`. Uma página pode separar principal e tarifa da mesma transferência. Conta sem histórico ou página além do fim retorna `200` e `data: []`.

**Datas civis.** `date_from` e `date_to` são interpretados no `CLIENT.timezone` do proprietário da conta e convertidos a limites UTC. O intervalo é internamente **[início local de `date_from`, início local do dia seguinte a `date_to`)**. A resposta utiliza o instante público `FINANCIAL_TRANSACTION.created_at`, em UTC. Consultas são permitidas mesmo quando a conta está `INACTIVE` ou `CLOSED`.

**Validação.** Parâmetros desconhecidos, duplicados, vazios ou fora do formato permitido retornam `400 QIT000001`. `date_from > date_to` retorna `422 TRX0005`.

**Outras falhas:** `403` token; `404 ACC0001`; `500` falha interna. Não exige `Idempotency-Key` nem realiza `FOR UPDATE`.

### R09 — `PATCH /client/{client_key}`

**Objetivo.** Realizar as mudanças de estado próprias do cliente que não dependam da análise R03 nem da coordenação de contas R06.

**Headers:** `INTERNAL-TOKEN`, `Content-Type: application/json`. **Path:** `client_key` UUID.

**Requisição:**

```json
{
  "status": "PENDING",
  "reason": "Solicitação de nova análise cadastral"
}
```

**Sucesso — `200 OK`:**

```json
{
  "client_key": "550e8400-e29b-41d4-a716-446655440000",
  "status": "PENDING"
}
```

**Transições permitidas:**

| CLIENT — origem | CLIENT — destino | Regra |
|---|---|---|
| `REJECTED` | `PENDING` | Reanálise, sem limite arbitrário de ciclos |
| `ACTIVE` | `INACTIVE` | Permitida apenas quando não existe `ACCOUNT` |
| `INACTIVE` | `ACTIVE` | Permitida apenas quando não existe `ACCOUNT` |

**Regras essenciais.** Cliente com **qualquer conta existente**, inclusive `CLOSED`, deve ter o ciclo `ACTIVE ↔ INACTIVE` coordenado pela R06. A R09 não aprova/rejeita clientes `PENDING`, não permite `REJECTED` como destino nem aceita repetir o mesmo estado. `reason` é obrigatório, com `trim`, não vazio e até 500 caracteres; transição e `CLIENT_STATUS_EVENT` são gravados atomicamente sob lock do cliente (`actor_type=INTERNAL`).

**Falhas:** `400` entrada inválida; `403` token; `404 CLI0001`; `409 CLI0002` transição inválida ou `CLI0009` alteração que exige R06; `500` falha interna.

### R10 — `GET /health_check`

**Objetivo.** Prover **liveness** do processo HTTP — não readiness de PostgreSQL ou do MockServer.

**Autenticação:** nenhuma. **Parâmetros obrigatórios:** nenhum.

**Sucesso — `204 No Content`:** corpo vazio (zero bytes), sem JSON, mensagem ou objeto de status.

A rota não consulta banco, não aciona conectores e não acessa recursos de domínio. Se a aplicação já estiver respondendo HTTP, a indisponibilidade posterior do PostgreSQL não deve, por si só, transformar esse endpoint em verificação de banco. Repetições são idempotentes e não geram escrita.

### Rotas auxiliares (fora de R01–R10)

| Método | Caminho | Autenticação | Comportamento |
|---|---|---|---|
| `GET` | `/` | Pública | `200` com `{"service": "<SERVICE_NAME>"}`; não expõe PID nem outros dados de runtime |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | `INTERNAL-TOKEN` | Registradas somente quando `APP_ENV` é exatamente `local` ou `test`; caso contrário não são registradas (com token válido, respondem `404 QIT000404`) |

## 4. Regras de estado e consistência

### 4.1 Cliente

```text
R01:          (novo) → PENDING
R03:          PENDING → ACTIVE | REJECTED
R09:          REJECTED → PENDING
R09:          ACTIVE ↔ INACTIVE, somente se não houver conta
R06:          ACTIVE ↔ INACTIVE, coordenado com a conta existente
```

A conta é criada exclusivamente para cliente `ACTIVE`. Reanálises seguem `REJECTED → PENDING → (ACTIVE | REJECTED)`, com novo evento a cada transição válida.

### 4.2 Conta

```text
R04:          (nova) → ACTIVE; balance_cents = 0
R06:          ACTIVE → INACTIVE
R06:          INACTIVE → ACTIVE
R06:          ACTIVE | INACTIVE → CLOSED (saldo zero)
```

`CLOSED` é terminal; uma conta encerrada não pode ser substituída por outra para o mesmo cliente.

### 4.3 Movimentações e histórico

- `DEPOSIT`: uma `FINANCIAL_TRANSACTION` e um `TRANSACTION_ENTRY` de crédito principal.
- `TRANSFER`: uma `FINANCIAL_TRANSACTION` e três `TRANSACTION_ENTRY`, na ordem débito principal, débito tarifa e crédito principal.
- `ACCOUNT.balance_cents` é o saldo operacional; `TRANSACTION_ENTRY.balance_after_cents` preserva o saldo após cada lançamento.
- Histórico de estado e lançamentos confirmados é preservado; tentativas com falha não geram efeitos parciais.

## 5. Catálogo de erros de domínio

| Código | HTTP | Significado |
|---|---:|---|
| `QIT000001` | `400` | Erro de formato, parâmetro ou validação estrutural |
| `QIT000002` | `403` | `INTERNAL-TOKEN` ausente/inválido |
| `QIT000010` | `400` | Parâmetro de path/query inválido (ex.: `client_key` malformado na R03) |
| `QIT000404` | `404` | Caminho inexistente |
| `QIT000405` | `405` | Método não permitido no caminho |
| `QIT000500` | `500` | Falha interna inesperada |
| `CLI0001` | `404` | Cliente não encontrado |
| `CLI0002` | `409` | Estado ou transição do cliente incompatível |
| `CLI0003` | `409` | E-mail já cadastrado |
| `CLI0004` | `409` | CPF já cadastrado |
| `CLI0005` | `409` | CNPJ já cadastrado |
| `CLI0006` | `400` | CPF/CNPJ inválido |
| `CLI0007` | `422` | Pessoa física abaixo da idade mínima |
| `CLI0008` | `400` | Timezone inválido/não suportado |
| `CLI0009` | `409` | Mudança de CLIENT exige coordenação pela rota da conta |
| `ACC0001` | `404` | Conta não encontrada |
| `ACC0002` | `409` | Cliente já possui conta |
| `ACC0003` | `409` | Transição da conta não permitida |
| `ACC0004` | `409` | Saldo impede encerramento |
| `ACC0005` | `409` | Conta não está ativa para movimentação |
| `TRX0001` | `422` | Saldo insuficiente |
| `TRX0002` | `409` | Transferência entre a mesma conta |
| `TRX0003` | `409` | Conflito de idempotência |
| `TRX0004` | `422` | Valor monetário inválido ou fora dos limites técnicos |
| `TRX0005` | `422` | Intervalo de datas semanticamente inválido |

## 6. Decisões arquiteturais e alternativas consideradas

As decisões abaixo explicitam **opções avaliadas, vantagens e limitações** para o escopo do MVP.

| Tema | Solução adotada e vantagens | Alternativa, vantagem e motivo de não adoção | Limitação assumida |
|---|---|---|---|
| Identificação pública | **UUID nas URLs; `BIGINT` apenas no banco.** Separa identidade externa e chave física. | Expor IDs sequenciais simplificaria URLs e debugging, mas vincularia o contrato ao armazenamento. | UUIDs ocupam mais espaço que inteiros. |
| Cardinalidade de conta | **Uma conta por cliente, mesmo após `CLOSED`.** Simplifica regras e preserva a trajetória do vínculo; `UNIQUE(account.client_id)` protege no banco. | Múltiplas contas permitiriam novos produtos e reabertura, mas ampliariam requisitos de domínio e de isolamento financeiro. | Menor flexibilidade comercial. |
| Análise cadastral | **Connector HTTP para um provedor de análise.** Separa a decisão do caller e permite simulação por MockServer. | Receber `APPROVE`/`REJECT` no body seria mais simples, porém faria do endpoint apenas uma alteração direta de estado. | Introduz dependência HTTP, timeout e tratamento de falhas externas. |
| Atomicidade | **Uma transação PostgreSQL por operação de negócio**, incluindo histórico. Evita atualização parcial. | Commits separados seriam mais simples localmente, mas deixariam estados, eventos ou lançamentos divergentes após falhas. | Exige coordenação transacional explícita. |
| Concorrência | **Locks pessimistas e ordem determinística de aquisição.** Serializam decisões incompatíveis. | Validação sem lock reduziria espera, mas permitiria decisões baseadas em estado/saldo obsoleto. | Contenção e espera sob concorrência elevada. |
| Idempotência financeira | **`Idempotency-Key` global + SHA-256 da intenção.** Retry não duplica efeitos; reutilização indevida gera conflito. | Somente deduplicação no cliente reduziria persistência, mas não resistiria a retentativas e falhas de rede. | Requer persistência da chave e tratamento de concorrência entre requests. |
| Tarifação | **Regra calculada no servidor por perfil da origem**, com percentuais, limites e `HALF_UP`. | Tarifa informada pelo caller seria mais flexível, mas permitiria valores não autorizados; tarifa fixa única seria mais simples, porém eliminaria a diferenciação PF/PJ. | Política precisa ser mantida centralmente. |
| Unidade do extrato | **Um item por `TRANSACTION_ENTRY`.** Expõe principal, tarifa e saldo histórico sem recomputação. | Um item por `FINANCIAL_TRANSACTION` seria mais compacto, mas esconderia o detalhamento dos lançamentos. | Principal e tarifa podem aparecer em páginas diferentes. |
| Paginação | **`page`/`limit`, desempate estável e consulta `limit + 1`.** Contrato fácil de consumir, sem `COUNT(*)` obrigatório. | Cursor escala melhor em conjuntos muito grandes e evita certos deslocamentos, mas adiciona complexidade ao MVP. | Mudanças concorrentes podem deslocar limites de página. |
| Filtro temporal | **Datas civis no timezone IANA do cliente, convertidas para UTC.** Respeita o calendário local. | Interpretar diretamente como UTC simplificaria consultas, mas poderia incluir/excluir movimentações no dia errado para o usuário. | Conversão temporal exige atenção aos limites de dia. |
| Monitoramento | **`/health_check` exclusivamente de liveness.** Separa processo HTTP de suas dependências. | Readiness com consultas a PostgreSQL/MockServer forneceria sinal mais amplo, mas transformaria falha de dependência em falsa impressão de processo morto. | Readiness e monitoramento de dependências são preocupações distintas. |

## 7. Escopo do produto

Esta API implementa um núcleo **BaaS simplificado**. Não contempla PIX, TED, boletos, saques, estornos, multi-tenancy no mesmo banco, KYC comercial real ou contabilidade de partidas dobradas com contas internas de compensação/receita. O provedor de análise cadastral é integrado via HTTP e simulado com MockServer no ambiente do projeto.

Para os relacionamentos físicos e constraints, consultar o [ERD](ERD.md). Para as sequências detalhadas de caminho feliz, falhas e decisões transacionais, consultar [Fluxos](FLUXOS.md). A [RFC](RFC.md) e sua [versão em PDF](RFC.pdf) apresentam a motivação, a arquitetura e as alternativas em nível macro.
