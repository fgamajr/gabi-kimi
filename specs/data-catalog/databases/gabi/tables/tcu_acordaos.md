# Tabela: `raw.tcu_acordaos`

**Criticidade:** 🔴 CRÍTICA — Tabela tipada de acórdãos TCU, principal fonte de jurisprudência  
**Linhas estimadas:** 547.490  
**Tamanho total:** 11 GB  
**Cobertura temporal:** 1973-12-04 → 2026-03-18  
**Origem:** TCU Dados Abertos (múltiplos CSVs) → ingestão direta  
**Última ingestão:** 2026-04-05 (typed_materialization — 547.490/547.490 ok)

---

## Descrição

Tabela tipada central de **acórdãos e jurisprudência do Tribunal de Contas da União (TCU)**. Consolidada a partir de 7 fontes CSV distintas disponibilizadas no portal de dados abertos do TCU. Cada linha representa uma decisão, súmula, jurisprudência selecionada ou resposta a consulta emitida pelo TCU. A coluna `source_type` discrimina a fonte CSV de cada registro. O campo `all_fields` preserva o documento completo enriquecido pelo pipeline de ingestão.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | ID canônico do documento (ex: `ACORDAO-COMPLETO-1319104`) |
| 2 | `tipo` | `text` | YES | — | — | Tipo do ato: ACÓRDÃO, ACÓRDÃO DE RELAÇÃO, DECISÃO, etc. |
| 3 | `has_relatorio` | `boolean` | YES | — | — | Indica se o documento possui seção Relatório |
| 4 | `has_voto` | `boolean` | YES | — | — | Indica se o documento possui seção Voto |
| 5 | `data_sessao` | `date` | YES | — | — | Data da sessão de julgamento |
| 6 | `colegiado` | `text` | YES | — | — | Órgão colegiado: Plenário, Primeira Câmara, Segunda Câmara |
| 7 | `raw_text_hash` | `text` | NO | — | — | Hash do texto para deduplicação |
| 8 | `all_fields` | `jsonb` | NO | — | — | Documento MongoDB completo (todos os campos enriquecidos) |
| 9 | `migrated_at` | `timestamptz` | NO | — | `now()` | Timestamp da inserção no PostgreSQL |
| 10 | `source_type` | `text` | YES | — | — | Fonte CSV de origem (ver distribuição abaixo) |
| 11 | `relator` | `text` | YES | — | — | Nome do Ministro relator |
| 12 | `situacao` | `text` | YES | — | — | Situação processual |
| 13 | `tipoprocesso` | `text` | YES | — | — | Tipo de processo TCU |
| 14 | `area` | `text` | YES | — | — | Área temática (alta taxa de NULL) |
| 15 | `tema` | `text` | YES | — | — | Tema (alta taxa de NULL) |
| 16 | `subtema` | `text` | YES | — | — | Subtema (alta taxa de NULL) |
| 17 | `numero_referencia` | `text` | YES | — | — | Número de referência do processo |
| 18 | `vigente` | `boolean` | YES | — | — | Se a jurisprudência está vigente |
| 19 | `autortese` | `text` | YES | — | — | Autor da tese (campo de jurisprudência selecionada) |

---

## Campo `all_fields` (JSONB) — Chaves Principais

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | 547.490 | string | ID do documento |
| `tipo` | 547.490 | string | Tipo do ato |
| `titulo` | 547.490 | string | Título completo do acórdão |
| `data_sessao` | 547.490 | string | Data da sessão |
| `colegiado` | 547.490 | string | Órgão colegiado |
| `source_type` | 547.490 | string | Fonte CSV |
| `sumario` | 547.490 | string | Sumário/ementa do acórdão |
| `search_all` | 547.490 | string | Campo concatenado para busca |
| `embedding_status` | 547.490 | string | Status de embedding vetorial |
| `tipo_processo` | 538.185 | string | Tipo de processo |
| `ano_acordao` | 537.891 | int | Ano do acórdão |
| `numero_acordao` | 537.891 | int | Número do acórdão |
| `relator` | 537.891 | string | Ministro relator |
| `source_url` | 520.647 | string | URL da fonte |
| `has_relatorio` | 520.353 | bool | Tem seção Relatório |
| `voto` | 520.353 | string/null | Texto do voto do relator |
| `acordaos_relacionados` | 520.353 | array | IDs de acórdãos relacionados |
| `orgaos_citados` | 520.353 | array | Órgãos citados no acórdão |
| `completeness_score` | 520.353 | float | Score de completude (0-1) |
| `tema_primario` | 520.353 | string | Tema primário classificado |
| `tem_debito` | 520.353 | bool | Indica imputação de débito |

---

## Distribuição por `source_type`

| source_type | Registros | Descrição |
|------------|----------|-----------|
| `tcu_acordao` | 520.353 | Acórdãos completos (CSV principal) |
| `tcu_jurisprudencia` | 17.016 | Jurisprudência Selecionada |
| `tcu_boletim_jurisprudencia` | 5.828 | Boletim de Jurisprudência |
| `tcu_boletim_lc` | 1.977 | Boletim de Licitação e Contratos |
| `tcu_boletim_pessoal` | 1.500 | Boletim de Pessoal |
| `tcu_resposta_consulta` | 522 | Respostas a Consulta |
| `tcu_sumula` | 294 | Súmulas TCU |

---

## Distribuição por `tipo`

| tipo | Registros |
|------|----------|
| ACÓRDÃO DE RELAÇÃO | 357.718 |
| ACÓRDÃO | 143.133 |
| DECISÃO | 19.502 |
| JURISPRUDÊNCIA SELECIONADA | 17.016 |
| BOLETIM | 9.305 |
| RESPOSTA A CONSULTA | 522 |
| SÚMULA | 294 |

---

## Distribuição por `colegiado`

| Colegiado | Registros |
|-----------|----------|
| Primeira Câmara | 224.285 |
| Segunda Câmara | 220.297 |
| Plenário | 95.580 |
| (sem colegiado) | 7.328 |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_acordaos_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_acordaos_tipo` | BTREE | `tipo` |
| `ix_raw_tcu_acordaos_data_sessao` | BTREE | `data_sessao` |
| `ix_raw_tcu_acordaos_area` | BTREE | `area` |
| `ix_raw_tcu_acordaos_source_type` | BTREE | `source_type` |

---

## Problemas / Notas

- ⚠️ `area`, `tema`, `subtema`, `autortese` — alta taxa de NULL (preenchidos apenas em `tcu_jurisprudencia`)
- ⚠️ `situacao`, `tipoprocesso` — verificar cobertura real vs fontes CSV
- ℹ️ Relacionamento implícito 1:1 com `tcu_acordaos_raw_data` — IDs idênticos, 100% sobreposição
- 🥇 **Top candidata para RAG** — campos `all_fields->>'sumario'` e `all_fields->>'voto'` (`has_relatorio` é boolean — o texto do relatório não está exposto como campo separado nesta tabela)
- ℹ️ Falta índice em `colegiado` e `relator` (filtros frequentes nas buscas)

---

## Classificação de Sensibilidade

**Público** — acórdãos TCU são documentos de acesso público.  
Atenção: nomes de relatores e partes processuais estão presentes → **Interno** para fins de LGPD se necessário.
