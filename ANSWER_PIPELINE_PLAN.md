# PLANO FINAL: Answer Generation Pipeline para GABI-Kimi

**Versão**: 2.0 (incorpora feedback do painel swarm)
**Data**: 2026-04-01
**Status**: APROVADO COM RESSALVAS pelo painel de agentes

---

## 1. Contexto

**GABI-Kimi** é plataforma de busca full-text do Diário Oficial da União (~16M docs DOU + 520K TCU), atualmente **search-only**. O objetivo é adicionar pipeline RAG completo de geração de respostas, herdando padrões validados do CAF-FINAL (`/Users/fgamajr/Desktop/CAF-FINAL/caf_audit_knowledge`).

**Lacunas vs CAF-FINAL**: Answer generation, query classification expandida, risk detection, aggregation, feedback loops, trace granular.

---

## 2. FASE 0 — Corpus Health + Freshness Layer (NOVA)

**Responsabilidade**: Verificar estado do corpus antes de qualquer resposta.

- Registrar timestamp da última ingestão bem-sucedida por fonte:
  - `dou_secao1`, `dou_secao2`, `dou_secao3`
  - `tcu_acordaos`, `tcu_normas`, `tcu_publicacoes`
- Verificar se há gaps > 24h desde última ingestão
- Expor freshness data na resposta (`"corpus_freshness": {...}`)
- Se tema tem corpus potencialmente stale, adicionar disclaimer na resposta
- **Arquivos novos**: `src/backend/answering/freshness.py`

---

## 3. FASE 1 — Query Classification + Risk Detection

**Responsabilidade**: Classificar intenção e avaliar risco antes de retrieve.

### 3.1 Mapeamento GABI → CAF (5 → 9 tipos)

| GABI Intent | CAF Type | Confidence Base |
|-------------|----------|-----------------|
| EXACT_NAME | exact_match | 0.95 |
| CANONICAL_LOOKUP | legal_reference | 0.90 |
| PERSON_NAME | exact_match | 0.90 |
| TRENDING_BROWSE | exploratory | 0.80 |
| SUBJECT_EXPLORE | exploratory | 0.50 |

**Tipos adicionais GABI-native**:
- `count_query` — "quantas portarias do MEC" → aggregation
- `source_conflict` — queries explícitas sobre conflito DOU vs TCU

### 3.2 Risk Flags (10 flags)

```python
RISK_WEIGHTS = {
    "hierarchical_query": 0.30,        # ementa hierarchy
    "subscope_resolution_risk": 0.25,   # se subnível mencionado
    "multi_evidence_required": 0.30,    # aggregation/summary/evidential
    "entity_resolution_risk": 0.20,    # pessoa nomeada sem contexto
    "aggregation_precision_risk": 0.20, # count queries
    "legal_precision_required": 0.15,   # legislação explícita
    "recommendation_synthesis_risk": 0.20,  # propostas
    "low_context": 0.20,              # < 3 resultados
    "cross_source_conflict": 0.15,     # DOU vs TCU
    "ranking_ambiguity": 0.15,         # score margin < 0.08
    "corpus_stale": 0.25,              # FASE 0 triggered
}
```

### 3.3 Safe Mode

- Ativo quando `risk.score >= 0.5`
- Aumenta candidate_limit em +10
- Instrui LLM: "prefira incompletude a inventar"

### 3.4 Artefatos

- **Arquivo novo**: `src/backend/answering/classifier.py`
- **Dependências**: reutiliza `src/backend/search/intent.py` para intents base

---

## 4. FASE 2+3 — Answer Service + Aggregation (CO-DESENVOLVIDOS)

**Responsabilidade**: Resposta LLM com citação verificável + agregação estruturada.

### 4.1 Subcamadas

**Subcamada 2a: RAG Verificável**
- Respostas factuais com citação inline rastreável
- Formato: `[doc_id, pagina]` — link direto ao documento fonte
- NUNCA gera citação que não venha de chunk recuperado

**Subcamada 2b: Síntese Generativa**
- Marcação: `[SÍNTESE]` prefixo em respostas interpretativas
- Disclaimer: "Verifique detalhes no documento original"

### 4.2 Prompt Templates

```python
SYSTEM_PROMPT = """Você é assistente de pesquisa sobre o Diário Oficial da União (DOU)
e Tribunal de Contas da União (TCU). REGRAS:
- Responda apenas com evidências dos documentos recuperados.
- Cite inline usando [doc_id, página].
- Não invente números, fatos ou referências legais.
- Se evidência for insuficiente, diga explicitamente.
- Quando fontes discordarem (DOU vs TCU), acknowledge o conflito."""

TASKS = {
    "exact_match": "Retorne citação direta com contexto.",
    "aggregation": "Agregue TODAS as evidências. Distinga categorias de totais.",
    "summary": "Produza síntese completa de múltiplas fontes.",
    "evidential": "Liste evidências com procedência explícita.",
    "legal_reference": "Identifique legislação com citação ao trecho.",
    "accountability": "Identifique responsável; distinga direto vs contextual.",
    "recommendation": "Extraia proposta vinculada à evidência.",
    "exploratory": "Sintetize padrões identificados com cautela.",
}
```

### 4.3 Aggregation Layer

- Deduplicação semântica: Jaccard + SequenceMatcher (threshold 0.9)
- Agrupamento por: `issuing_organ`, `art_type`, `section` (do1/do2/do3), período
- Filtragem por seção preferida por tipo de query

### 4.4 Output Bundle

```json
{
  "answer": "...",
  "answer_type": "factual | synthetic",
  "confidence": 0.85,
  "corpus_freshness": {...},
  "classification": {...},
  "risk": {...},
  "evidence": [...],
  "aggregation": {...},
  "conflict_note": "...",
  "disclaimer": "..."
}
```

### 4.5 Artefatos

- **Arquivos novos**:
  - `src/backend/answering/service.py`
  - `src/backend/answering/prompts.py`
  - `src/backend/answering/aggregation.py`

---

## 5. FASE 4 — Feedback Loops + Ledger

**Responsabilidade**: Aprendizado contínuo de classificações e respostas.

### 5.1 Estrutura de Ledger

```
src/backend/answering/ledger/
├── query_logs.jsonl          # todas as queries + resposta + classification + risk
├── query_feedback.jsonl      # {"query", "predicted", "correct", "source"}
├── scoring_feedback.jsonl    # {"query", "answer", "success", "reason"}
├── query_patterns.json       # {"patterns": {"token": "type", ...}}
└── scoring_profiles.json     # {"profiles": {"exact_match": {...weights...}}}
```

### 5.2 CLI de Feedback

```bash
gabi feedback-query "consulta" --predicted=exploratory --correct=legal_reference
gabi feedback-answer "consulta" --failure --reason="citou norma inexistente"
gabi agent-learn  # processa feedback e atualiza patterns
```

### 5.3 Adaptive Classifier

- Token frequency mining de feedback
- Min support: 3 occurrences
- Min token length: 4

### 5.4 Artefatos

- **Arquivos novos**:
  - `src/backend/answering/ledger.py`
  - CLI commands em `src/backend/cli.py`

---

## 6. FASE 5 — MCP Tool + Integration

**Responsabilidade**: Expor `gabi_answer` via MCP server.

### 6.1 Nova Tool MCP

```python
@gabi_dou()
def gabi_answer(
    query: str,
    date_from: Optional[str] = None,  # YYYY-MM-DD
    date_to: Optional[str] = None,    # YYYY-MM-DD
    section: Optional[str] = None,    # do1|do2|do3
    source: Optional[str] = None,    # dou|tcu|all
    intent_override: Optional[str] = None,
) -> dict:
    """Gera resposta RAG para query sobre DOU/TCU."""
```

### 6.2 Fluxo Integrado

```
User query
    ↓
FASE 0: Corpus freshness check
    ↓
FASE 1: Classify intent + assess risk
    ↓
hybrid_search() [existente]
    ↓
rerank() [existente]
    ↓
FASE 2+3: Answer + Aggregate
    ↓
FASE 4: Log (async)
    ↓
Return + trace
```

### 6.3 Fallback Graceful

Se LLM unavailable, retorna search results com aviso.

### 6.4 Artefatos

- **Arquivos modificados**:
  - `ops/bin/mcp_es_server.py` — adicionar tool `gabi_answer`

---

## 7. FASE 6 — Trace + Auditoria Jurídica

**Responsabilidade**: Explainability completa para debugging e compliance.

### 7.1 13 Componentes por Chunk

```json
{
  "chunk_id": "...",
  "bm25_raw": 12.5,
  "bm25_norm": 0.82,
  "vector_raw": 0.73,
  "vector_norm": 0.68,
  "rerank_raw": 0.91,
  "rerank_norm": 0.95,
  "authority": 1.0,
  "entity_density": 0.45,
  "evidence_score": 0.25,
  "policy_multiplier": 1.15,
  "boosts": [{"pattern": "sintese", "factor": 1.15}],
  "penalties": [{"pattern": "boilerplate", "factor": 0.85}],
  "final_score": 0.847,
  "reasons": ["boost_sintese", "authority_normative"]
}
```

### 7.2 Output com Confidence Disclosure

```json
{
  "filtered_out": [
    {"chunk_id": "...", "reason": "debug_artifact", "pattern": "bug:"}
  ],
  "confidence_disclosure": {
    "score": 0.72,
    "below_threshold": false,
    "disclaimer": "Resposta baseada em 4 documentos."
  }
}
```

### 7.3 Artefatos

- **Arquivos modificados**:
  - `src/backend/answering/service.py` — adicionar trace generation
  - `ops/bin/mcp_es_server.py` — expor trace via tool

---

## 8. Riscos e Mitigações

| # | Risco | Prob | Impacto | Mitigação |
|---|-------|------|---------|-----------|
| R1 | **Alucinação Jurídica com Aparência de Autoridade** | Alta | Crítico | Citação só de chunks recuperados; disclosure obrigatório |
| R2 | **Desatualização Silenciosa do Corpus** | Média | Alto | FASE 0: freshness check + alerta |
| R3 | **Ambiguidade de Jurisdição e Conflito Normativo** | Média | Alto | FASE 2: conflict_note explícito; safe_mode |
| R4 | LLM latência alta | Alta | Médio | Async, timeout 30s, fallback search-only |
| R5 | Jurisprudência DOU diferente do CAF | Média | Médio | Validação com queries reais DOU |
| R6 | Feedback loops poluem | Baixa | Baixo | Threshold mínimo (3 occurrences) |
| R7 | LLM config não calibrado para linguagem normativa | Desconhecida | Alto | Testar com dataset de queries DOU reais |

---

## 9. Timeline

| Fase | Responsabilidade | Esforço | Semana |
|------|------------------|---------|--------|
| FASE 0 | Corpus Health + Freshness | 2 dias | 1 |
| FASE 1 | Query Classification + Risk | 3 dias | 1-2 |
| FASE 2+3 | Answer Service + Aggregation | 5 dias | 2-3 |
| FASE 4 | Feedback Loops + Ledger | 2 dias | 3 |
| FASE 5 | MCP Integration | 3 dias | 3-4 |
| FASE 6 | Trace + Auditoria | 2 dias | 4 |
| **Total** | | **~17 dias** | **4 semanas** |

---

## 10. Critérios de Sucesso

1. `gabi_answer` retorna resposta LLM com citação inline `[doc_id, pagina]`
2. Queries de contagem ("quantas portarias do MEC em 2025?") retornam JSON de agregação
3. Safe mode ativa para queries com risk.score >= 0.5
4. Corpus freshness exposto na resposta
5. Separação RAG verificável vs síntese generativa no output
6. CLI feedback funcional
7. Trace com 13 componentes disponível
8. Fallback graceful: se LLM unavailable, retorna search results
9. Latência < 5s para 95% (excluindo LLM call)

---

## 11. Dependências Técnicas

| Dependência | Status | Reusa de |
|-------------|--------|----------|
| ANTHROPIC_API_KEY | ✅ Configurado | `settings.EDITORIAL_LLM_MODEL` |
| httpx | ✅ Em uso | `editorial.py` |
| hybrid_search | ✅ Existente | `src/backend/search/hybrid.py` |
| reranker | ✅ Existente | `src/backend/search/reranker.py` |
| intent classification | ✅ Existente | `src/backend/search/intent.py` |

---

## 12. Priorização de Implementação

```
Semana 1: FASE 0 (freshness) + FASE 1 (classifier)
          ↓
Semana 2-3: FASE 2+3 (Answer Service + Aggregation) — MAIOR IMPACTO
          ↓
Semana 3: FASE 4 (Feedback Loops)
          ↓
Semana 3-4: FASE 5 (MCP Integration)
          ↓
Semana 4: FASE 6 (Trace)
```

---

## 13. Gaps Identificados pelo Painel Swarm

O painel identificou 3 riscos críticos não mencionados no plano original:

1. **Alucinação Jurídica com Aparência de Autoridade** — Mitigado com citação só de chunks + disclosure
2. **Desatualização Silenciosa do Corpus** — Mitigado com FASE 0 (freshness)
3. **Ambiguidade de Jurisdição e Conflito Normativo** — Mitigado com conflict_note + safe_mode

---

## 14. Diretórios do Projeto

```
src/backend/answering/
├── __init__.py
├── freshness.py      # FASE 0
├── classifier.py     # FASE 1
├── service.py        # FASE 2+3
├── prompts.py        # FASE 2+3
├── aggregation.py    # FASE 2+3
├── ledger.py         # FASE 4
└── ledger/
    ├── query_logs.jsonl
    ├── query_feedback.jsonl
    ├── scoring_feedback.jsonl
    ├── query_patterns.json
    └── scoring_profiles.json
```
