# Tabela: `raw.tcu_csv_fetch_meta`

**Criticidade:** ⚪ META — Controle de ingestão CSV  
**Linhas (live):** 42  
**Tamanho total:** 64 kB  
**Origem:** Gerada pelo pipeline `tcu_csv_raw_pg.py`

---

## Descrição

Tabela de controle de fetch dos CSVs do TCU. Registra cada arquivo CSV baixado com seu hash de conteúdo (SHA-256), tamanho e ETag HTTP. Permite detectar mudanças nos CSVs fonte e evitar re-ingestão desnecessária.

---

## Colunas

| # | Coluna | Tipo | PK | Descrição |
|---|--------|------|----|-----------|
| 1 | `url` | `text` | ✅ | URL do CSV fonte — chave primária |
| 2 | `content_sha256` | `text` | — | Hash SHA-256 do conteúdo baixado |
| 3 | `bytes_size` | `bigint` | — | Tamanho em bytes do arquivo |
| 4 | `fetched_at` | `timestamptz` | — | Timestamp do último fetch |
| 5 | `response_etag` | `text` | — | ETag HTTP da resposta (pode ser null) |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_csv_fetch_meta_pkey` | UNIQUE BTREE | `url` |

---

## Notas

- ℹ️ 42 linhas = uma entrada por URL de CSV monitorada (múltiplas fontes × múltiplos anos)
- ℹ️ `content_sha256` é a base para detecção de mudança — se o hash mudar, re-ingestão é acionada
- ℹ️ `response_etag` pode ser null dependendo do servidor TCU

---

## Classificação de Sensibilidade

**Interno** — metadados operacionais do sistema.
