# Tabela: `raw.tcu_sumula_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 294  
**Tamanho total:** 720 kB  
**Origem:** TCU Dados Abertos — CSV `sumula` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar de **súmulas do TCU** — enunciados normativos aprovados pelo Plenário que consolidam o entendimento jurisprudencial do Tribunal sobre matérias recorrentes. Corpus pequeno e altamente autoritativo.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_sumula"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `NUMERO` | `text` | — | Número da súmula |
| 6 | `ENUNCIADO` | `text` | — | Texto do enunciado da súmula |
| 7 | `TIPOPROCESSO` | `text` | — | Tipo de processo de origem |
| 8 | `AREA` | `text` | — | Área temática |
| 9 | `TEMA` | `text` | — | Tema |
| 10 | `SUBTEMA` | `text` | — | Subtema |
| 11 | `APROVACAO` | `text` | — | Acórdão de aprovação |
| 12 | `NUMAPROVACAO` | `text` | — | Número do acórdão de aprovação |
| 13 | `ANOAPROVACAO` | `text` | — | Ano do acórdão de aprovação |
| 14 | `COLEGIADO` | `text` | — | Sempre Plenário |
| 15 | `FUNCAOAUTORTESE` | `text` | — | Função do autor da tese |
| 16 | `AUTORTESE` | `text` | — | Autor da tese |
| 17 | `INDEXACAO` | `text` | — | Termos de indexação |
| 18 | `VIGENTE` | `text` | — | `S` se vigente, `N` se cancelada |
| 19 | `DATASESSAOFORMATADA` | `text` | — | Data da sessão de aprovação |
| 20 | `EXCERTO` | `text` | — | Excerto do acórdão base |
| 21 | `REFERENCIALEGAL` | `text` | — | Referências legais |
| 22 | `INDEXADORESCONSOLIDADOS` | `text` | — | Indexadores consolidados |
| 23 | `PUBLICACAO` | `text` | — | Publicação no DOU |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_sumula_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_sumula_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- 🥇 **Máxima prioridade para RAG** — súmulas são o nível mais autoritativo de jurisprudência TCU
- ℹ️ `VIGENTE = 'S'` filtra as súmulas em vigor
- ℹ️ Relacionamento com `tcu_acordao_completo_raw` via `NUMAPROVACAO` + `ANOAPROVACAO`

---

## Classificação de Sensibilidade

**Público** — súmulas TCU são de acesso irrestrito.
