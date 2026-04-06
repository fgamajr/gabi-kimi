# Database: `gabi`

**Engine:** PostgreSQL 16 (pgvector/pgvector:pg16)  
**Owner:** gabi  
**Encoding:** UTF8  
**Collation:** en_US.utf8  
**Tamanho total:** ~95 GB (2026-04-05, pós-limpeza Sprint 2)  
**Schemas:** `public` (vazio), `raw` (dados)

---

## Schema `raw` — Tabelas

| Tabela | Linhas (live) | Tamanho | Tipo | Origem |
|--------|--------------|---------|------|--------|
| [dou_documents_raw_data](tables/dou_documents_raw_data.md) | 15.835.274 | 89 GB | Colunar + JSONB | DOU/INLABS |
| [tcu_acordao_completo_raw](tables/tcu_acordao_completo_raw.md) | 520.595 | 4,0 GB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_btcu_raw_data](tables/tcu_btcu_raw_data.md) | 223.515 | 822 MB | JSONB | BTCU API |
| [tcu_normas_raw](tables/tcu_normas_raw.md) | 16.443 | 98 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_jurisprudencia_selecionada_raw](tables/tcu_jurisprudencia_selecionada_raw.md) | 17.549 | 75 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_publicacoes_raw_data](tables/tcu_publicacoes_raw_data.md) | 667 | 39 MB | JSONB | Portal TCU (scraping) |
| [tcu_boletim_informativo_lc_raw](tables/tcu_boletim_informativo_lc_raw.md) | 1.977 | 6 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_boletim_jurisprudencia_raw](tables/tcu_boletim_jurisprudencia_raw.md) | 5.837 | 5 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_resposta_consulta_raw](tables/tcu_resposta_consulta_raw.md) | 523 | 4 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_boletim_pessoal_raw](tables/tcu_boletim_pessoal_raw.md) | 1.500 | 1,4 MB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_sumula_raw](tables/tcu_sumula_raw.md) | 294 | 720 kB | Colunar (CSV headers) | TCU Dados Abertos |
| [tcu_csv_fetch_meta](tables/tcu_csv_fetch_meta.md) | 42 | 64 kB | Meta / Controle | Pipeline interno |
| [migration_log](tables/migration_log.md) | 10 | 32 kB | Meta / Auditoria | Pipeline interno |

---

## Índices

| Índice | Tabela | Tipo | Coluna(s) |
|--------|--------|------|-----------|
| `dou_documents_raw_data_pkey` | dou_documents_raw_data | UNIQUE BTREE | id |
| `ix_raw_dou_documents_raw_data_pub_date` | dou_documents_raw_data | BTREE | pub_date |
| `ix_raw_dou_documents_raw_data_art_type` | dou_documents_raw_data | BTREE | art_type |
| `ix_raw_dou_documents_raw_data_raw_html_hash` | dou_documents_raw_data | BTREE | raw_html_hash |
| `tcu_acordao_completo_raw_pkey` | tcu_acordao_completo_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_acordao_completo_raw_dumped_at` | tcu_acordao_completo_raw | BTREE | dumped_at DESC |
| `tcu_btcu_raw_data_pkey` | tcu_btcu_raw_data | UNIQUE BTREE | id |
| `tcu_normas_raw_pkey` | tcu_normas_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_normas_raw_dumped_at` | tcu_normas_raw | BTREE | dumped_at DESC |
| `tcu_jurisprudencia_selecionada_raw_pkey` | tcu_jurisprudencia_selecionada_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_jurisprudencia_selecionada_raw_dumped_at` | tcu_jurisprudencia_selecionada_raw | BTREE | dumped_at DESC |
| `tcu_publicacoes_raw_data_pkey` | tcu_publicacoes_raw_data | UNIQUE BTREE | id |
| `tcu_boletim_informativo_lc_raw_pkey` | tcu_boletim_informativo_lc_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_boletim_informativo_lc_raw_dumped_at` | tcu_boletim_informativo_lc_raw | BTREE | dumped_at DESC |
| `tcu_boletim_jurisprudencia_raw_pkey` | tcu_boletim_jurisprudencia_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_boletim_jurisprudencia_raw_dumped_at` | tcu_boletim_jurisprudencia_raw | BTREE | dumped_at DESC |
| `tcu_resposta_consulta_raw_pkey` | tcu_resposta_consulta_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_resposta_consulta_raw_dumped_at` | tcu_resposta_consulta_raw | BTREE | dumped_at DESC |
| `tcu_boletim_pessoal_raw_pkey` | tcu_boletim_pessoal_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_boletim_pessoal_raw_dumped_at` | tcu_boletim_pessoal_raw | BTREE | dumped_at DESC |
| `tcu_sumula_raw_pkey` | tcu_sumula_raw | UNIQUE BTREE | id |
| `ix_raw_tcu_sumula_raw_dumped_at` | tcu_sumula_raw | BTREE | dumped_at DESC |
| `tcu_csv_fetch_meta_pkey` | tcu_csv_fetch_meta | UNIQUE BTREE | url |
| `migration_log_pkey` | migration_log | UNIQUE BTREE | id |

**Nota:** Tabelas `tcu_btcu_raw_data` e `tcu_publicacoes_raw_data` possuem apenas PK. Sem índices em campos do JSONB.

---

## Foreign Keys

**Nenhuma FK física definida.** Relacionamentos são implícitos:

| De | Para | Via |
|----|------|-----|
| `tcu_jurisprudencia_selecionada_raw` | `tcu_acordao_completo_raw` | `NUMACORDAO` + `ANOACORDAO` |
| `tcu_resposta_consulta_raw` | `tcu_acordao_completo_raw` | `NUMACORDAO` + `ANOACORDAO` |
| `tcu_sumula_raw` | `tcu_acordao_completo_raw` | `NUMAPROVACAO` + `ANOAPROVACAO` |
| `tcu_boletim_jurisprudencia_raw` | `tcu_acordao_completo_raw` | `REFERENCIA` |
| `tcu_boletim_pessoal_raw` | `tcu_acordao_completo_raw` | `REFERENCIA` |
| `tcu_normas_raw` | `dou_documents_raw_data` | `NUMDOU` + `NUMSECAODOU` + `DATADOU` |
| `tcu_btcu_raw_data` | `tcu_acordao_completo_raw` | `all_fields->>'acordaos_citados'` |

---

## Tabelas removidas (histórico)

| Tabela | Removida em | Motivo |
|--------|------------|--------|
| `tcu_acordaos` | 2026-04-05 | Typed Sprint 1 — substituída por `tcu_acordao_completo_raw` |
| `tcu_acordaos_raw_data` | 2026-04-05 | JSONB legacy — subconjunto de `tcu_acordao_completo_raw`; continha 27.137 linhas contaminadas (BOLETIM, JURISPRUDÊNCIA SELECIONADA, RESPOSTA A CONSULTA, SÚMULA) |
| `tcu_normas_raw_data` | 2026-04-05 | JSONB legacy — subconjunto de `tcu_normas_raw` |

---

## Configuração de Manutenção

| Parâmetro | Status | Recomendação |
|-----------|--------|-------------|
| VACUUM | Nunca executado | Configurar `autovacuum = on` |
| ANALYZE | Nunca executado | Executar `ANALYZE raw.*;` após ingestões |
| Extensões | pgvector instalado | Pronto para embeddings vetoriais |
