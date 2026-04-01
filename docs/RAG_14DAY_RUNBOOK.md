# Runbook — RAG (14 dias)

Checklist operacional para ativar reranker + vector search com risco controlado, coletar feedback e decidir reindexação.  
Configuração de flags: [`src/backend/core/config.py`](../src/backend/core/config.py) e [`.env.example`](../.env.example).

Pré-checagens automatizáveis:

```bash
cd /path/to/gabi-kimi
python3 ops/rag_rollout_checks.py
# ou com ES remoto:
ES_URL=https://seu-es:9200 python3 ops/rag_rollout_checks.py
```

O mesmo script faz um *probe* de leitura em `TCU_PUBLICACOES_INDEX` (publicações TCU) — útil antes de depender da busca federada no MCP.

**Respostas RAG (`POST /api/answer`):** o backend só gera texto quando `RAG_ENABLED=true` e há chave Anthropic configurada. Em produção, defina no `.env` do servidor `RAG_ENABLED=true` e `ANTHROPIC_API_KEY=...`; o [`docker-compose.prod.yml`](../docker-compose.prod.yml) repassa `RAG_ENABLED` e `ANTHROPIC_API_KEY` ao serviço `backend`. Depois: `docker compose -f docker-compose.prod.yml restart backend`. Smoke (porta publicada do backend, ex. 8001):

```bash
curl -sS -X POST "http://localhost:8001/api/answer" \
  -H "Content-Type: application/json" \
  -d '{"query":"o que é dispensa de licitação"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('fallback=',d.get('fallback'), 'reason=',d.get('fallback_reason'), 'answer_len=',len(d.get('answer')or''))"
```

**Diagnóstico TCU (`_id` vs campo `doc_id`):** somente leitura — [`ops/diagnose_tcu_doc_id.py`](../ops/diagnose_tcu_doc_id.py). Ex.: `ES_URL=http://elasticsearch:9200 python3 ops/diagnose_tcu_doc_id.py JURISPRUDENCIA-SELECIONADA-12345`.

---

## Fase 1 (dias 1–2) — Reranker

**Objetivo:** `RERANKER_ENABLED=true` com estabilidade de latência e erros.

1. Confirmar serviço do reranker acessível a partir do backend (rede Docker / `host.docker.internal` conforme `.env`).
2. Definir baseline **antes** (amostra de 20–50 queries representativas): tempo p50/p95 do endpoint de busca, taxa de erro HTTP, ordem dos top-5.
3. Aplicar em produção:
   - `RERANKER_ENABLED=true`
   - Subir stack com perfil reranker se aplicável (`docker compose ... --profile reranker up -d`).
4. Repetir medições. **Gate:** p95 não regressa além do orçamento acordado (ex.: +200 ms) e sem picos de 5xx.
5. Rollback: `RERANKER_ENABLED=false` e restart do backend.

**Observação:** O cliente chama `POST {RERANKER_URL}/v1/rerank` — ver [`src/backend/search/reranker.py`](../src/backend/search/reranker.py).

---

## Fase 2 (dias 3–5) — Vector search (DOU / índice principal)

**Objetivo:** `VECTOR_SEARCH_ENABLED=true` com embeddings presentes no índice alvo.

1. Rodar `python3 ops/rag_rollout_checks.py` e confirmar contagem `embedding` > 0 no índice principal (alias ou `ES_INDEX`).
2. Confirmar que o servidor de embedding (`EMBED_SERVER_URL`) devolve vetores com **mesma dimensão** que o mapping ES do índice (DOU: 384 em [`es_index_v3_full.json`](../src/backend/search/es_index_v3_full.json)).
3. Ativar `VECTOR_SEARCH_ENABLED=true` e reiniciar backend.
4. Medir recall percebido em consultas semânticas (sem keywords exatas) vs baseline Fase 1.
5. **Gate:** ganho claro em semântica sem degradar latência além do aceite; caso contrário, rollback da flag.

**Observação:** [`hybrid.py`](../src/backend/search/hybrid.py) faz fallback para BM25 se o embedding da query falhar.

---

## Fase 3 (dias 6–10) — Feedback e `agent-learn-scoring`

**Objetivo:** dados reais para validar perfis de scoring e qualidade por `query_type`.

1. Garantir traces/ledger acessíveis (`RETRIEVAL_AUDIT_LOG_PATH` → pasta `answers`).
2. Registrar feedback de qualidade:
   - Respostas: `python -m src.backend.cli feedback-answer "..."` (grava `scoring_feedback.jsonl` com `success`/falha).
   - Ou fluxo por `query_id` via `python -m src.backend.answering.feedback` quando aplicável.
3. Periodicamente (ex.: semanal):

   ```bash
   PYTHONPATH=src python -m src.backend.cli agent-learn-scoring
   ```

4. Revisar `scoring_stats.json` (taxa por `query_type`) e ajustar operação (prompts, limites de evidência) antes de mexer em modelo de embedding.

**Gate para Fase 4:** volume mínimo de feedbacks (ex.: dezenas por tipo crítico) e tendência estável por alguns dias.

---

## Fase 4 (dias 11–14) — Decisão de reindex (go / no-go)

**Só reindexar em larga escala se:**

| Critério | Descrição |
|----------|-----------|
| Problema comprovado | Recall / nDCG@10 (ou métrica acordada) abaixo do alvo com reranker + vector ativos |
| Ganho projetado | Benchmark offline ≥ ~10% de melhoria com modelo/dimensão alternativos |
| Operação | Plano de índice paralelo + swap de alias sem downtime |

Se algum critério falhar: manter modelo atual; iterar em query rewrite, rerank, filtros e scoring.

---

## Referência cruzada — TCU e dimensões

Ver [TCU_EMBEDDING_DIMENSION_STRATEGY.md](./TCU_EMBEDDING_DIMENSION_STRATEGY.md) antes de assumir um único vetor para todos os índices.
