# Tabela: `raw.migration_log`

**Criticidade:** ⚪ META — Tabela de auditoria de ingestões  
**Linhas:** 10 (contagem exata)  
**Tamanho total:** 32 kB  
**Origem:** Gerada pelo pipeline `tcu_csv_postgres_ingest.py`

---

## Descrição

Registro de auditoria de cada execução do pipeline de ingestão para o PostgreSQL. Cada linha representa uma operação (`raw_dump` ou `typed_materialization`) para uma fonte específica, com contagens de validação (fonte vs. PostgreSQL) e status.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `bigint` | NO | ✅ | `nextval(...)` | ID sequencial autoincrement |
| 2 | `collection` | `text` | NO | — | — | Nome da coleção/fonte (ex: `tcu_acordaos`, `dou_documents`) |
| 3 | `stage` | `text` | NO | — | — | Etapa: `raw_dump` ou `typed_materialization` |
| 4 | `count_mongo` | `bigint` | YES | — | — | Contagem de documentos na fonte (CSV ou API) — nome histórico da coluna |
| 5 | `count_postgres` | `bigint` | YES | — | — | Contagem de documentos inseridos no PostgreSQL |
| 6 | `hash_errors` | `integer` | NO | — | `0` | Número de erros de hash durante a ingestão |
| 7 | `duration_s` | `float8` | YES | — | — | Duração da operação em segundos |
| 8 | `status` | `text` | NO | — | — | Status: `ok` ou `error` |
| 9 | `details` | `jsonb` | YES | — | — | Detalhes adicionais (erros, avisos, metadados) |
| 10 | `ran_at` | `timestamptz` | NO | — | `now()` | Timestamp de execução |

---

## Histórico de Ingestões

| collection | stage | count_mongo | count_postgres | status | ran_at |
|-----------|-------|-------------|----------------|--------|--------|
| tcu_acordaos | typed_materialization | 547.490 | 547.490 | ok | 2026-04-05 16:48 |
| tcu_acordaos | raw_dump | 547.490 | 547.490 | ok | 2026-04-05 16:38 |
| tcu_acordaos | raw_dump | 547.490 | 547.490 | ok | 2026-04-05 16:32 |
| tcu_acordaos | raw_dump | 547.490 | 547.490 | ok | 2026-04-04 21:18 |
| dou_documents | raw_dump | 15.853.837 | 15.853.837 | ok | 2026-04-04 17:04 |
| tcu_publicacoes | raw_dump | 667 | 667 | ok | 2026-04-04 13:45 |
| tcu_btcu | raw_dump | 223.515 | 223.515 | ok | 2026-04-04 13:45 |
| tcu_normas | raw_dump | 16.413 | 16.413 | ok | 2026-04-04 13:40 |
| tcu_acordaos | typed_materialization | 547.490 | 547.490 | ok | 2026-04-04 13:40 |
| tcu_acordaos | raw_dump | 547.490 | 547.490 | ok | 2026-04-04 13:31 |

**Todas as ingestões: status `ok`, zero hash_errors, zero divergências.**

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `migration_log_pkey` | UNIQUE BTREE | `id` |

---

## Notas

- ℹ️ Sem índice em `collection` ou `ran_at` — volume baixo, sem necessidade
- ℹ️ `count_mongo` vs `count_postgres` = validação de integridade da ingestão (nome `count_mongo` é legado — representa contagem da fonte, seja CSV ou API)
- ℹ️ Tabela deve crescer a cada nova ingestão — manter como histórico permanente

---

## Classificação de Sensibilidade

**Interno** — metadados operacionais do sistema.
