# Migrações de banco — P1-D

Este diretório contém migrações **SQL versionadas** aplicadas sobre um banco
PostgreSQL **já populado**. O bootstrap de um banco vazio continua sendo
`database/database.sql` (schema alvo, já no estado pós-P1-D); as migrações aqui
existem para evoluir instalações que ainda estão no schema antigo **sem perder
dados**.

> Não há Alembic no projeto (o schema é instalado por `database.sql` no
> `docker-entrypoint-initdb.d`). Estas migrações são scripts `psql` idempotentes.

## Convenção

- Nome: `NNNN_descricao.sql` (ordem lexicográfica = ordem de aplicação).
- Cada migração tem um par `NNNN_ROLLBACK.sql`.
- Toda migração roda em **transação única** com `ON_ERROR_STOP=1`
  (`ROLLBACK` total em qualquer erro).
- Idempotente: reexecutar não duplica objetos nem dados de lookup.

## 0001 — COD-05/COD-06 (lookup tables + entry_key)

`0001_cod05_cod06_lookup_and_entry_key.sql`

- **COD-06:** cria as lookups `client_type`, `transaction_type`,
  `transaction_direction`, `entry_type`, `actor_type`; faz backfill das colunas
  textuais para FKs `*_id`; remove os `CHECK IN (...)` e as colunas textuais.
- **COD-05:** adiciona `transaction_entry.entry_key UUID NOT NULL UNIQUE`, com
  backfill determinístico por linha (`gen_random_uuid()`), preservando a chave
  interna `id` (PK) e todas as FKs/ordenação.

### Pré-condições (obrigatórias em ambiente não-efêmero)

1. **Backup:** `pg_dump` completo ANTES de aplicar.
   ```sh
   pg_dump "$DATABASE_URL" -Fc -f pre_0001.dump
   ```
2. Janela de manutenção (a migração faz `ALTER TABLE`/`DROP COLUMN`).

### Aplicar

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql
```

### Validação pós-migração

A própria migração valida (e aborta via `RAISE EXCEPTION` em caso de problema):
nenhuma FK/entry_key nula; `entry_key` totalmente único; lookups sem enumerator
duplicado. O teste automatizado
`tests/integration/database/test_populated_migration.py` exercita a migração em
banco efêmero populado (PF/PJ, contas, saldos, históricos, depósitos,
transferências, lançamentos, chaves de idempotência) e compara contagem,
identidade, valores monetários, hashes e relacionamentos antes/depois.

### Rollback / recuperação

- **Preferencial:** restaurar do backup.
  ```sh
  pg_restore --clean --if-exists -d "$DATABASE_URL" pre_0001.dump
  ```
- **Estrutural (quando o restore não for viável):**
  ```sh
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/migrations/0001_ROLLBACK.sql
  ```
  Lossless para dados de negócio (o `enumerator` é o mesmo texto). O `entry_key`
  é descartado no rollback por não ser referenciado por nenhuma FK.

### Segurança

- **Nunca** use `DROP SCHEMA` como estratégia de migração. O `DROP SCHEMA public
  CASCADE` existente só roda no cluster efêmero `*_test`
  (`tests/utils/db_utils.py`, com guarda `_test`), jamais no banco da API.
