# Migrações de schema — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Autores:** João Vitor Miranda Sousa · Mohamad Ahmad Barakat

**Documentos relacionados:** [ERD](ERD.md) · [CI e DevSecOps](CI-DEVSECOPS.md) · [README das migrações](../database/migrations/README.md)

## Sumário

1. [Banco novo × banco existente](#1-banco-novo--banco-existente)
2. [O que a migração 0001 faz](#2-o-que-a-migração-0001-faz)
3. [Aplicar em um banco do Docker Compose](#3-aplicar-em-um-banco-do-docker-compose)
4. [Aplicar em outro PostgreSQL](#4-aplicar-em-outro-postgresql)
5. [Validação](#5-validação)
6. [Rollback e recuperação](#6-rollback-e-recuperação)
7. [Como a migração é testada](#7-como-a-migração-é-testada)

## 1. Banco novo × banco existente

| Situação | O que acontece | O que fazer |
|---|---|---|
| Volume PostgreSQL novo (primeiro `docker compose up`) | A imagem `database/Dockerfile` copia `database/database.sql` para `docker-entrypoint-initdb.d`, e o PostgreSQL cria o schema atual de 15 tabelas | Nada |
| Volume criado com o schema anterior (10 tabelas, enumerações em `VARCHAR`) | O PostgreSQL só executa `docker-entrypoint-initdb.d` em um diretório de dados vazio. Reiniciar ou reconstruir containers **não** altera o schema existente, e a API atual não funciona sobre o schema antigo | Fazer backup e aplicar a migração `0001` |

> Não apague o volume (`docker compose down -v` ou `docker volume rm`) para "atualizar" o schema de um banco com dados: isso destrói os dados. A migração existe para evoluir o banco preservando-os.

Não há Alembic no projeto. As migrações são scripts SQL versionados em [`database/migrations/`](../database/migrations/), executados com `psql`. Cada `NNNN_*.sql` tem um `NNNN_ROLLBACK.sql` correspondente.

## 2. O que a migração 0001 faz

Arquivo: [`0001_cod05_cod06_lookup_and_entry_key.sql`](../database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql).

- Roda em **uma única transação** (`BEGIN` … `COMMIT`); com `ON_ERROR_STOP=1`, qualquer erro desfaz tudo.
- Exige que as tabelas de domínio existam; caso contrário, aborta com `RAISE EXCEPTION`.
- Habilita a extensão `pgcrypto` (`CREATE EXTENSION IF NOT EXISTS`), necessária para `gen_random_uuid()`. O usuário que executa a migração precisa de permissão para isso.
- Cria as lookups `client_type`, `transaction_type`, `transaction_direction`, `entry_type` e `actor_type` com seus valores.
- Para cada enumeração, adiciona a coluna `*_id`, preenche a FK a partir do texto existente, exige que nenhuma linha fique sem valor, define `NOT NULL` e `FOREIGN KEY ... ON DELETE RESTRICT`, remove o `CHECK` antigo e a coluna textual, e cria o índice da FK.
- Adiciona `transaction_entry.entry_key` e preenche cada linha com `gen_random_uuid()`. Os valores são **aleatórios**. O preenchimento só atinge linhas com `entry_key IS NULL`, então uma reexecução não altera chaves já atribuídas. Depois, a coluna passa a ser `NOT NULL UNIQUE`.
- Ao final, falha se houver FK nova nula, `entry_key` nulo ou duplicado, ou lookup com valor repetido.

**Idempotência:** reaplicar a migração em um banco já migrado não recria colunas nem duplica lookups (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING` e verificações no `information_schema`).

A operação faz `ALTER TABLE` e remove colunas: planeje uma janela sem tráfego na API.

## 3. Aplicar em um banco do Docker Compose

No `docker-compose.yml`, o serviço `db` não publica porta no host. Os comandos abaixo usam `docker compose exec` e o usuário local `bootcamp`; execute-os na raiz do repositório.

**1. Parar a API** (mantém containers e volumes):

```bash
docker compose stop api
```

**2. Backup:**

```bash
docker compose exec -T db pg_dump -U bootcamp -d bootcamp -Fc > pre_0001.dump
```

Confira que `pre_0001.dump` foi criado e não está vazio antes de continuar.

**3. Aplicar a migração:**

```bash
docker compose exec -T db psql -U bootcamp -d bootcamp -v ON_ERROR_STOP=1 \
  < database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql
```

**4. Subir a API e verificar:**

```bash
docker compose up -d --wait api
curl -i http://localhost:3000/health_check
```

## 4. Aplicar em outro PostgreSQL

`psql` e `pg_dump` aceitam URLs `postgresql://`, **não** o formato do SQLAlchemy `postgresql+psycopg2://` usado em `DATABASE_URL` no `.env.example`. Use uma URL própria para as ferramentas:

```bash
export PG_URL="postgresql://USUARIO:SENHA@HOST:5432/BANCO"

pg_dump "$PG_URL" -Fc -f pre_0001.dump
psql "$PG_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql
```

## 5. Validação

A própria migração aborta se encontrar inconsistências. Para conferir manualmente depois de aplicada (exemplo com Compose):

```bash
docker compose exec -T db psql -U bootcamp -d bootcamp -c "\dt"
docker compose exec -T db psql -U bootcamp -d bootcamp -c \
  "SELECT count(*) AS entries, count(DISTINCT entry_key) AS distinct_keys FROM transaction_entry;"
```

O primeiro comando deve listar 15 tabelas; no segundo, os dois números devem ser iguais. Compare também contagens e a soma de `account.balance_cents` com valores anotados antes da migração.

## 6. Rollback e recuperação

**Preferencial — restaurar o backup:**

```bash
docker compose stop api
docker compose exec -T db pg_restore -U bootcamp -d bootcamp --clean --if-exists < pre_0001.dump
```

**Estrutural — `0001_ROLLBACK.sql`**, quando o restore não for viável:

```bash
docker compose exec -T db psql -U bootcamp -d bootcamp -v ON_ERROR_STOP=1 \
  < database/migrations/0001_ROLLBACK.sql
```

O rollback recria as colunas textuais a partir do `enumerator` das lookups, restaura os `CHECK`, remove as FKs, as colunas `*_id` e as cinco lookups criadas pela migração, e remove `entry_key`.

- **Dados de negócio preservados:** clientes, perfis PF/PJ, contas, saldos, eventos, transações, lançamentos, `request_control_key` e `request_hash` permanecem; o texto das enumerações volta igual ao original.
- **Metadado perdido intencionalmente:** `entry_key`, que não existia antes da migração e não é referenciado por nenhuma FK.
- **Atenção:** depois do rollback estrutural, o banco volta ao schema anterior e **não é compatível** com a versão atual da API.

## 7. Como a migração é testada

- **Job `migration` do CI:** banco legado populado, migração, reexecução e rollback, com comparação de contagens e da soma de saldos com o estado inicial. Detalhes em [CI-DEVSECOPS.md](CI-DEVSECOPS.md#3-job-migration).
- **`tests/integration/database/test_populated_migration.py`:** aplica a migração em um banco efêmero populado e compara identidade, valores monetários, hashes e relacionamentos antes e depois.

Nenhum desses testes roda contra bancos persistentes; ambos usam PostgreSQL descartável.
