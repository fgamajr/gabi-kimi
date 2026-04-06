# Tabela: `raw.tcu_jurisprudencia_selecionada_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 17.549  
**Tamanho total:** 75 MB  
**Origem:** TCU Dados Abertos — CSV `jurisprudencia-selecionada` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar de **jurisprudência selecionada do TCU** — excertos temáticos extraídos de acórdãos e organizados por área, tema e subtema. Cada linha representa um enunciado jurisprudencial com o excerto relevante do acórdão de origem. Referencia acórdãos em `tcu_acordao_completo_raw` via `NUMACORDAO` + `ANOACORDAO`.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_jurisprudencia_selecionada"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `NUMACORDAO` | `text` | — | Número do acórdão de origem |
| 6 | `ANOACORDAO` | `text` | — | Ano do acórdão de origem |
| 7 | `COLEGIADO` | `text` | — | Órgão colegiado |
| 8 | `AREA` | `text` | — | Área temática |
| 9 | `TEMA` | `text` | — | Tema |
| 10 | `SUBTEMA` | `text` | — | Subtema |
| 11 | `ENUNCIADO` | `text` | — | Enunciado jurisprudencial |
| 12 | `EXCERTO` | `text` | — | Trecho do acórdão que embasa o enunciado |
| 13 | `NUMSUMULA` | `text` | — | Número da súmula relacionada (se houver) |
| 14 | `DATASESSAOFORMATADA` | `text` | — | Data da sessão formatada |
| 15 | `AUTORTESE` | `text` | — | Autor da tese |
| 16 | `FUNCAOAUTORTESE` | `text` | — | Função do autor da tese |
| 17 | `TIPOPROCESSO` | `text` | — | Tipo de processo |
| 18 | `TIPORECURSO` | `text` | — | Tipo de recurso |
| 19 | `INDEXACAO` | `text` | — | Termos de indexação |
| 20 | `INDEXADORESCONSOLIDADOS` | `text` | — | Indexadores consolidados |
| 21 | `PARAGRAFOLC` | `text` | — | Parágrafo da Lei de Compliance relacionado |
| 22 | `REFERENCIALEGAL` | `text` | — | Referência legal base |
| 23 | `PUBLICACAOAPRESENTACAO` | `text` | — | Publicação de apresentação |
| 24 | `PARADIGMATICO` | `text` | — | Indica se é paradigmático |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_jurisprudencia_selecionada_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_jurisprudencia_selecionada_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- 🥇 **Excelente candidata para RAG** — enunciados curtos e precisos, com excerto contextual
- ℹ️ Relacionamento implícito com `tcu_acordao_completo_raw` via `NUMACORDAO` + `ANOACORDAO`
- ℹ️ `AREA`, `TEMA`, `SUBTEMA` permitem filtragem temática refinada

---

## Classificação de Sensibilidade

**Público** — jurisprudência TCU é de acesso irrestrito.
