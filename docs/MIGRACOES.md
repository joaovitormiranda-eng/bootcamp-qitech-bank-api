# Migrações de schema — BaaS Simplificado

**Bootcamp QI Tech 2026** · **Versão:** P2-Final

**Documentos relacionados:** [ERD](ERD.md) · [CI/DevSecOps](CI-DEVSECOPS.md) · [README das migrações](../database/migrations/README.md) · [Auditoria P1-D](P1D-DATABASE-AUDIT.md)

> Documento-índice da estratégia de migração. A referência operacional detalhada
> (pré-condições, backup, aplicação, rollback) é
> [`database/migrations/README.md`](../database/migrations/README.md); os scripts
> executáveis estão em [`database/migrations/`](../database/migrations/).

## 1. Estratégia

- **Bootstrap de banco vazio:** `database/database.sql` instala o schema **alvo**
  (já no estado pós-P1-D, 15 tabelas). No Compose, roda em
  `docker-entrypoint-initdb.d` no primeiro provisionamento de um volume vazio.
- **Evolução de banco populado:** migrações **SQL versionadas** em
  `database/migrations/`, aplicadas via `psql`. **Não há Alembic** no projeto.
- **Convenção:** `NNNN_descricao.sql` (ordem lexicográfica = ordem de aplicação),
  cada migração com um par `NNNN_ROLLBACK.sql`.
- **Transação única:** cada migração roda com `ON_ERROR_STOP=1` e `BEGIN/COMMIT`
  — qualquer erro provoca `ROLLBACK` total.
- **Idempotência:** reexecutar não duplica objetos nem dados de lookup
  (`CREATE TABLE IF NOT EXISTS`, seed com `ON CONFLICT (enumerator) DO NOTHING`).

## 2. Migração 0001 — COD-05/COD-06 (lookups + entry_key)

Arquivo: [`0001_cod05_cod06_lookup_and_entry_key.sql`](../database/migrations/0001_cod05_cod06_lookup_and_entry_key.sql).

Fato verificado (leitura do SQL):

- **COD-06:** cria as lookups `client_type`, `transaction_type`,
  `transaction_direction`, `entry_type`, `actor_type`; para cada enumeração,
  adiciona a coluna `*_id`, **faz backfill** texto→FK, assere ausência de `NULL`
  (`RAISE EXCEPTION` se incompleto), define `NOT NULL` + `FOREIGN KEY ON DELETE
  RESTRICT`, remove o `CHECK IN (...)` e **dropa a coluna textual**, e cria os
  índices de suporte (`idx_client_type`, `idx_financial_transaction_type`,
  `idx_transaction_entry_direction`, `idx_transaction_entry_entry_type`).
- **COD-05:** adiciona `transaction_entry.entry_key UUID NOT NULL UNIQUE`,
  fazendo o backfill por linha com `gen_random_uuid()` (extensão `pgcrypto`),
  preservando a PK `id BIGINT` e todas as FKs/ordenação. Os UUIDs gerados são
  **aleatórios** (não determinísticos): cada execução que precise preencher uma
  linha nova sorteia um UUID novo. Isso **não** compromete a idempotência da
  migração — o backfill roda com `WHERE entry_key IS NULL`, então uma reexecução
  **preserva** os `entry_key` já existentes e não os regera (ver §3 e §4). Ou
  seja, a propriedade garantida é "não sobrescrever chaves existentes em
  reexecução", e não "produzir sempre o mesmo UUID para a mesma linha".
- **Validação embutida:** a própria migração aborta via `RAISE EXCEPTION` se
  houver FK/`entry_key` nula, `entry_key` duplicado ou lookup com `enumerator`
  duplicado — **nunca** perda silenciosa de dados.

## 3. Rollback — `0001_ROLLBACK.sql`

Fato verificado. Restaura a estrutura legada (colunas textuais de volta, lookups
removidas) e é **lossless para dados de negócio** no round-trip
`migrate → rollback`: o `enumerator` é o mesmo texto reposto nas colunas. O
`entry_key` é descartado no rollback por não ser referenciado por nenhuma FK.

> Preferência operacional (ambiente não efêmero): restaurar de um `pg_dump`
> feito **antes** da migração. O rollback estrutural existe para quando o restore
> não for viável. Nunca usar `DROP SCHEMA` como estratégia de migração — o
> `DROP SCHEMA public CASCADE` só roda no cluster efêmero `*_test`, com guarda de
> sufixo em `tests/utils/db_utils.py`.

## 4. Como isso é provado (CI)

Dois mecanismos independentes, ambos verdes no CI:

1. **Job `migration`** (`.github/workflows/ci.yml`): cluster PostgreSQL efêmero
   dedicado (`127.0.0.1:5434`). Instala o schema **legado** populado
   (`tests/integration/database/legacy_schema.sql`), semeia dados representativos
   (PF/PJ, contas, saldos, históricos, depósitos, transferências, lançamentos,
   chaves de idempotência), tira *snapshots* `BEFORE`/`AFTER`, aplica a migração,
   confere contagens/`sum_balance`/integridade, **reexecuta** (idempotência =
   no-op) e aplica o **rollback** confirmando que os dados de negócio e o texto
   das enumerações são preservados.
2. **Teste pytest** `tests/integration/database/test_populated_migration.py`:
   exercita a migração em banco efêmero populado e compara contagem, identidade,
   valores monetários, hashes e relacionamentos antes/depois.

## 5. Limitações

- A migração `0001` é a **única** versionada até aqui; futuras evoluções devem
  seguir a mesma convenção (`NNNN_*.sql` + `NNNN_ROLLBACK.sql`, transação única,
  idempotência, validação por `RAISE EXCEPTION`).
- A validação de banco populado é exclusivamente **por CI** (sem PostgreSQL no
  host de desenvolvimento). A aba Actions é a fonte autoritativa.
