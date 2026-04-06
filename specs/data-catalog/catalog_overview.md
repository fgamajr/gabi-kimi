# GABI — Data Catalog Overview

**Gerado em:** 2026-04-05  
**Servidor:** Hetzner CPX42 — `gabi-prod` (204.168.173.163)  
**Engine:** PostgreSQL 16 (pgvector/pgvector:pg16)  
**Container:** `gabi-kimi-postgres`

---

## Databases

| Database | Owner | Encoding | Tamanho total |
|----------|-------|----------|---------------|
| `gabi` | gabi | UTF8 | **107 GB** |
| `postgres` | gabi | UTF8 | — (sistema) |

---

## Schemas — Database `gabi`

| Schema | Owner | Propósito |
|--------|-------|-----------|
| `public` | pg_database_owner | Vazio — reservado |
| `raw` | gabi | **Fonte de verdade** — dados ingeridos de todas as fontes |

---

## Resumo de Tabelas

### Canónicas (SoT — ingest actual)

| Tabela | Schema | Linhas (aprox.) | Fonte | Notas |
|--------|--------|-----------------|-------|--------|
| `dou_documents_raw` | raw | ~15,9M | DOU/INLABS | JSONB `all_fields`; ingest [`sync_dou`](../../src/backend/ingest/sync_dou.py) |
| `tcu_acordao_completo_raw` … `tcu_boletim_informativo_lc_raw` (8) | raw | ver catálogo CSV | TCU CSV | Layout **colunar** via `tcu_csv_postgres_ingest` |
| `tcu_normas_raw` | raw | ~16,4k | norma.csv | Colunar ou envelope conforme deploy |
| `tcu_btcu_raw` | raw | ~223k | BTCU scrape | JSONB envelope |
| `tcu_publicacoes_raw` | raw | ~667 | Portal TCU | JSONB envelope |
| `tcu_csv_fetch_meta` | raw | — | — | Metadados de fetch |

### Legado (arquivar após paridade)

| Tabela | Schema | Estado |
|--------|--------|--------|
| `dou_documents_raw_data` | raw | Substituída por `dou_documents_raw` |
| `tcu_acordaos` / `tcu_acordaos_raw_data` | raw | Tipada + JSONB consolidado |
| `tcu_btcu_raw_data` / `tcu_normas_raw_data` / `tcu_publicacoes_raw_data` | raw | Substituídas pelas tabelas `*_raw` homónimas |
| [`migration_log`](databases/gabi/tables/migration_log.md) | raw | Auditoria migrações legadas |

Ver [`ops/migrations/raw_legacy_archive.sql`](../../ops/migrations/raw_legacy_archive.sql) para renomear legado.

**Tamanho total do banco (snapshot anterior):** ~107 GB — revalidar após cutover.

---

## Onze fontes raw alinhadas ao código

| Tabela | Fonte |
|--------|--------|
| `raw.dou_documents_raw` | INLABS/Liferay |
| `raw.tcu_acordao_completo_raw` | acordao-completo-{ano}.csv |
| `raw.tcu_jurisprudencia_selecionada_raw` | jurisprudencia-selecionada.csv |
| `raw.tcu_resposta_consulta_raw` | resposta-consulta.csv |
| `raw.tcu_sumula_raw` | sumula.csv |
| `raw.tcu_boletim_jurisprudencia_raw` | boletim-jurisprudencia.csv |
| `raw.tcu_boletim_pessoal_raw` | boletim-pessoal.csv |
| `raw.tcu_boletim_informativo_lc_raw` | boletim-informativo-lc.csv |
| `raw.tcu_normas_raw` | norma.csv |
| `raw.tcu_btcu_raw` | BTCU (scrape) |
| `raw.tcu_publicacoes_raw` | Publicações TCU (scrape) |

---

## Arquitetura de Dados (alvo)

```
Fontes externas                         PostgreSQL raw.* (canónico)
├── DOU/INLABS ───────────────────────→ raw.dou_documents_raw
├── TCU CSV (8 ficheiros) ─────────────→ raw.tcu_*_raw (colunar)
├── norma.csv ─────────────────────────→ raw.tcu_normas_raw
├── BTCU scrape ───────────────────────→ raw.tcu_btcu_raw
└── Publicações scrape ────────────────→ raw.tcu_publicacoes_raw
```

---

## Relacionamentos Lógicos

Não existem **foreign keys físicas**. Entre **legado** `raw.tcu_acordaos` / `raw.tcu_acordaos_raw_data` os `id` alinhavam 1:1; o alvo de ingest é agora o conjunto de onze `raw.*_raw` canónicas (ver secção «Onze fontes» acima).

Ver [`erd.json`](databases/gabi/erd.json) para grafo completo.

---

## Problemas Identificados

| Severidade | Tabela | Problema | Recomendação |
|-----------|--------|---------|--------------|
| 🟡 MÉDIO | `tcu_acordaos_raw_data` | Duplica IDs de `tcu_acordaos` — 6 GB redundantes | DROP apenas após Sprint 2 concluído: `tcu_acordaos_raw_data` ainda contém `tcu_jurisprudencia`, `tcu_sumula`, `tcu_boletim_*` que não estarão nas novas tabelas até a migração ser validada |
| 🟡 MÉDIO | `tcu_acordaos` | Colunas `area`, `tema`, `subtema`, `autortese` com alto índice de NULL | Verificar preenchimento nas fontes CSV |
| 🟡 MÉDIO | `dou_documents` | `pub_date` nullable — risco de documentos sem data | Adicionar NOT NULL após limpeza |
| 🔴 ALTO | todas as tabelas | Nenhuma operação de VACUUM/ANALYZE registrada | Configurar autovacuum ou executar manualmente |
| 🟡 MÉDIO | `raw schema` | Ausência de índices em `tcu_btcu_raw_data`, `tcu_normas_raw_data`, `tcu_publicacoes_raw_data` | Adicionar índice em `dumped_at` para auditoria |
| ⚪ INFO | `public schema` | Schema vazio | Manter reservado para futuras tabelas tipadas |

---

## Candidatas a RAG / Embeddings

| Tabela | Campo de texto | Prioridade | Justificativa |
|--------|---------------|-----------|--------------|
| `raw.tcu_acordaos` | `all_fields->>'sumario'`, `all_fields->>'voto'` | 🥇 ALTA | Jurisprudência: textos densos, semanticamente ricos (`relatorio` é indicador bool `has_relatorio`, não campo de texto) |
| `raw.tcu_normas_raw_data` | `all_fields->>'texto_norma'` | 🥇 ALTA | Normas internas: curtas e precisas, ótimas para RAG |
| `raw.dou_documents` | `content_html` / `all_fields->>'search_all'` | 🥈 MÉDIA | Volume enorme — usar subset ou chunking |
| `raw.tcu_publicacoes_raw_data` | `all_fields->>'body_plain'` | 🥈 MÉDIA | 667 docs, conteúdo editorializado |
| `raw.tcu_btcu_raw_data` | `all_fields->>'texto_completo'` | 🥉 BAIXA | Já é boletim — redundante com acordaos |
