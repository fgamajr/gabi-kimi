# CAF-FINAL vs Gabi-Kimi — Gap Analysis
> Análise feita em 2026-03-31. Fonte: `/Users/fgamajr/Desktop/CAF-FINAL/caf_audit_knowledge`

## Contexto

**CAF-FINAL** (`caf_audit_knowledge`) é um sistema RAG maduro para busca e síntese de documentos de auditoria, com detecção de risco, scoring adaptativo e explainability fina.

**Gabi-Kimi** é uma plataforma de busca de larga escala (~16M docs DOU + 520K TCU) com intent detection sofisticado, MCP integration e trending discovery.

---

## O que o CAF-FINAL tem que o Gabi-Kimi NÃO tem

### 1. Pipeline de Geração de Respostas (Gap Crítico)

Gabi-Kimi é **search-only**. CAF-FINAL tem RAG end-to-end:

- **LLM providers**: OpenAI + Gemini (`llm/providers.py`)
- **9 tipos de query** com prompt templates específicos:
  - `exact_match`, `aggregation`, `summary`, `factual`, `exploratory`
  - `evidential`, `legal_reference`, `accountability`, `recommendation`
- **Injeção de contexto** no prompt: risco, conflito entre fontes, hierarquia, subscope
- **Aggregation bundle**: injeta JSON estruturado para queries de lista/contagem
- **Pipeline**: classify → assess risk → retrieve → aggregate → select prompt → LLM → trace

**Arquivos CAF relevantes:**
- `answering/service.py` — orquestrador principal
- `answering/classifier.py` — classificação de queries
- `answering/prompts.py` — templates por tipo
- `answering/aggregation.py` — pós-retrieval

---

### 2. Query Classification + Risk Detection

CAF tem 9 tipos de query vs 5 intents do Gabi. Gaps específicos:

**Risk Detection (10 flags):**
- `hierarchical_query` — detecta "achado 1, subachado 2"
- `subscope_resolution` — query pede subscope específico
- `entity_resolution` — ACH reference sem contexto claro
- `ambiguous_query`, `multi_entity`, `conflicting_sources`...
- **Risk score numérico** → `safe_mode` quando alto

**Safe Mode behavior:**
- Aumenta `candidate_limit` e `top_k`
- Instrui o LLM a preferir incompletude a inventar

**Facet Detection:**
- `hierarchical`: detecta padrão "achado [1-4](\.\d)*"
- `subscope`: detecção de subachado específico
- `exact_reference`: quoted strings ou padrão ACH

**Learned Patterns:**
- `ledger/query_patterns.json` — overrides aprendidos de feedback
- LLM fallback se confidence < 0.7

**Arquivo CAF:** `answering/classifier.py` (linhas 13-68 para risk weights)

---

### 3. Evidence-Aware Scoring

CAF detecta chunks com evidências e aplica boosts:

```python
# Padrões de evidência (retrieval/service.py, linhas 32-40)
"conforme peça"       → +0.25
"foi verificado"      → +0.20
"comprovado"          → +0.20
"documento analisado" → +0.15
"anexo"               → +0.10
section_type == "evidencia" → structural flag
```

- Para queries do tipo `evidential`: boost de até +20% no score final
- Gabi-Kimi: **nenhum equivalente**

**Arquivo CAF:** `retrieval/service.py` (linhas 32-40, 248-265)

---

### 4. Post-Retrieval Aggregation

Para queries do tipo "liste todas as causas do achado 1":

**Pipeline CAF:**
1. Retrieve 15 candidatos
2. **Deduplicação** (Jaccard + SequenceMatcher, threshold 0.9)
3. **Filtragem** por `section_type` preferido para o tipo de query
4. **Agrupamento** por `audit_object_id` + `subscope_id` + `section_type`
5. Injeta JSON estruturado no prompt com contagens + top items

**Gabi-Kimi:** flat list de resultados ordenados, sem agrupamento ou dedup

**Arquivo CAF:** `answering/aggregation.py`

---

### 5. Adaptive Scoring + Feedback Loops

CAF aprende com feedback do usuário:

**Arquivos de ledger:**
- `ledger/query_feedback.jsonl` — classificações incorretas reportadas
- `ledger/query_patterns.json` — overrides aprendidos
- `ledger/scoring_feedback.jsonl` — sucesso/falha de respostas
- `ledger/scoring_profiles.json` — pesos por tipo de query (atualizados incrementalmente)
- `ledger/query_logs.jsonl` — log completo de todas as queries/respostas

**CLI de feedback:**
```bash
caf-audit feedback-query "query" "correct_type"
caf-audit feedback-answer "query" --failure
```

**GraphQL mutations:**
```graphql
mutation { registerQueryFeedback(query: "...", correctType: "aggregation") }
mutation { registerAnswerFeedback(query: "...", success: false) }
```

**Gabi-Kimi:** nenhum mecanismo de aprendizado ou feedback

**Arquivo CAF:** `retrieval/scoring.py` (linhas 96-132)

---

### 6. Fine-Grained Explainability / Trace

CAF retorna trace JSON com **13 componentes por chunk**:

```python
{
  "bm25_raw", "bm25_norm",
  "vector_raw", "vector_norm",
  "rerank_raw", "rerank_norm",
  "authority",          # source_type weight
  "entity_density",     # ACH/legal reference frequency
  "evidence_score",     # pattern-based evidence signal
  "policy_multiplier",  # section/query-type boost
  "penalties": [...],   # each penalty applied + reason
  "boosts": [...],      # each boost applied + reason
  "scoring_profile",    # default vs learned
  "final_score",
  "reasons": [...]      # human-readable explanation
}
```

Também retorna `filtered_out` — chunks eliminados com motivo (debug artifacts, stack traces, review panels, boilerplate).

**Gabi-Kimi:** intent confidence + ES explain scores (BM25 term vectors). Sem breakdown de políticas.

**Arquivo CAF:** `retrieval/service.py` (linhas 458-570)

---

### 7. Policy-Based Scoring Multipliers

CAF aplica boosts/penalties baseados em metadados:

**Penalties:**
- `section_type == "debug"` → -0.4
- `section_type == "toc"` → -0.3
- `section_type == "boilerplate"` → -0.15
- Stack traces, review panels → hard filter (pré-ranking)

**Boosts:**
- `section_type == "sintese"` → +0.15
- `section_type == "causa"` → +0.10
- `section_type == "efeito"` → +0.10
- `source_type == "normative"` → +0.25
- `source_type == "ground_truth"` → +0.15
- Exact match detected → +0.20
- Legal signal in chunk → +0.15

**Arquivo CAF:** `retrieval/scoring.py`

---

### 8. Cross-Encoder Reranker Local (BAAI/bge-reranker-large)

CAF usa cross-encoder local com rich metadata como input:

```
[Document title] | [Source type] | [Section type] | [Audit object] | [Page range] | [Chunk text]
```

Gabi usa Cohere (API) ou HTTP endpoint local, mas o input é apenas texto dos campos `identifica + ementa + sumario + dispositivo_resumo`.

**Gap**: CAF injeta metadados estruturados no reranker, não só texto — potencialmente melhor discriminação.

**Arquivo CAF:** `retrieval/reranker.py`

---

### 9. Determinism Validation Tool

CAF tem ferramenta explícita para validar reproducibilidade:

```bash
caf-audit build --full
caf-audit build --full
caf-audit debug compare-chunks  # Asserts chunk IDs unchanged
```

Gabi tem chunk IDs determinísticos (sha256-based) mas **sem ferramenta de validação**.

---

## O que o Gabi-Kimi tem melhor (que o CAF não tem)

| Feature | Gabi-Kimi | CAF-FINAL |
|---------|-----------|-----------|
| Person name detection | Sofisticado (60 nomes BR, variantes ortográficas y↔i, ph↔f) | Nenhum |
| Legal alias expansion | Canonical laws index com variantes | Nenhum |
| Trending detection | 7/14/30 dias vs baseline 90 dias | Nenhum |
| Multi-pass fallback | Phrase → bag-of-words, relaxação progressiva | Merge simples |
| RRF (Reciprocal Rank Fusion) | Sim | Weighted sum |
| Escala | 16M+ docs, multi-corpus | 1 repositório |
| MCP integration | 21+ tools | Apenas GraphQL + CLI |
| Topic classification | 12 tópicos determinísticos | Nenhum |
| Multi-corpus federation | DOU + TCU + BTCU + normas | Single corpus |

---

## Tabela de Paridade

| Capability | CAF-FINAL | Gabi-Kimi |
|-----------|-----------|-----------|
| Answer Generation | ✅✅✅ Full LLM pipeline | ❌ Search only |
| Query Classification | ✅✅ 9 tipos + risk | ✅ 5 intents |
| Evidence Scoring | ✅✅ Pattern-based | ❌ Nenhum |
| Adaptive Learning | ✅✅ Feedback loops | ❌ Nenhum |
| Post-Retrieval Aggregation | ✅✅ Sim | ❌ Não |
| Explainability Depth | ✅✅✅ 13 componentes | ✅ Basic |
| Policy Multipliers | ✅✅ Section + source boosts | ❌ Parcial |
| GraphQL + Mutations | ✅ Sim | ❌ MCP only |
| Person Name Detection | ❌ Nenhum | ✅✅ Sofisticado |
| Legal Alias Expansion | ❌ Nenhum | ✅✅ Canonical index |
| Trending Detection | ❌ Nenhum | ✅✅ 7/14/30 dias |
| Multi-Pass Fallback | ❌ Simples | ✅ Phrase → BoW |
| RRF | ❌ Weighted sum | ✅ RRF |
| Scale | ❌ Single repo | ✅✅ 16M+ docs |
| MCP Integration | ❌ Não | ✅✅ 21+ tools |
| Determinism Testing | ✅ compare-chunks | ❌ Não testado |

---

## Prioridades de Implementação

| Prioridade | Feature | Esforço Estimado |
|-----------|---------|-----------------|
| 🔴 Alto | Answer generation pipeline (LLM + prompts por tipo de query) | Alto |
| 🔴 Alto | Post-retrieval aggregation (dedup + agrupamento por facets) | Médio |
| 🟡 Médio | Risk detection + safe mode | Médio |
| 🟡 Médio | Feedback loops (query patterns + scoring profiles) | Médio |
| 🟢 Baixo | Evidence-aware scoring patterns | Baixo |
| 🟢 Baixo | Fine-grained trace (13 componentes) | Baixo |
| 🟢 Baixo | Policy multipliers (section boosts/penalties) | Baixo |
| 🟢 Baixo | Determinism validation CLI tool | Baixo |

---

## Referências

- **CAF-FINAL source:** `/Users/fgamajr/Desktop/CAF-FINAL/caf_audit_knowledge/src/caf_audit_knowledge/`
- **Arquivos chave do CAF:**
  - `answering/service.py` — orquestrador RAG
  - `answering/classifier.py` — classificação + risk
  - `answering/aggregation.py` — pós-retrieval dedup/agrupamento
  - `retrieval/service.py` — retrieval + trace
  - `retrieval/scoring.py` — políticas de scoring
  - `retrieval/reranker.py` — cross-encoder BAAI/bge-reranker-large
  - `repo_semantics.py` — extração de audit_object_id, section_type
  - `ingest/chunking.py` — chunking com importance scoring
