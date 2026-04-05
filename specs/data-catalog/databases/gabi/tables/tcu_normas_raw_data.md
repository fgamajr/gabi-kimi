# Tabela: `raw.tcu_normas_raw_data`

**Criticidade:** 🟢 ATIVA  
**Linhas estimadas:** 16.413  
**Tamanho total:** 90 MB  
**Origem:** TCU Normas CSV — pipeline `tcu_normas_processor.py`  
**Última ingestão:** 2026-04-04 (raw_dump — 16.413/16.413 ok)

---

## Descrição

Repositório de **normas internas do TCU** — portarias, resoluções, instruções normativas e atos administrativos emitidos pelas unidades do Tribunal. Cada linha representa uma norma vigente ou revogada, com links para o BTCU e DOU quando aplicável. Os textos completos das normas são armazenados em `all_fields->>'texto_norma'`.

> **Nota Sprint 2:** Esta tabela usa schema JSONB (`all_fields`). O Sprint 2 criará `raw.tcu_normas_raw` com colunas explícitas por campo CSV: `UNIDADEBASICAAUTORA`, `ORIGEM`, `NUMNORMA`, `ANONORMA`, `TIPONORMA`, `NUMEROPROCESSO`, `TITULO`, `ASSUNTO`, `TEXTONORMA`, `DATAINICIOVIGENCIA`, `DATAFIMVIGENCIA`, `SITUACAO`, `LINKBTCU`, `TEXTOANEXO`, `ARQUIVONORMA`, `PAGINABTCU`, `TEMA`, `TAGSVCE`, `NORMARELACIONADA`, `NUMDOU`, `NUMSECAODOU`, `NUMPAGINADOU`, `DATADOU`, `INFOSGERAIS` (26 colunas).



---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | ID da norma (ex: `NORMA-45816`) |
| 2 | `all_fields` | `jsonb` | NO | — | — | Documento MongoDB completo como JSONB |
| 3 | `dumped_at` | `timestamptz` | NO | — | `now()` | Timestamp do dump |

---

## Campo `all_fields` (JSONB) — Chaves Identificadas

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | 16.413 | string | ID da norma |
| `titulo` | 16.413 | string | Título da norma (ex: "Portaria TCU nº 47/2026") |
| `tema` | 16.413 | string | Tema temático (ex: Gestão, Licitação) |
| `origem` | 16.413 | string | Unidade autora (ex: TCU, DIOP-ESTADOS, DIADI) |
| `unidade_autora` | 16.413 | string | Unidade organizacional emissora |
| `assunto` | 16.413 | string | Assunto da norma |
| `ano_norma` | 16.413 | int | Ano de emissão |
| `numero_processo` | 16.413 | string | Número do processo TCU |
| `vigente` | 16.413 | bool | Se a norma está vigente |
| `situacao` | 16.413 | string | Vigente, Revogada, etc. |
| `data_fim_vigencia` | 16.413 | date/null | Data de encerramento da vigência |
| `texto_norma` | 16.413 | string | Texto completo da norma |
| `link_btcu` | 16.413 | string | URL no portal BTCU |
| `num_dou` | 16.413 | string/null | Número da edição do DOU |
| `secao_dou` | 16.413 | string/null | Seção do DOU onde foi publicada |
| `pagina_dou` | 16.413 | string/null | Página do DOU |
| `data_dou` | 16.413 | date/null | Data de publicação no DOU |
| `source_csv` | 16.413 | string | Arquivo CSV de origem |
| `source_type` | 16.413 | string | Sempre `"tcu_normas"` |
| `authority_level` | 16.413 | string | Nível de autoridade normativa |
| `deterministic_hash` | 16.413 | string | Hash determinístico do conteúdo |
| `search_all` | 16.413 | string | Campo concatenado para busca |
| `embedding_status` | 16.413 | string | Status do embedding |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_normas_raw_data_pkey` | UNIQUE BTREE | `id` |

---

## Problemas / Notas

- ℹ️ Sem índice em `all_fields->>'vigente'` — considerar índice GIN ou coluna extraída para filtrar vigentes
- ℹ️ Relacionamento implícito com DOU via `num_dou` + `secao_dou` + `data_dou`
- 🥇 **Excelente candidata para RAG** — textos curtos e precisos, ótimos para recuperação contextual
- ℹ️ Campo `authority_level` pode ser usado para priorização em resultados de busca

---

## Classificação de Sensibilidade

**Público** — normas TCU são documentos oficiais de acesso público.
