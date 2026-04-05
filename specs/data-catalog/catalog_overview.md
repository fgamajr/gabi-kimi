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

| Tabela | Schema | Linhas (exato) | Tamanho | Fonte | Criticidade |
|--------|--------|--------------|---------|-------|-------------|
| [`dou_documents`](databases/gabi/tables/dou_documents.md) | raw | **15.853.837** | 89 GB | DOU/INLABS | 🔴 CRÍTICA |
| [`tcu_acordaos`](databases/gabi/tables/tcu_acordaos.md) | raw | **547.490** | 11 GB | TCU Dados Abertos (CSVs) | 🔴 CRÍTICA |
| [`tcu_acordaos_raw_data`](databases/gabi/tables/tcu_acordaos_raw_data.md) | raw | **547.490** | 6,1 GB | TCU Dados Abertos (CSVs) — JSONB | 🟡 LEGADO |
| [`tcu_btcu_raw_data`](databases/gabi/tables/tcu_btcu_raw_data.md) | raw | **223.515** | 822 MB | BTCU API | 🟢 ATIVA |
| [`tcu_normas_raw_data`](databases/gabi/tables/tcu_normas_raw_data.md) | raw | **16.413** | 90 MB | TCU Normas CSV | 🟢 ATIVA |
| [`tcu_publicacoes_raw_data`](databases/gabi/tables/tcu_publicacoes_raw_data.md) | raw | **667** | 39 MB | Portal TCU (scraping) | 🟢 ATIVA |
| [`migration_log`](databases/gabi/tables/migration_log.md) | raw | 10 | 32 kB | Interna — auditoria de ingestão | ⚪ META |

**Total de documentos únicos:** ~16.641.822  
**Tamanho total do banco:** 107 GB

> **Nota sobre contagem:** O valor de `dou_documents` (15.853.837) é a contagem exata validada pelo migration_log. O estimador do PostgreSQL (`reltuples`) retorna 15.649.937 por falta de `ANALYZE` — não representa perda de dados.

---

## ⚠️ Sprint 2 — Tabelas Source-Separated (Planejadas)

O Sprint 2 prevê a substituição de `raw.tcu_acordaos` e `raw.tcu_acordaos_raw_data` por **tabelas colunar separadas por fonte**, cada uma com as colunas exatas dos CSVs TCU (sem JSONB). Estas tabelas **ainda não existem no banco em produção** (verificado em 2026-04-05).

| Tabela planejada | Linhas esperadas | Fonte CSV |
|-----------------|-----------------|-----------|
| `raw.tcu_acordao_completo_raw` | 520.353 | acordao-completo-{year}.csv |
| `raw.tcu_jurisprudencia_selecionada_raw` | 17.016 | jurisprudencia.csv |
| `raw.tcu_resposta_consulta_raw` | 522 | resposta-consulta.csv |
| `raw.tcu_sumula_raw` | 294 | sumula.csv |
| `raw.tcu_boletim_jurisprudencia_raw` | 5.828 | boletim-jurisprudencia.csv |
| `raw.tcu_boletim_pessoal_raw` | 1.500 | boletim-pessoal.csv |
| `raw.tcu_boletim_informativo_lc_raw` | 1.977 | boletim-lc.csv |
| `raw.tcu_normas_raw` | 16.413 | norma.csv |

Também será criada `raw.tcu_csv_fetch_meta` (tabela de metadados de fetch por fonte/ano).

**Quando o Sprint 2 for executado, este catálogo deve ser atualizado** para refletir o novo schema columnar.

---

## Arquitetura de Dados

```
Fontes externas                                    PostgreSQL raw.*
├── DOU/INLABS (HTML/ZIP) ─────────────────────→ raw.dou_documents (15.9M)
├── TCU Dados Abertos (CSV) ───────────────────→ raw.tcu_acordaos (547K)  ← tipada
│   ├── acordao-completo-{year}.csv                  (source_type: tcu_acordao)
│   ├── jurisprudencia.csv                           (source_type: tcu_jurisprudencia)
│   ├── sumula.csv                                   (source_type: tcu_sumula)
│   ├── resposta-consulta.csv                        (source_type: tcu_resposta_consulta)
│   └── boletim-*.csv                                (source_type: tcu_boletim_*)
│                                              → raw.tcu_acordaos_raw_data (547K) ← JSONB/legado
├── BTCU API ──────────────────────────────────→ raw.tcu_btcu_raw_data (223K)
├── TCU Normas CSV ────────────────────────────→ raw.tcu_normas_raw_data (16K)
└── Portal TCU (scraping) ─────────────────────→ raw.tcu_publicacoes_raw_data (667)
```

---

## Relacionamentos Lógicos

Não existem **foreign keys físicas** no banco atual. Os relacionamentos são **implícitos via `id`**:

```
raw.tcu_acordaos.id  ←→  raw.tcu_acordaos_raw_data.id
  (547.490 registros — sobreposição 100%)
  
tcu_acordaos        = tabela tipada (colunas explícitas + all_fields JSONB)
tcu_acordaos_raw_data = tabela JSONB puro (all_fields apenas)
Candidata a DROP após Sprint 2 — ver tabela de problemas.
```

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
