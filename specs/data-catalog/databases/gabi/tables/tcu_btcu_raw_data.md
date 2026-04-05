# Tabela: `raw.tcu_btcu_raw_data`

**Criticidade:** 🟢 ATIVA  
**Linhas estimadas:** 223.515  
**Tamanho total:** 822 MB  
**Origem:** BTCU API — pipeline de ingestão BTCU  
**Última ingestão:** 2026-04-04 (raw_dump — 223.515/223.515 ok)

---

## Descrição

Repositório do **Boletim do TCU (BTCU)** — publicação periódica que consolida deliberações, atas e decisões do TCU. Cada linha representa uma **seção/chunk** de um boletim, segmentado por `caderno` (Deliberações, Normas, etc.) e `section_type`. Os documentos preservam links para PDFs originais e referências cruzadas com acórdãos.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | ID do documento BTCU (ex: `BTCU-77828393`) |
| 2 | `all_fields` | `jsonb` | NO | — | — | Documento MongoDB completo como JSONB |
| 3 | `dumped_at` | `timestamptz` | NO | — | `now()` | Timestamp do dump |

---

## Campo `all_fields` (JSONB) — Chaves Identificadas

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | 223.515 | string | ID do documento |
| `caderno` | 223.515 | string | Caderno do BTCU (Deliberações, Normas, etc.) |
| `section_type` | 223.515 | string | Tipo de seção dentro do caderno |
| `section_title` | 223.515 | string | Título da seção |
| `assunto` | 223.515 | string | Assunto/tema da edição do boletim (não confundir com `data_publicacao`) |
| `data_publicacao` | 223.515 | date | Data de publicação do boletim |
| `num_pages` | 223.515 | int | Número de páginas do PDF |
| `page_range` | 223.515 | string | Intervalo de páginas desta seção |
| `chunk_sequence` | 223.515 | int | Sequência do chunk no boletim |
| `parent_btcu_id` | 223.515 | string | ID do boletim pai (agrupamento) |
| `pdf_url` | 223.515 | string | URL do PDF original no portal BTCU |
| `texto_completo` | 223.515 | string | Texto extraído do PDF |
| `search_all` | 223.515 | string | Campo concatenado para busca |
| `acordaos_citados` | 223.515 | array | IDs de acórdãos referenciados no texto |
| `normative_references` | 223.515 | array | Referências normativas (leis, decretos, etc.) |
| `valores_monetarios` | 223.515 | array | Valores monetários mencionados |
| `source_type` | 223.515 | string | Sempre `"btcu"` |
| `indexed_at` | 223.515 | timestamp | Quando indexado no ES |
| `embedding_status` | 223.515 | string | Status do embedding |
| `embedding_queued_at` | 223.515 | timestamp | Quando enfileirado para embedding |
| `updated_at` | 223.515 | timestamp | Última atualização do registro |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_btcu_raw_data_pkey` | UNIQUE BTREE | `id` |

---

## Problemas / Notas

- ⚠️ Sem índice em `all_fields->>'data_publicacao'` — adicionar GIN ou BTREE extraído para buscas temporais
- ℹ️ `acordaos_citados` cria relacionamento implícito com `tcu_acordaos` via IDs
- ℹ️ Candidato a indexação por `caderno` para filtragem eficiente
- 🥉 Candidato de baixa prioridade para RAG — usar `texto_completo`, mas verificar redundância com `tcu_acordaos`

---

## Classificação de Sensibilidade

**Público** — BTCU é publicação oficial do TCU de acesso irrestrito.
