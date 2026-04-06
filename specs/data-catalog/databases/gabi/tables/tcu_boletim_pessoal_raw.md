# Tabela: `raw.tcu_boletim_pessoal_raw`

**Criticidade:** 🟢 ATIVA  
**Linhas (live):** 1.500  
**Tamanho total:** 1,4 MB  
**Origem:** TCU Dados Abertos — CSV `boletim-pessoal` via `tcu_csv_raw_pg.py`  
**Última ingestão:** 2026-04-05

---

## Descrição

Tabela colunar do **Boletim de Pessoal do TCU** — publicação periódica com enunciados sobre pessoal (admissão, aposentadoria, pensão), com referência aos acórdãos de origem.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `id` | `text` | ✅ | ID gerado pelo pipeline |
| 2 | `source_type` | `text` | — | Sempre `"tcu_boletim_pessoal"` |
| 3 | `dumped_at` | `timestamptz` | — | Timestamp da inserção |
| 4 | `KEY` | `text` | — | Chave natural do CSV |
| 5 | `TITULO` | `text` | — | Título do enunciado |
| 6 | `ENUNCIADO` | `text` | — | Texto do enunciado |
| 7 | `NUMERO` | `text` | — | Número do boletim |
| 8 | `REFERENCIA` | `text` | — | Referência ao acórdão de origem |
| 9 | `TEXTOACORDAO` | `text` | — | Trecho do acórdão citado |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_boletim_pessoal_raw_pkey` | UNIQUE BTREE | `id` |
| `ix_raw_tcu_boletim_pessoal_raw_dumped_at` | BTREE | `dumped_at DESC` |

---

## Notas

- ℹ️ Conteúdo focado em matéria de pessoal — relacionamento temático com acórdãos de APOSENTADORIA, PENSÃO, ADMISSÃO

---

## Classificação de Sensibilidade

**Público** — boletins TCU são de acesso irrestrito.  
Atenção: pode conter nomes de servidores → **Interno** para fins de LGPD se necessário.
