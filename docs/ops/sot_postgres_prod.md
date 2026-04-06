# Checklist operacional — SoT Postgres (11 `raw.*` canónicas)

Executar na máquina de produção após deploy do código que escreve só nas tabelas canónicas.

## 1. Backfill

```bash
# Dry-run (logs apenas)
python -m ops.migrations.source_separate_raw --postgres-url "$POSTGRES_URL"

# Executar (ajustar URL)
python -m ops.migrations.source_separate_raw --confirm --postgres-url "$POSTGRES_URL"

# Só DOU
python -m ops.migrations.source_separate_raw --confirm --dou-only --postgres-url "$POSTGRES_URL"

# Se contagens TCU/DOU divergirem do esperado mas forem aceitáveis
python -m ops.migrations.source_separate_raw --confirm --relax-count-check --postgres-url "$POSTGRES_URL"
```

Se as tabelas TCU CSV estiverem em layout **colunar** (sem `all_fields`), o script **omite** os `INSERT` envelope para esses alvos; completar com:

```bash
python -m src.backend.ingest.tcu_csv_postgres_ingest --all --year-from 2002 --year-to 2026
```

## 2. Validação rápida

```sql
SELECT COUNT(*) FROM raw.dou_documents_raw;
-- Comparar com legado antes de arquivar:
-- SELECT COUNT(*) FROM raw.dou_documents_raw_data;
```

## 3. Arquivo de tabelas legadas

Ver e executar (com backup / janela de manutenção): [`ops/migrations/raw_legacy_archive.sql`](../../ops/migrations/raw_legacy_archive.sql).

## 4. Infra Elasticsearch (opcional / cutover)

Se a stack prod já não usar ES:

```bash
docker compose -f docker-compose.prod.yml stop elasticsearch worker || true
docker compose -f docker-compose.prod.yml rm -f elasticsearch worker || true
# Listar e remover volume de dados ES após backup
docker volume ls | grep -i elastic
```

Libertar disco montado (ex.: `elastic_data`) só após confirmar que não há rollback necessário.

## 5. Migrações Mongo legadas

`python -m ops.migrations.run` exige `GABI_ALLOW_LEGACY_MONGO_MIGRATION=1`. Sem isso, o comando termina com mensagem a indicar ingest canónico em `src/backend/ingest`.
