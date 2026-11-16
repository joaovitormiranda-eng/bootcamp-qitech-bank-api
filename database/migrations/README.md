# Migrações de banco

Este diretório contém migrações **SQL versionadas** aplicadas sobre um banco
PostgreSQL **já populado**. Um banco vazio é criado diretamente por
`database/database.sql`, que já está no schema atual; as migrações existem para
evoluir instalações criadas com um schema anterior **sem perder dados**.

> Não há Alembic no projeto (o schema é instalado por `database.sql` no
> `docker-entrypoint-initdb.d`). Estas migrações são scripts `psql` idempotentes.
> O guia completo, com comandos para Docker Compose, validação e recuperação,
> está em [`docs/MIGRACOES.md`](../../docs/MIGRACOES.md).

## Convenção

- Nome: `NNNN_descricao.sql` (ordem lexicográfica = ordem de aplicação).
- Cada migração tem um par `NNNN_ROLLBACK.sql`.
- Toda migração roda em **transação única** com `ON_ERROR_STOP=1`
  (`ROLLBACK` total em qualquer erro).
- Idempotente: reexecutar não duplica objetos nem dados de lookup.

## 0001 — lookups de enumeração e `entry_key`

`0001_cod05_cod06_lookup_and_entry_key.sql`

- Cria as lookups `client_type`, `transaction_type`, `transaction_direction`,
  `entry_type` e `actor_type`; preenche as novas FKs `*_id` a partir das colunas
  textuais; remove os `CHECK IN (...)` e as colunas textuais.
- Adiciona `transaction_entry.entry_key UUID NOT NULL UNIQUE`, preenchendo cada
  linha com `gen_random_uuid()` (valores **aleatórios**). O preenchimento só
  atinge linhas com `entry_key IS NULL`, então reexecuções preservam as chaves
  já atribuídas. A chave interna `id` (PK), as FKs e a ordenação não mudam.

`psql` e `pg_dump` não aceitam o formato `postgresql+psycopg2://` do
`DATABASE_URL` usado pela aplicação. Nos exemplos abaixo, `$PG_URL` é uma URL
`postgresql://usuario:senha@host:porta/banco`.

### Pré-condições (obrigatórias em ambiente não-efêmero)

1. **Backup:** `pg_dump` completo ANTES de aplicar.
   ```sh
   pg_dump "$PG_URL" -Fc -f pre_0001.dump
   ```
2. Janela de manutenção (a migração faz `ALTER TABLE`/`DROP COLUMN`).

### Aplicar

```sh
psql "$PG_URL" -v ON_ERROR_STOP=1 \
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
  pg_restore --clean --if-exists -d "$PG_URL" pre_0001.dump
  ```
- **Estrutural (quando o restore não for viável):**
  ```sh
  psql "$PG_URL" -v ON_ERROR_STOP=1 -f database/migrations/0001_ROLLBACK.sql
  ```
  Preserva os dados de negócio (o texto das enumerações é reconstruído a partir
  do `enumerator`). O `entry_key` é descartado no rollback por não ser
  referenciado por nenhuma FK. Após o rollback, o banco volta ao schema anterior
  e não é compatível com a versão atual da API.

### Segurança

- **Nunca** use `DROP SCHEMA` como estratégia de migração. O `DROP SCHEMA public
  CASCADE` existente só roda no cluster efêmero `*_test`
  (`tests/utils/db_utils.py`, com guarda `_test`), jamais no banco da API.
