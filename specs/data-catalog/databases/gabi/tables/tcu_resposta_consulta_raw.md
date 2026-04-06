# Tabela: `raw.tcu_resposta_consulta_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 523  
**Tamanho total:** 4 MB  
**Origem:** TCU Dados Abertos — CSV `resposta-consulta` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar de **respostas a consultas do TCU** — deliberações em que o TCU responde a consultas de autoridades sobre matérias de sua competência. Estrutura similar à jurisprudência selecionada, com enunciado, excerto e referências.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_resposta_consulta"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `NUMACORDAO` | `text` | — | Número do acórdão |
| 6 | `ANOACORDAO` | `text` | — | Ano do acórdão |
| 7 | `COLEGIADO` | `text` | — | Órgão colegiado |
| 8 | `NUMACORDAOFORMATADO` | `text` | — | Número do acórdão formatado (ex: Acórdão 123/2024-Plenário) |
| 9 | `AREA` | `text` | — | Área temática |
| 10 | `TEMA` | `text` | — | Tema |
| 11 | `SUBTEMA` | `text` | — | Subtema |
| 12 | `ENUNCIADO` | `text` | — | Enunciado da resposta |
| 13 | `EXCERTO` | `text` | — | Trecho do acórdão |
| 14 | `DATASESSAOFORMATADA` | `text` | — | Data da sessão |
| 15 | `AUTORTESE` | `text` | — | Autor da tese |
| 16 | `FUNCAOAUTORTESE` | `text` | — | Função do autor da tese |
| 17 | `TIPOPROCESSO` | `text` | — | Tipo de processo (CONSULTA) |
| 18 | `TIPORECURSO` | `text` | — | Tipo de recurso |
| 19 | `INDEXACAO` | `text` | — | Termos de indexação |
| 20 | `INDEXADORESCONSOLIDADOS` | `text` | — | Indexadores consolidados |
| 21 | `PARAGRAFOLC` | `text` | — | Parágrafo da Lei de Compliance |
| 22 | `REFERENCIALEGAL` | `text` | — | Referência legal |
| 23 | `PUBLICACAOAPRESENTACAO` | `text` | — | Publicação de apresentação |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_resposta_consulta_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_resposta_consulta_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- 🥇 **Alta relevância para RAG** — respostas a consultas têm alta precisão jurídica
- ℹ️ Relacionamento implícito com `tcu_acordao_completo_raw` via `NUMACORDAO` + `ANOACORDAO`

---

## Classificação de Sensibilidade

**Público** — respostas a consultas TCU são de acesso irrestrito.
