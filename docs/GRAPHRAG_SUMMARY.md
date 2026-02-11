# GraphRAG Architecture Summary for GABI

## Deliverables Overview

This document summarizes the GraphRAG architecture design for GABI, addressing all 5 requirements.

---

## 1. Graph Schema (Nodes, Edges, Properties)

### Node Types

| Node | Key Properties | Purpose |
|------|---------------|---------|
| `:Document` | `document_id`, `title`, `doc_type`, `date`, `relator`, `pg_id` | Central entity - legal documents |
| `:Ministro` | `name`, `cargo`, `ativo` | Court ministers/reporters |
| `:Orgao` | `name`, `sigla`, `tipo` | Chambers, plenary, committees |
| `:Processo` | `numero`, `tipo`, `ano` | Legal process numbers |
| `:Normativo` | `numero`, `tipo`, `ano`, `status` | Internal norms (IN, Portaria) |
| `:Sumula` | `numero`, `tema`, `vigente` | Jurisprudence summaries |
| `:Tema` | `nome`, `palavras_chave` | Subject matter topics |
| `:Entidade` | `nome`, `tipo`, `cpf_cnpj` | People, companies, agencies |

### Edge Types

| Relationship | Direction | Properties | Use Case |
|--------------|-----------|------------|----------|
| `:CITA` | Doc → Doc/Sumula/Norma | `context`, `trecho` | Citation tracking |
| `:REVOGA` | Doc → Norma | `parcial`, `artigos` | Norm revocation |
| `:MODIFICA` | Doc → Norma | `artigos` | Norm modification |
| `:FUNDAMENTA` | Doc → Doc | `fundamento` | Precedent foundation |
| `:DIVERGE` | Doc → Doc | `trecho` | Conflicting jurisprudence |
| `:CONCORDA` | Doc → Doc | - | Agreement with precedent |
| `:RELATADO_POR` | Doc → Ministro | - | Reporter assignment |
| `:TRATA_DE` | Doc → Tema | - | Subject classification |
| `:ORIGINADO_DE` | Doc → Processo | - | Process origin |

---

## 2. Extraction Prompts for LLM

### Main Extraction Prompt

```
Você é um assistente especializado em extrair informações de documentos 
jurídicos do TCU (Tribunal de Contas da União).

Analise o texto abaixo e extraia:
1. Entidades mencionadas (ministros, órgãos, processos, temas)
2. Relações entre documentos (citações, revogações, divergências)

ENTIDADES JÁ IDENTIFICADAS (use estes IDs):
{entity_context}

TEXTO DO DOCUMENTO:
---
{text}
---

Retorne APENAS um JSON válido com o seguinte formato:
{
    "entities": [
        {
            "id": "identificador-unico",
            "type": "Ministro|Orgao|Processo|Tema|Entidade",
            "name": "Nome completo",
            "properties": {},
            "source_text": "trecho onde aparece"
        }
    ],
    "relations": [
        {
            "source_id": "id-origem",
            "target_id": "id-destino",
            "relation_type": "CITA|REVOGA|MODIFICA|FUNDAMENTA|DIVERGE",
            "properties": {},
            "source_text": "trecho evidenciando a relação"
        }
    ]
}
```

### Specialized Prompts

- **Citation Extraction**: Identifies positive/negative/neutral citations
- **Precedent Relation**: Detects `segue`, `diverge`, `distingue`, `supera` relationships
- **Normative Chain**: Extracts `revoga`, `altera`, `regulamenta` relationships
- **Minister Identification**: Identifies relator, redator, votantes

---

## 3. Cypher Query Examples

### UC1: Find all documents citing a specific sumula
```cypher
MATCH (s:Sumula {numero: 247})<-[:CITA]-(d:Document)
RETURN d.document_id, d.title, d.date
ORDER BY d.date DESC
```

### UC2: Full citation network around a document
```cypher
MATCH (center:Document {document_id: "AC-01234-2024"})
OPTIONAL MATCH (center)-[:CITA]->(cited:Document)
OPTIONAL MATCH (citing:Document)-[:CITA]->(center)
RETURN collect(DISTINCT cited) as cited_docs,
       collect(DISTINCT citing) as citing_docs
```

### UC3: Find conflicting precedents
```cypher
MATCH (d1:Document)-[:DIVERGE]->(d2:Document)
WHERE d1.date > d2.date
RETURN d1.document_id as newer_doc,
       d2.document_id as older_doc,
       d1.date as divergence_date
ORDER BY d1.date DESC
```

### UC4: Trace normative chain
```cypher
MATCH path = (latest:Normativo)-[:REVOGA|MODIFICA*1..10]->(oldest:Normativo)
WHERE latest.numero = "IN-0075-2022"
RETURN [n in nodes(path) | n.numero] as chain
```

### UC5: PageRank for document authority
```cypher
CALL gds.pageRank.stream('document-graph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).document_id as doc_id,
       score as authority
ORDER BY score DESC
LIMIT 20
```

### UC6: Shortest path between documents
```cypher
MATCH (start:Document {document_id: "AC-01000-2020"}),
      (end:Document {document_id: "AC-02000-2024"})
MATCH path = shortestPath((start)-[:CITA|FUNDAMENTA*]-(end))
RETURN [n in nodes(path) | n.document_id] as path_nodes
```

---

## 4. Performance Considerations

### 4.1 Technology Choice: Neo4j vs PostgreSQL

| Aspect | Neo4j (Chosen) | PostgreSQL CTEs |
|--------|----------------|-----------------|
| Deep traversal (5+ hops) | O(depth) | O(n log n) |
| Pathfinding | Native | Complex recursive |
| PageRank/centrality | Built-in GDS | Manual implementation |
| Visualization | Neo4j Browser | External tools |
| Best for | Complex legal networks | Simple relationships |

### 4.2 Neo4j Configuration

```yaml
# docker-compose.yml
services:
  neo4j:
    image: neo4j:5.15-enterprise
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc", "gds"]
      - NEO4J_dbms_memory_heap_max__size=8G
      - NEO4J_dbms_memory_pagecache_size=4G
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
```

### 4.3 Indexing Strategy

```cypher
-- Constraints (unique identifiers)
CREATE CONSTRAINT document_id FOR (d:Document) REQUIRE d.document_id IS UNIQUE;
CREATE CONSTRAINT ministro_id FOR (m:Ministro) REQUIRE m.id IS UNIQUE;

-- Indexes (query performance)
CREATE INDEX document_date FOR (d:Document) ON (d.date);
CREATE INDEX document_source FOR (d:Document) ON (d.source_id);

-- Full-text search
CALL db.index.fulltext.createNodeIndex(
    "documentText", 
    ["Document"], 
    ["title", "ementa"]
);
```

### 4.4 Caching

- Graph query results cached in Redis with 1-hour TTL
- Citation networks cached per document
- Invalidation on document update/delete

---

## 5. Incremental Update Strategy

### 5.1 Pipeline Integration

```
Existing Pipeline:
Discovery → Fetch → Parse → Chunk → Embed → Index (PG+ES)

Extended Pipeline (+ GraphRAG):
Discovery → Fetch → Parse → Chunk → Embed → Index (PG+ES) → Graph Extraction → Graph Index (Neo4j)
```

### 5.2 Change Detection

```python
class IncrementalGraphUpdater:
    async def detect_changes(self, document_id, new_extraction):
        # 1. Get current state from Neo4j
        current = await self._get_current_state(document_id)
        
        # 2. Calculate diffs
        nodes_to_add = new_entities - current_entities
        nodes_to_remove = current_entities - new_entities
        relations_to_add = new_relations - current_relations
        
        # 3. Apply only changes
        await self.apply_changes(changeset)
```

### 5.3 Backfill Process

```bash
# Process all existing documents
python scripts/backfill_graph.py \
    --neo4j-uri bolt://localhost:7687 \
    --neo4j-user neo4j \
    --neo4j-password $NEO4J_PASSWORD \
    --batch-size 100 \
    --source tcu_acordaos
```

---

## Code Implementation Structure

```
src/gabi/graphrag/
├── __init__.py           # Public API exports
├── extractor.py          # LLM entity/relation extraction
├── pipeline.py           # Graph construction pipeline
├── search.py             # Graph-aware search service
├── api.py                # FastAPI endpoints
├── cache.py              # Redis caching layer
└── optimizations.py      # Query optimization utilities

scripts/
└── backfill_graph.py     # Backfill existing documents

docs/
├── GRAPHRAG_ARCHITECTURE.md   # Full design document
└── GRAPHRAG_SUMMARY.md        # This summary
```

---

## API Endpoints

```python
# Graph-aware search
POST /api/v1/graph/search
    query: str
    graph_depth: int = 2
    include_citations: bool = true
    include_conflicts: bool = true

# Document exploration
GET /api/v1/graph/documents/{doc_id}/citations
GET /api/v1/graph/documents/{doc_id}/precedent-chain

# Normative analysis
GET /api/v1/graph/normativos/{norm_id}/evolution

# Health check
GET /api/v1/graph/health
```

---

## Key Benefits for TCU

1. **Normative Chain Discovery**: Automatically trace IN 75/2022 → IN 43/2017 revocation chain
2. **Conflict Detection**: Find diverging jurisprudence on the same topic
3. **Citation Authority**: PageRank identifies most influential precedents
4. **Minister Tracking**: Follow a minister's jurisprudence evolution
5. **Process Context**: See all documents related to a specific process

---

## Configuration Additions (config.py)

```python
# Neo4j connection
neo4j_uri: str = "bolt://localhost:7687"
neo4j_user: str = "neo4j"
neo4j_password: SecretStr

# Feature flags
graphrag_enabled: bool = False
graphrag_cache_ttl: int = 3600
graphrag_default_depth: int = 2

# LLM settings
graphrag_llm_model: str = "gpt-4"
graphrag_llm_temperature: float = 0.0
```
