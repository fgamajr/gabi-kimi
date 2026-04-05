# Tabela: `raw.tcu_publicacoes_raw_data`

**Criticidade:** 🟢 ATIVA  
**Linhas:** 667 (contagem exata)  
**Tamanho total:** 39 MB  
**Origem:** Portal TCU — scraping via pipeline `tcu_publicacoes`  
**Última ingestão:** 2026-04-04 (raw_dump — 667/667 ok)

---

## Descrição

Repositório de **publicações institucionais do TCU** — cartilhas, manuais, tutoriais, cadernos temáticos e relatórios de auditoria educacional. Corpus obtido via scraping do portal TCU. Cada linha representa uma publicação com título, descrição, texto completo extraído de PDF e links para download.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | ID hash da publicação (ex: `tcu-pub-aedd96fb...`) |
| 2 | `all_fields` | `jsonb` | NO | — | — | Documento MongoDB completo como JSONB |
| 3 | `dumped_at` | `timestamptz` | NO | — | `now()` | Timestamp do dump |

---

## Campo `all_fields` (JSONB) — Chaves Identificadas

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | 667 | string | ID hash do documento |
| `doc_id` | 667 | string | Mesmo que `_id` |
| `title` | 667 | string | Título da publicação |
| `description` | 667 | string/null | Descrição editorial |
| `slug` | 667 | string | Slug de URL (ex: `cartilha-manual-ou-tutorial/inclusao-transforma`) |
| `pub_type` | 667 | string | Tipo de publicação (Cartilha, Caderno Temático, etc.) |
| `pub_date` | 667 | date | Data de publicação |
| `body_plain` | 667 | string | Texto completo extraído dos PDFs |
| `page_count` | 667 | int | Total de páginas dos PDFs |
| `pdf_urls` | 667 | array | URLs dos PDFs no portal TCU |
| `source_url` | 667 | string | URL da página no portal |
| `source_type` | 667 | string | Sempre `"tcu_publicacoes"` |
| `deterministic_hash` | 667 | string | Hash determinístico do conteúdo |
| `search_all` | 667 | string | Campo concatenado para busca |
| `indexed_at` | 667 | timestamp | Quando indexado no ES |
| `embedding_status` | 667 | string | Status do embedding |
| `embedding_model` | 667 | string | Modelo de embedding usado |
| `embedding_updated_at` | 667 | timestamp | Quando o embedding foi atualizado |
| `updated_at` | 667 | timestamp | Última atualização do registro |

---

## Exemplos de Publicações

| slug | title |
|------|-------|
| `cartilha-manual-ou-tutorial/inclusao-transforma` | Inclusão Transforma |
| `Caderno Temático/caderno-audeducacao-direitos-humanos-2022-2025` | Caderno AudEducação - Direitos Humanos 2022-2025 |
| `Caderno Temático/caderno-audeducacao-esporte-2018-2025` | Caderno AudEducação - Esporte 2018-2025 |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_publicacoes_raw_data_pkey` | UNIQUE BTREE | `id` |

---

## Problemas / Notas

- ℹ️ Menor tabela — 667 registros, baixo risco
- ℹ️ `pub_type` poderia virar coluna tipada para filtragem direta sem JSONB
- 🥈 Boa candidata para RAG — textos editorizados, conteúdo rico e estruturado
- ℹ️ IDs como hashes SHA256 longos (64 chars) — padrão diferente das outras tabelas

---

## Classificação de Sensibilidade

**Público** — publicações institucionais TCU são de acesso irrestrito.
