# Tabela: `raw.dou_documents`

**Criticidade:** 🔴 CRÍTICA — Maior tabela do banco, fonte primária de documentos DOU  
**Linhas (exato):** 15.853.837 (~15.9M) — confirmado pelo migration_log e `COUNT(*)`  
**Tamanho total:** 89 GB  
**Cobertura temporal:** 2002-01-02 → 2026-03-30  
**Origem:** DOU/INLABS — pipeline `sync_dou.py` + `inlabs_daily.py`  
**Última ingestão:** 2026-04-04 (migration_log: 15.853.837 docs confirmados)

---

## Descrição

Repositório central de publicações do **Diário Oficial da União (DOU)**, Seções 1, 2 e 3 (incluindo Extras e Especiais). Cada linha representa um artigo/documento publicado no DOU, identificado por hash MD5 do conteúdo HTML original. Cobre 24 anos de publicações (2002–2026), com mais de 15 milhões de documentos.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | Hash MD5 do HTML original — identificador determinístico único |
| 2 | `pub_date` | `date` | YES | — | — | Data de publicação no DOU |
| 3 | `section` | `text` | YES | — | — | Seção do DOU: DO1, DO2, DO3, DO1E, DO2E, DO3E, DO1A, etc. |
| 4 | `source_zip` | `text` | YES | — | — | Nome do arquivo ZIP de origem (ex: `S02012002.zip`) |
| 5 | `art_type` | `text` | YES | — | — | Tipo do ato: PORTARIA, EXTRATO, AVISO, EDITAL, etc. |
| 6 | `content_html` | `text` | YES | — | — | HTML bruto do documento conforme publicado |
| 7 | `raw_html_hash` | `text` | NO | — | — | Hash SHA do HTML — usado para dedup em reprocessamento |
| 8 | `all_fields` | `jsonb` | NO | — | — | Todos os campos enriquecidos pelo pipeline de ingestão |
| 9 | `migrated_at` | `timestamptz` | NO | — | `now()` | Timestamp da inserção no PostgreSQL |

---

## Campo `all_fields` (JSONB) — Chaves Identificadas

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | universal | string | Mesmo que `id` |
| `source_type` | universal | string | Sempre `"dou"` |
| `issuing_organ` | universal | string | Órgão emissor do ato |
| `normalized_title` | universal | string | Título normalizado do artigo |
| `art_type_normalized` | universal | string | Tipo normalizado (uppercase canônico) |
| `section` | universal | string | Seção do DOU |
| `edition_date` | universal | string | Data da edição |
| `indexed_at` | universal | timestamp | Quando indexado no ES |
| `embedding_status` | universal | string | Status do embedding vetorial: `pending`, `done`, `error` |
| `parse_quality_score` | universal | float | Score de qualidade do parse (0-1) |
| `reconstruction_status` | universal | string | Status da reconstrução textual |
| `reconstruction_notes` | universal | string/null | Notas do processo de reconstrução |
| `organization_path_string` | universal | string | Hierarquia organizacional do órgão emissor |
| `signatures` | universal | array | Assinaturas identificadas no documento |
| `logical_doc_id` | universal | string | ID lógico para agrupamento multipart |
| `multipart_seq` | universal | int | Sequência em documentos multipart |
| `is_revocation` | universal | bool | Indica se o ato é revogação de outro |
| `text_language` | universal | string | Idioma detectado (geralmente `pt`) |
| `image_count` | universal | int | Número de imagens no HTML |
| `parse_errors` | universal | array | Erros detectados no parse |
| `search_all` | universal | string | Campo concatenado para busca full-text |

---

## Distribuição por Seção

| Seção | Documentos | % |
|-------|-----------|---|
| DO3 (Contratos/Licitações) | 11.287.999 | 72,1% |
| DO2 (Executivo) | 2.730.180 | 17,4% |
| DO1 (Legislativo/Judiciário) | 1.804.860 | 11,5% |
| Extras e Especiais | ~30.000 | 0,2% |

---

## Top Tipos de Ato

| art_type | Documentos |
|----------|-----------|
| EXTRATO | 2.420.752 |
| Portaria | 1.324.423 |
| AVISO | 1.285.235 |
| PORTARIA | 1.250.423 |
| Extrato de Termo Aditivo | 680.018 |
| Extrato de Contrato | 665.164 |

---

## Índices

| Índice | Tipo | Coluna | Uso |
|--------|------|--------|-----|
| `dou_documents_pkey` | UNIQUE BTREE | `id` | Lookup por ID hash |
| `ix_raw_dou_documents_pub_date` | BTREE | `pub_date` | Filtragem por data |
| `ix_raw_dou_documents_art_type` | BTREE | `art_type` | Filtragem por tipo |
| `ix_raw_dou_documents_raw_html_hash` | BTREE | `raw_html_hash` | Deduplicação |

---

## Problemas / Notas

- ⚠️ `pub_date` é **nullable** — 0 nulos hoje, mas sem restrição; considerar `NOT NULL`
- ℹ️ Contagem exata (15.853.837) > estimativa do planner (15.649.937): diferença devida à ausência de `ANALYZE` — executar `ANALYZE raw.dou_documents` para corrigir
- ⚠️ `art_type` tem inconsistência de case (`PORTARIA` vs `Portaria`) — considerar normalizar
- ℹ️ `content_html` é o maior contribuinte de espaço em disco (~60–70 GB estimados)
- ℹ️ Candidata a **chunking** para RAG — usar `all_fields->>'search_all'` como campo base
- ⚠️ Sem índice em `all_fields->>'issuing_organ'` (filtro natural do usuário) — considerar coluna extraída ou GIN index em `all_fields` para queries `issuing_organ`
- 🔍 Campo `all_fields->>'embedding_status'` indica pipeline de embeddings pendente

---

## Classificação de Sensibilidade

**Público** — documentos publicados no DOU são de acesso irrestrito pela lei brasileira.  
Atenção: `signatures` pode conter nomes de servidores → classificar como **Interno** se necessário para LGPD.
