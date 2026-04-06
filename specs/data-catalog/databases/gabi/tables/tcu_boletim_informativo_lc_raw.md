# Tabela: `raw.tcu_boletim_informativo_lc_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 1.977  
**Tamanho total:** 6 MB  
**Origem:** TCU Dados Abertos — CSV `boletim-informativo-lc` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar do **Boletim Informativo de Licitações e Contratos (LC) do TCU** — publicação periódica com enunciados e textos informativos sobre licitações e contratos, organizada por colegiado.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_boletim_informativo_lc"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `TITULO` | `text` | — | Título do item |
| 6 | `COLEGIADO` | `text` | — | Órgão colegiado |
| 7 | `TEXTOACORDAO` | `text` | — | Trecho do acórdão citado |
| 8 | `ENUNCIADO` | `text` | — | Enunciado do item |
| 9 | `NUMERO` | `text` | — | Número do boletim |
| 10 | `TEXTOINFO` | `text` | — | Texto informativo complementar |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_boletim_informativo_lc_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_boletim_informativo_lc_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Classificação de Sensibilidade

**Público** — boletins TCU são de acesso irrestrito.
