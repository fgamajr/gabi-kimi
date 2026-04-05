# Tabela: `raw.tcu_acordaos_raw_data`

**Criticidade:** 🟡 LEGADO — Schema JSONB puro; coberto por `tcu_acordaos` (tipada)  
**Linhas:** 547.490  
**Tamanho total:** 6,1 GB  
**Origem:** TCU Dados Abertos (CSVs) — ingestão via `tcu_csv_postgres_ingest.py`  
**Última ingestão:** 2026-04-05 (raw_dump — 547.490/547.490 ok)

---

## Descrição

Tabela JSONB puro contendo todos os documentos TCU (acórdãos, jurisprudência, súmulas, boletins e respostas a consulta) consolidados no campo `all_fields`. **Contém os mesmos 547.490 IDs que `raw.tcu_acordaos`** — 100% de sobreposição verificada. A diferença é de schema: `tcu_acordaos` expõe colunas tipadas extraídas; esta tabela armazena apenas o JSONB completo.

> **Candidata a DROP após Sprint 2 concluído.** Esta tabela contém source_types que ainda não possuem tabelas source-separated em produção (`tcu_jurisprudencia`, `tcu_sumula`, `tcu_boletim_*`, `tcu_resposta_consulta`). Dropar antes destruiria o safety net. Após Sprint 2 validado: economia de ~6 GB.

---

## Colunas

| # | Coluna | Tipo | Nullable | PK | Default | Descrição |
|---|--------|------|----------|-----|---------|-----------|
| 1 | `id` | `text` | NO | ✅ | — | ID do documento (ex: `ACORDAO-COMPLETO-2683294`) |
| 2 | `all_fields` | `jsonb` | NO | — | — | Documento completo serializado como JSONB |
| 3 | `dumped_at` | `timestamptz` | NO | — | `now()` | Timestamp da inserção no PostgreSQL |

---

## Campo `all_fields` (JSONB) — Chaves Identificadas

| Chave | Presença | Tipo inferido | Descrição |
|-------|---------|--------------|-----------|
| `_id` | 547.490 | string | ID do documento |
| `tipo` | 547.490 | string | Tipo do ato |
| `titulo` | 547.490 | string | Título |
| `data_sessao` | 547.490 | string | Data da sessão |
| `colegiado` | 547.490 | string | Órgão colegiado |
| `sumario` | 547.490 | string | Ementa/sumário |
| `source_type` | 547.490 | string | Fonte CSV de origem |
| `search_all` | 547.490 | string | Campo concatenado para busca full-text |
| `embedding_status` | 547.490 | string | Status do embedding vetorial |
| `tipo_processo` | 538.185 | string | Tipo de processo |
| `ano_acordao` | 537.891 | int | Ano do acórdão |
| `numero_acordao` | 537.891 | int | Número do acórdão |
| `relator` | 537.891 | string | Ministro relator |
| `source_url` | 520.647 | string | URL da fonte |
| `has_relatorio` | 520.353 | bool | Indica presença de seção Relatório |
| `voto` | 520.353 | string/null | Texto do voto do relator |
| `acordaos_relacionados` | 520.353 | array | IDs de acórdãos relacionados |
| `orgaos_citados` | 520.353 | array | Órgãos citados no documento |
| `completeness_score` | 520.353 | float | Score de completude (0-1) |
| `tema_primario` | 520.353 | string | Tema primário classificado |
| `tem_debito` | 520.353 | bool | Indica imputação de débito |

---

## Índices

| Índice | Tipo | Coluna |
|--------|------|--------|
| `tcu_acordaos_raw_data_pkey` | UNIQUE BTREE | `id` |

---

## Relacionamentos

| Coluna | Referencia | Tipo |
|--------|-----------|------|
| `id` | `raw.tcu_acordaos.id` | Implícito (100% sobreposição) |

---

## Pré-condições para DROP

```sql
-- 1. Confirmar sobreposição total de IDs
SELECT COUNT(*) FROM raw.tcu_acordaos_raw_data r
WHERE NOT EXISTS (SELECT 1 FROM raw.tcu_acordaos a WHERE a.id = r.id);
-- Resultado atual: 0

-- 2. Sprint 2 concluído — tabelas source-separated existem e estão populadas
SELECT tablename FROM pg_tables
WHERE schemaname='raw' AND tablename LIKE 'tcu_%_raw';

-- 3. Cada source_type coberto pelas novas tabelas
SELECT source_type, COUNT(*) FROM raw.tcu_acordaos GROUP BY source_type;

-- Somente após as 3 condições satisfeitas:
-- DROP TABLE raw.tcu_acordaos_raw_data;  -- economia: ~6 GB
```

---

## Classificação de Sensibilidade

**Público** — mesmos dados que `tcu_acordaos`.
