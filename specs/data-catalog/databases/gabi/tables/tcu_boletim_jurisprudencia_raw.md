# Tabela: `raw.tcu_boletim_jurisprudencia_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 5.837  
**Tamanho total:** 5 MB  
**Origem:** TCU Dados Abertos — CSV `boletim-jurisprudencia` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar do **Boletim de Jurisprudência do TCU** — publicação periódica que consolida enunciados jurisprudenciais com excertos dos acórdãos de origem e referências cruzadas.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_boletim_jurisprudencia"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `TITULO` | `text` | — | Título do enunciado |
| 6 | `ENUNCIADO` | `text` | — | Texto do enunciado jurisprudencial |
| 7 | `REFERENCIA` | `text` | — | Referência ao acórdão de origem |
| 8 | `TEXTOACORDAO` | `text` | — | Trecho do acórdão citado |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_boletim_jurisprudencia_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_boletim_jurisprudencia_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- ℹ️ Relacionamento implícito com `tcu_acordao_completo_raw` via `REFERENCIA`
- ℹ️ Conteúdo sobrepõe parcialmente com `tcu_jurisprudencia_selecionada_raw` — são publicações distintas do TCU

---

## Classificação de Sensibilidade

**Público** — boletins TCU são de acesso irrestrito.
