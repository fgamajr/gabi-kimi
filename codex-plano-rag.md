# CODEX Plano RAG Profissional (BM25 + Vetor + Reranking + Contextual Embeddings)

## 1. Objetivo

Evoluir a busca atual (BM25/Elasticsearch + MCP + web) para um pipeline RAG profissional com:

- busca híbrida lexical + semântica
- reranking de alta precisão
- chunks com embeddings contextuais
- respostas com citações verificáveis
- observabilidade e métricas de qualidade

Resultado esperado: maior recall para consultas em linguagem natural, melhor precisão no top-10 e respostas mais confiáveis para perguntas jurídicas/administrativas no acervo DOU.

---

## 2. Estado Atual (baseline)

Já implementado no projeto:

- ingestão DOU para PostgreSQL (`dou.*`)
- indexação Elasticsearch de documentos
- busca, suggest, facets via MCP e web API
- sinais Redis (top searches, cache suggest)

Limitação atual:

- ranking majoritariamente lexical (BM25)
- pouca recuperação semântica para perguntas indiretas
- ausência de reranking cross-encoder
- ausência de chunking contextual para grounding robusto

---

## 3. Arquitetura Alvo

## 3.1 Camadas

1. Ingestão/Parsing (já existe)
2. Chunking + Enriquecimento Contextual (novo)
3. Embedding + Indexação Vetorial (novo)
4. Retrieval Híbrido (BM25 + kNN + fusão)
5. Reranking (novo)
6. Context Builder para RAG (novo)
7. Geração com citações (MCP/web)

## 3.2 Estratégia de índices

- Manter índice atual de documentos (`gabi_documents_v1`) para BM25/facets.
- Criar índice novo de chunks vetoriais, ex:
  - `gabi_chunks_v1`
- Campo vetorial:
  - `embedding: dense_vector` (dimensão definida pelo modelo)
- Metadados indexados no chunk:
  - `doc_id`, `id_materia`, `publication_date`, `section`, `issuing_organ`, `art_type`, `page_number`, `chunk_idx`, `chunk_text`, `chunk_text_norm`, `source_score_signals`

---

## 4. Plano de Implementação (fases)

## Fase 0 — Preparação e decisões técnicas

### 0.1 Definir provedores/modelos

- Embeddings (PT-BR robusto):
  - opção cloud (OpenAI/Cohere/Jina/etc.) ou local (BGE multilingual, e5-multilingual)
- Reranker:
  - cross-encoder multilíngue/jurídico

Critérios:

- qualidade em português
- custo por 1k chunks / por query
- latência p95
- facilidade operacional

### 0.2 Definir políticas de chunking

- chunk_size alvo: 700-1200 caracteres
- overlap: 120-200 caracteres
- regras por estrutura (títulos, subtítulos, assinaturas, referências)
- hard limits para evitar chunk gigante

### 0.3 Congelar dataset de avaliação

- criar conjunto ouro com ~200 queries reais
- rótulos de relevância em nível de chunk/doc (manual + heurística)

Entregáveis Fase 0:

- matriz de decisão (modelo embedding/reranker)
- config padrão em `.env.example`
- dataset inicial de avaliação

---

## Fase 1 — Chunking Contextual + Persistência

### 1.1 Nova tabela de chunks no PostgreSQL

Criar tabela `dou.document_chunk` (fonte de verdade dos chunks):

- `id` UUID
- `document_id` UUID FK
- `chunk_index` INT
- `chunk_text` TEXT
- `chunk_text_norm` TEXT
- `chunk_char_start`, `chunk_char_end`
- `token_estimate`
- `heading_context` TEXT
- `metadata_json` JSONB
- `created_at` TIMESTAMPTZ

Índices:

- `(document_id, chunk_index)`
- GIN em `chunk_text_norm` (opcional para fallback local)

### 1.2 Implementar chunker

Novo módulo sugerido:

- `ingest/chunker.py`

Responsabilidades:

- dividir `body_plain/body_html` em chunks estáveis
- preservar contexto local (seção, título, cabeçalho)
- atribuir offsets

### 1.3 Backfill de chunks

Script:

- `scripts/backfill_chunks.py`

Funções:

- processar docs em lotes
- idempotência por `document_id`
- resume por cursor
- logs de progresso

Entregáveis Fase 1:

- chunks gerados para todo acervo alvo
- integridade validada (contagem, offsets, cobertura)

---

## Fase 2 — Embeddings + Índice Vetorial no Elasticsearch

### 2.1 Mapping do índice `gabi_chunks_v1`

Campos principais:

- `chunk_id` (keyword)
- `doc_id` (keyword)
- `chunk_text` (text + analyzer pt)
- `embedding` (dense_vector, index=true, similarity=cosine)
- metadata para filtros/facets por período/seção/órgão/tipo

### 2.2 Pipeline de embedding

Novo módulo:

- `ingest/embedding_pipeline.py`

Fluxo:

- ler `dou.document_chunk`
- gerar embedding por lote
- retry com backoff
- escrever no ES chunks index

### 2.3 Backfill vetorial

Script:

- `scripts/backfill_embeddings.py`

Recursos:

- batch size configurável
- checkpoint/cursor
- métrica de throughput
- dead-letter para chunks com erro

Entregáveis Fase 2:

- `gabi_chunks_v1` íntegro
- paridade `PG chunks` vs `ES chunks`
- dashboard básico de cobertura

---

## Fase 3 — Retrieval Híbrido (BM25 + kNN + Fusão)

### 3.1 Query planner híbrido

Novo módulo:

- `search/hybrid_retriever.py`

Fluxo por query:

1. BM25 (docs/chunks) top_k_lexical
2. kNN vetorial top_k_vector
3. fusão por RRF (Reciprocal Rank Fusion)
4. dedupe por `chunk_id` e `doc_id`

### 3.2 Filtros

Aplicar filtros nos dois braços (lexical e vetorial):

- período (`date_from/date_to`)
- seção (`do1/do2/do3`)
- órgão
- tipo de ato

### 3.3 Endpoint e MCP

Adicionar endpoints:

- `GET /api/hybrid-search`
- `GET /api/rag-context`

Adicionar tools MCP:

- `es_hybrid_search`
- `es_rag_context`

Entregáveis Fase 3:

- busca híbrida funcional no web + MCP
- logs comparativos lexical vs hybrid

---

## Fase 4 — Reranking

### 4.1 Serviço de rerank

Novo módulo:

- `search/reranker.py`

Entrada:

- query + top_n candidatos (chunks)

Saída:

- candidatos rerankeados com score

### 4.2 Estratégia operacional

- rerank só no top-N (ex: 50)
- timeout rígido + fallback sem rerank
- circuit breaker para indisponibilidade do modelo

### 4.3 Integração no pipeline

Pipeline final:

- retrieval híbrido -> reranker -> top-k final (ex: 8-12 chunks)

Entregáveis Fase 4:

- ganho mensurável em NDCG/MRR/Recall@k
- fallback resiliente

---

## Fase 5 — Contextual Embeddings (qualidade)

### 5.1 Enriquecimento de contexto no chunk

Prefixar chunk no embedding com contexto estruturado, ex:

- `Órgão: ...`
- `Seção: ...`
- `Tipo: ...`
- `Data: ...`
- `Título: ...`

Sem poluir texto final exibido ao usuário.

### 5.2 Variações de embedding

Testes A/B:

- sem contexto
- contexto curto
- contexto completo

Comparar qualidade e custo.

Entregáveis Fase 5:

- configuração final de contextual embedding
- melhoria documentada no benchmark

---

## Fase 6 — Resposta RAG com citações

### 6.1 Context builder

Novo módulo:

- `rag/context_builder.py`

Responsabilidades:

- montar bloco de contexto com chunk + metadados
- manter rastreabilidade (`doc_id`, `chunk_id`, offsets)
- cortar contexto por orçamento de tokens

### 6.2 Geração de resposta

No chat/API:

- usar top chunks rerankeados
- resposta com citações explícitas por item
- links para `/api/document/{doc_id}`

### 6.3 Anti-hallucination

- instrução de “não inventar”
- recusar quando contexto insuficiente
- exibir confiança/fonte

Entregáveis Fase 6:

- modo RAG em produção no chat
- respostas auditáveis

---

## 5. Mudanças em Arquivos (proposta)

Novos:

- `ingest/chunker.py`
- `ingest/embedding_pipeline.py`
- `search/hybrid_retriever.py`
- `search/reranker.py`
- `rag/context_builder.py`
- `scripts/backfill_chunks.py`
- `scripts/backfill_embeddings.py`
- `scripts/eval_rag.py`
- `tests/test_chunker.py`
- `tests/test_hybrid_retriever.py`
- `tests/test_reranker.py`

Alterados:

- `dbsync/dou_schema.sql` (tabela de chunks)
- `web_server.py` (novos endpoints híbridos/RAG)
- `mcp_es_server.py` (tools híbridas)
- `README.md` (runbook RAG)
- `.env.example` (config modelos e toggles)

---

## 6. Configuração (.env)

Variáveis sugeridas:

- `RAG_ENABLED=true`
- `EMBED_PROVIDER=openai|cohere|local`
- `EMBED_MODEL=...`
- `EMBED_DIM=...`
- `RERANK_PROVIDER=...`
- `RERANK_MODEL=...`
- `HYBRID_TOPK_LEX=100`
- `HYBRID_TOPK_VEC=100`
- `RERANK_TOPN=50`
- `RAG_FINAL_K=10`
- `CHUNK_SIZE=900`
- `CHUNK_OVERLAP=150`

---

## 7. Observabilidade e Qualidade

### 7.1 Métricas online

- latência p50/p95 por etapa (bm25, knn, rerank)
- taxa de fallback do reranker
- hit-rate de cache
- distribuição de scores

### 7.2 Métricas offline

- Recall@10
- MRR@10
- NDCG@10
- Precision@5

### 7.3 Testes de regressão

- suite de queries fixas
- comparação automática contra baseline

---

## 8. Segurança e Governança

- mascarar PII em logs de query (quando aplicável)
- rate limit nos endpoints RAG pesados
- controle de custo por query (limite topN/token)
- trilha de auditoria de fontes citadas

---

## 9. Plano de Rollout

1. `dev`: habilitar híbrido sem rerank
2. `staging`: habilitar rerank para 10%-20% tráfego
3. `prod canary`: 5% queries no pipeline novo
4. `prod full`: 100% após métricas estáveis

Feature flags:

- `USE_HYBRID_RETRIEVAL`
- `USE_RERANKER`
- `USE_CONTEXTUAL_EMBEDDINGS`

---

## 10. Riscos e Mitigações

- Custo de embedding/rerank alto
  - mitigação: batch, cache, topN pequeno
- Latência alta
  - mitigação: timeout + fallback lexical
- Drift de qualidade
  - mitigação: benchmark contínuo + canary
- Complexidade operacional
  - mitigação: fases pequenas, flags e runbooks

---

## 11. Cronograma sugerido

- Semana 1: Fase 0 + Fase 1
- Semana 2: Fase 2
- Semana 3: Fase 3
- Semana 4: Fase 4
- Semana 5: Fase 5 + Fase 6 + rollout canary

---

## 12. Critério de pronto (Definition of Done)

- chunks e embeddings completos para escopo alvo
- endpoint híbrido e RAG em produção com feature flag
- reranking ativo com fallback estável
- melhoria >= 20% em NDCG@10 vs baseline lexical
- documentação operacional e testes automatizados

---

## 13. Proposta de execução imediata (após aprovação)

Ordem recomendada para começar amanhã:

1. Implementar `dou.document_chunk` + `ingest/chunker.py`
2. Backfill chunks em lote com checkpoint
3. Criar `gabi_chunks_v1` + backfill embeddings
4. Entregar `hybrid_search` (sem rerank) no MCP/web
5. Adicionar rerank e rodar benchmark A/B

