# Database: `gabi`

**Engine:** PostgreSQL 16 (pgvector/pgvector:pg16)  
**Owner:** gabi  
**Encoding:** UTF8  
**Collation:** en_US.utf8  
**Tamanho total:** 107 GB  
**Schemas:** `public` (vazio), `raw` (dados)

---

## Schema `raw` — Tabelas

| Tabela | Linhas (est.) | Tamanho | Última ingestão | Tipo |
|--------|--------------|---------|-----------------|------|
| [dou_documents](tables/dou_documents.md) | 15.853.837 | 89 GB | 2026-04-04 | Tipada |
| [tcu_acordaos](tables/tcu_acordaos.md) | 547.490 | 11 GB | 2026-04-05 | Tipada (CSV TCU) |
| [tcu_acordaos_raw_data](tables/tcu_acordaos_raw_data.md) | 547.490 | 6,1 GB | 2026-04-05 | JSONB puro |
| [tcu_btcu_raw_data](tables/tcu_btcu_raw_data.md) | 223.515 | 822 MB | 2026-04-04 | JSONB puro |
| [tcu_normas_raw_data](tables/tcu_normas_raw_data.md) | 16.413 | 90 MB | 2026-04-04 | JSONB puro |
| [tcu_publicacoes_raw_data](tables/tcu_publicacoes_raw_data.md) | 667 | 39 MB | 2026-04-04 | JSONB puro |
| [migration_log](tables/migration_log.md) | 10 | 32 kB | 2026-04-05 | Meta / Auditoria |

---

## Índices

| Índice | Tabela | Tipo | Coluna(s) |
|--------|--------|------|-----------|
| `dou_documents_pkey` | dou_documents | UNIQUE BTREE | id |
| `ix_raw_dou_documents_art_type` | dou_documents | BTREE | art_type |
| `ix_raw_dou_documents_pub_date` | dou_documents | BTREE | pub_date |
| `ix_raw_dou_documents_raw_html_hash` | dou_documents | BTREE | raw_html_hash |
| `migration_log_pkey` | migration_log | UNIQUE BTREE | id |
| `tcu_acordaos_pkey` | tcu_acordaos | UNIQUE BTREE | id |
| `ix_raw_tcu_acordaos_area` | tcu_acordaos | BTREE | area |
| `ix_raw_tcu_acordaos_data_sessao` | tcu_acordaos | BTREE | data_sessao |
| `ix_raw_tcu_acordaos_source_type` | tcu_acordaos | BTREE | source_type |
| `ix_raw_tcu_acordaos_tipo` | tcu_acordaos | BTREE | tipo |
| `tcu_acordaos_raw_data_pkey` | tcu_acordaos_raw_data | UNIQUE BTREE | id |
| `tcu_btcu_raw_data_pkey` | tcu_btcu_raw_data | UNIQUE BTREE | id |
| `tcu_normas_raw_data_pkey` | tcu_normas_raw_data | UNIQUE BTREE | id |
| `tcu_publicacoes_raw_data_pkey` | tcu_publicacoes_raw_data | UNIQUE BTREE | id |

**Nota:** Tabelas `tcu_btcu_raw_data`, `tcu_normas_raw_data` e `tcu_publicacoes_raw_data` possuem apenas PK. Sem índices de busca em campos do JSONB.

---

## Foreign Keys

**Nenhuma FK física definida.** Relacionamentos são implícitos:

- `tcu_acordaos.id` ↔ `tcu_acordaos_raw_data.id` (100% sobreposição, mesmo conjunto de IDs)

---

## Sprint 2 — Tabelas Planejadas (não criadas ainda)

As tabelas abaixo serão criadas pelo pipeline `tcu_csv_raw_pg.py` quando o Sprint 2 for executado:

| Tabela | Linhas esperadas | Schema |
|--------|-----------------|--------|
| `raw.tcu_acordao_completo_raw` | 520.353 | Colunar (CSV headers) |
| `raw.tcu_jurisprudencia_selecionada_raw` | 17.016 | Colunar (CSV headers) |
| `raw.tcu_resposta_consulta_raw` | 522 | Colunar (CSV headers) |
| `raw.tcu_sumula_raw` | 294 | Colunar (CSV headers) |
| `raw.tcu_boletim_jurisprudencia_raw` | 5.828 | Colunar (CSV headers) |
| `raw.tcu_boletim_pessoal_raw` | 1.500 | Colunar (CSV headers) |
| `raw.tcu_boletim_informativo_lc_raw` | 1.977 | Colunar (CSV headers) |
| `raw.tcu_normas_raw` | 16.413 | Colunar (CSV headers) |
| `raw.tcu_csv_fetch_meta` | — | Meta de fetch por fonte/ano |

---

## Configuração de Manutenção

| Parâmetro | Status | Recomendação |
|-----------|--------|-------------|
| VACUUM | Nunca executado | Configurar `autovacuum = on` |
| ANALYZE | Nunca executado | Executar `ANALYZE raw.*;` após ingestões |
| Extensões | pgvector instalado | Pronto para embeddings vetoriais |
