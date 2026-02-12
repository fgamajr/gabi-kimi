# GraphRAG Architecture Design for GABI

## Executive Summary

GraphRAG (Graph-based Retrieval Augmented Generation) extends GABI's search capabilities by modeling legal documents as a knowledge graph. This enables relationship-aware search that understands citations, revocations, precedents, and normative chains - essential for legal research at TCU.

## 1. Graph Data Model

### 1.1 Technology Selection: Neo4j vs PostgreSQL

**Decision: Use Neo4j as primary graph store with PostgreSQL for entity metadata**

| Criteria | Neo4j | PostgreSQL (Recursive CTEs) |
|----------|-------|---------------------------|
| Query Complexity | Native graph traversal | Complex recursive queries |
| Performance (deep traversal) | O(depth) | O(n log n) with depth |
| Pathfinding | Built-in algorithms | Manual implementation |
| Visualization | Native browser | External tools needed |
| Team Expertise | New learning curve | Existing SQL knowledge |
| Integration | New dependency | Existing infrastructure |

**Rationale:** Legal citation networks require multi-hop traversals (e.g., "find all documents that cite documents that cite X"). Neo4j's native graph storage provides orders of magnitude better performance for these queries.

### 1.2 Graph Schema

```cypher
// ============================================
// NODE TYPES
// ============================================

(:Document {
    document_id: string,           // External ID (e.g., "AC-1234-2024")
    title: string,
    doc_type: string,              // "acordao" | "norma" | "sumula" | "voto"
    source_id: string,             // tcu_acordaos, tcu_normas
    date: date,
    ementa: string,                // Brief summary
    relator: string,               // Minister/Reporter
    tribunal: string,              // TCU, STF, etc.
    camara: string,                // TCU chamber (e.g., "1ª Câmara")
    processo: string,              // Process number
    status: string,                // "active" | "revoked" | "modified"
    pg_id: string                  // Reference to PostgreSQL document.id
})

(:Ministro {
    name: string,
    nome_completo: string,
    cargo: string,                 // "Ministro" | "Procurador"
    ativo: boolean,
    nomeacao_date: date
})

(:Orgao {
    name: string,
    sigla: string,
    tipo: string,                  // "camara" | "plenário" | "comissao"
    ativo: boolean
})

(:Processo {
    numero: string,
    tipo: string,                  // "TC" | "AP" | "MS"
    ano: integer,
    partes: list,                  // ["Nome Parte 1", "Nome Parte 2"]
    assunto: string
})

(:Normativo {
    numero: string,
    tipo: string,                  // "IN" | "Portaria" | "Resolucao"
    ano: integer,
    orgao_issuer: string,
    status: string                 // "vigente" | "revogada" | "modificada"
})

(:Sumula {
    numero: integer,
    tema: string,
    texto: string,
    vigente: boolean
})

(:Tema {
    nome: string,
    descricao: string,
    palavras_chave: list
})

(:Entidade {
    nome: string,
    tipo: string,                  // "pessoa" | "empresa" | "orgao_publico"
    cpf_cnpj: string
})

// ============================================
// EDGE TYPES
// ============================================

(:Document)-[:CITA { tipo: string, trecho: string, pagina: int }]->(:Document)
(:Document)-[:CITA]->(:Sumula)
(:Document)-[:CITA]->(:Normativo)

(:Document)-[:REVOGA { parcial: boolean, artigos: list }]->(:Normativo)
(:Document)-[:MODIFICA { artigos: list }]->(:Normativo)

(:Document)-[:FUNDAMENTA { fundamento: string }]->(:Document)
(:Document)-[:DIVERGE { trecho: string }]->(:Document)
(:Document)-[:CONCORDA]->(:Document)

(:Document)-[:RELATADO_POR]->(:Ministro)
(:Document)-[:REDIGIDO_POR]->(:Ministro)
(:Document)-[:VOTADO_POR { posicao: string }]->(:Ministro)

(:Document)-[:ORIGINADO_DE]->(:Processo)
(:Document)-[:JULGADO_EM]->(:Orgao)

(:Document)-[:TRATA_DE]->(:Tema)
(:Document)-[:MENTIONA]->(:Entidade)

(:Processo)-[:PARTE]->(:Entidade)
(:Normativo)-[:ALTERA]->(:Normativo)
```

### 1.3 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         GRAPH SCHEMA                             │
└─────────────────────────────────────────────────────────────────┘

┌──────────────┐     CITA      ┌──────────────┐
│   Document   │◄─────────────►│   Document   │
└──────┬───────┘               └──────┬───────┘
       │                              │
       │ RELATADO_POR                 │ FUNDAMENTA
       ▼                              ▼
┌──────────────┐               ┌──────────────┐
│   Ministro   │               │   Document   │
└──────────────┘               └──────────────┘
                                     │
       ┌─────────────────────────────┼─────────────────────────────┐
       │                             │                             │
       ▼                             ▼                             ▼
┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│    Tema      │           │   Processo   │           │   Orgao      │
└──────────────┘           └──────────────┘           └──────────────┘

┌──────────────┐     CITA      ┌──────────────┐
│   Document   │──────────────►│    Sumula    │
└──────────────┘               └──────────────┘

┌──────────────┐    REVOGA     ┌──────────────┐
│   Document   │──────────────►│  Normativo   │
└──────────────┘               └──────────────┘

┌──────────────┐    MODIFICA   ┌──────────────┐
│   Document   │──────────────►│  Normativo   │
└──────────────┘               └──────────────┘

┌──────────────┐    DIVERGE    ┌──────────────┐
│   Document   │──────────────►│   Document   │
└──────────────┘               └──────────────┘
```

## 2. Entity and Relation Extraction

### 2.1 LLM Extraction Pipeline

```python
# src/gabi/graphrag/extractor.py

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import json
import re


@dataclass
class ExtractedEntity:
    """Entity extracted from document text."""
    id: str                          # Normalized ID
    type: str                        # Entity type
    name: str                        # Display name
    properties: Dict[str, Any]       # Additional properties
    source_text: str                 # Original text fragment
    confidence: float                # Extraction confidence


@dataclass
class ExtractedRelation:
    """Relationship extracted from document text."""
    source_id: str                   # Source entity ID
    target_id: str                   # Target entity ID
    relation_type: str               # Type of relationship
    properties: Dict[str, Any]       # Edge properties
    source_text: str                 # Supporting text
    confidence: float                # Extraction confidence


class LegalEntityExtractor:
    """Extract entities and relations from legal documents using LLM."""
    
    # Document type patterns for normalization
    DOC_PATTERNS = {
        'acordao': [
            r'Ac[óo]rd[aã]o\s*(?:n[º°]?\s*)?(\d{1,5})[/-](\d{2,4})',
            r'AC[\s-]*(\d{1,5})[/-](\d{2,4})',
        ],
        'sumula': [
            r'S[úu]mula\s*(?:TCU\s*)?(?:n[º°]?\s*)?(\d{1,3})',
            r'STCU[\s-]*(\d{1,3})',
        ],
        'normativo': [
            r'(IN|Portaria|Resolu[çc][ãa]o)\s*(?:n[º°]?\s*)?(\d{1,4})[/-](\d{2,4})',
            r'(IN|Port\.?|Res\.?)\s*(\d{1,4})[/-](\d{2,4})',
        ],
        'processo': [
            r'Processo\s*(?:TC|n[º°])?\s*(\d{7,10})[/-](\d{2})[/-](\d)',
            r'TC[\s-]*(\d{7,10})[/-](\d{2})[/-](\d)',
        ],
    }
    
    def __init__(self, llm_client: Any):
        self.llm_client = llm_client
    
    async def extract(self, document_text: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Extract entities and relations from document.
        
        Args:
            document_text: Full text of the document
            metadata: Document metadata (source_id, date, etc.)
            
        Returns:
            Dictionary with entities and relations
        """
        # Phase 1: Regex pre-extraction for known patterns
        regex_entities = self._extract_regex_patterns(document_text)
        
        # Phase 2: LLM extraction for complex relationships
        llm_result = await self._extract_with_llm(document_text, regex_entities)
        
        # Phase 3: Merge and deduplicate
        merged = self._merge_extractions(regex_entities, llm_result)
        
        return merged
    
    def _extract_regex_patterns(self, text: str) -> List[ExtractedEntity]:
        """Extract entities using regex patterns."""
        entities = []
        
        for doc_type, patterns in self.DOC_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    # Normalize ID
                    normalized_id = self._normalize_id(doc_type, match.groups())
                    entities.append(ExtractedEntity(
                        id=normalized_id,
                        type=doc_type,
                        name=match.group(0).strip(),
                        properties={'matched_pattern': pattern},
                        source_text=match.group(0),
                        confidence=0.9
                    ))
        
        return entities
    
    def _normalize_id(self, doc_type: str, groups: tuple) -> str:
        """Normalize document ID to canonical format."""
        if doc_type == 'acordao':
            num, year = groups[:2]
            year_full = year if len(year) == 4 else f"20{year}"
            return f"AC-{int(num):05d}-{year_full}"
        elif doc_type == 'sumula':
            return f"STCU-{int(groups[0]):03d}"
        elif doc_type == 'normativo':
            tipo, num, year = groups
            tipo_map = {'IN': 'IN', 'Port.': 'PORT', 'Portaria': 'PORT', 
                       'Res.': 'RES', 'Resolução': 'RES'}
            return f"{tipo_map.get(tipo, tipo)}-{int(num):04d}-{year}"
        return f"{doc_type}-{'-'.join(groups)}"
    
    async def _extract_with_llm(
        self, 
        text: str, 
        known_entities: List[ExtractedEntity]
    ) -> Dict[str, Any]:
        """Use LLM to extract relationships and additional entities."""
        
        # Truncate text if too long
        max_chars = 15000
        truncated_text = text[:max_chars] if len(text) > max_chars else text
        
        # Build entity context from regex extraction
        entity_context = "\n".join([
            f"- {e.type}: {e.name} (ID: {e.id})" 
            for e in known_entities[:50]  # Limit context
        ])
        
        prompt = f"""Você é um assistente especializado em extrair informações de documentos jurídicos do TCU (Tribunal de Contas da União).

Analise o texto abaixo e extraia:
1. Entidades mencionadas (ministros, órgãos, processos, temas)
2. Relações entre documentos (citações, revogações, divergências)

ENTIDADES JÁ IDENTIFICADAS (use estes IDs):
{entity_context}

TEXTO DO DOCUMENTO:
---
{truncated_text}
---

Retorne APENAS um JSON válido com o seguinte formato:
{{
    "entities": [
        {{
            "id": "identificador-unico",
            "type": "Ministro|Orgao|Processo|Tema|Entidade",
            "name": "Nome completo",
            "properties": {{}},
            "source_text": "trecho onde aparece"
        }}
    ],
    "relations": [
        {{
            "source_id": "id-origem",
            "target_id": "id-destino",
            "relation_type": "CITA|REVOGA|MODIFICA|FUNDAMENTA|DIVERGE|CONCORDA|RELATADO_POR|TRATA_DE",
            "properties": {{}},
            "source_text": "trecho evidenciando a relação"
        }}
    ]
}}

Regras importantes:
- Para citações: identifique se é citação positiva, negativa ou neutra
- Para divergências: capture o trecho específico que demonstra a divergência
- Para ministros: identifique se é relator, redator ou votante
- Normalize nomes de ministros para formato padrão
- Identifique órgãos colegiados (1ª Câmara, 2ª Câmara, Plenário)
"""
        
        response = await self.llm_client.complete(prompt)
        
        try:
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except json.JSONDecodeError:
            pass
        
        return {"entities": [], "relations": []}
    
    def _merge_extractions(
        self, 
        regex_entities: List[ExtractedEntity], 
        llm_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Merge regex and LLM extractions, removing duplicates."""
        
        # Convert to dictionaries
        all_entities = {}
        
        # Add regex entities
        for e in regex_entities:
            all_entities[e.id] = {
                'id': e.id,
                'type': e.type,
                'name': e.name,
                'properties': e.properties,
                'source_text': e.source_text,
                'confidence': e.confidence
            }
        
        # Add LLM entities
        for e in llm_result.get('entities', []):
            entity_id = e.get('id', '').upper().replace(' ', '-')
            if entity_id and entity_id not in all_entities:
                all_entities[entity_id] = {
                    **e,
                    'confidence': 0.7  # LLM confidence lower than regex
                }
        
        # Deduplicate relations
        seen_relations = set()
        unique_relations = []
        
        for r in llm_result.get('relations', []):
            rel_key = (r.get('source_id'), r.get('target_id'), r.get('relation_type'))
            if rel_key not in seen_relations:
                seen_relations.add(rel_key)
                unique_relations.append(r)
        
        return {
            'entities': list(all_entities.values()),
            'relations': unique_relations
        }
```

### 2.2 Extraction Prompts

```python
# src/gabi/graphrag/prompts.py

CITATION_EXTRACTION_PROMPT = """
Você é um sistema especializado em identificar citações jurídicas em textos do TCU.

Contexto: O documento abaixo é um {doc_type} do TCU. Identifique todas as citações a outros documentos.

Texto para análise:
{text}

Para cada citação encontrada, extraia:
1. Tipo do documento citado (acórdão, súmula, normativo, lei, doutrina)
2. Identificador normalizado
3. Contexto da citação (positiva/negativa/neutra)
4. Trecho específico que contém a citação

Retorne em formato JSON:
{{
    "citations": [
        {{
            "cited_doc_type": "acordao|sumula|normativo|lei|doutrina",
            "cited_doc_id": "identificador-normalizado",
            "context": "positiva|negativa|neutra",
            "quotation_text": "trecho exato da citação",
            "page": número_da_página
        }}
    ]
}}

Exemplos de identificadores normalizados:
- "Acórdão 1234/2023" → "AC-01234-2023"
- "Súmula TCU 247" → "STCU-247"
- "IN 75/2022" → "IN-0075-2022"
- "Lei 8.666/1993" → "LEI-8666-1993"
"""

PRECEDENT_RELATION_PROMPT = """
Analise o texto deste acórdão do TCU e identifique relações de precedentes jurisprudenciais.

Texto:
{text}

Identifique:
1. **Segue**: O acórdão segue/simula precedente anterior
2. **Diverge**: O acórdão diverge/modifica entendimento anterior
3. **Distingue**: O acórdão distingue a situação de precedente anterior
4. **Supera**: O acórdão supera/modifica súmula ou orientação

Retorne JSON:
{{
    "precedent_relations": [
        {{
            "relation_type": "segue|diverge|distingue|supera",
            "target_doc_id": "identificador-do-precedente",
            "target_doc_type": "acordao|sumula|orientacao",
            "reasoning": "fundamentação para a relação",
            "quotation": "trecho do texto"
        }}
    ]
}}
"""

NORMATIVE_CHAIN_PROMPT = """
Analise este normativo do TCU e identifique a cadeia normativa.

Texto:
{text}

Identifique:
1. **Revoga**: Documentos que este normativo revoga total ou parcialmente
2. **Altera**: Documentos que este normativo altera/modifica
3. **Regulamenta**: Leis ou normas superiores que este documento regulamenta
4. **É_Revogado_Por**: Se mencionado, qual documento revogou este
5. **É_Alterado_Por**: Se mencionado, qual documento alterou este

Retorne JSON:
{{
    "normative_relations": [
        {{
            "relation_type": "revoga|altera|regulamenta|e_revogado_por|e_alterado_por",
            "target_doc_id": "identificador-normalizado",
            "scope": "total|parcial",
            "articles": ["artigo_1", "artigo_2"],  // se parcial
            "quotation": "trecho do texto"
        }}
    ]
}}
"""

MINISTER_IDENTIFICATION_PROMPT = """
Identifique os ministros e suas funções neste acórdão.

Texto:
{text}

Identifique:
1. Relator (responsável pelo voto de relatoria)
2. Redator (se diferente do relator)
3. Ministros que votaram com o relator
4. Ministros que divergiram
5. Ministros que se abstiveram ou se declararam suspeitos

Retorne JSON:
{{
    "ministros": [
        {{
            "name": "nome_completo",
            "normalized_name": "SOBRENOME_Nome",
            "role": "relator|redator|votante|dissidente|abstencao",
            "vote_position": "acompanhou_relator|divergiu|voto_vista"
        }}
    ],
    "orgao_julgador": "1a_Camara|2a_Camara|Plenario"
}}
"""
```

## 3. Graph Construction Pipeline

### 3.1 Pipeline Integration

```python
# src/gabi/graphrag/pipeline.py

from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio
import logging

from neo4j import AsyncGraphDatabase

from gabi.graphrag.extractor import LegalEntityExtractor, ExtractedEntity, ExtractedRelation
from gabi.models.document import Document

logger = logging.getLogger(__name__)


@dataclass
class GraphUpdateResult:
    """Result of graph update operation."""
    document_id: str
    nodes_created: int
    nodes_updated: int
    relationships_created: int
    relationships_updated: int
    errors: List[str]
    duration_ms: float


class GraphConstructionPipeline:
    """Pipeline for constructing and updating the knowledge graph."""
    
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        extractor: Optional[LegalEntityExtractor] = None
    ):
        self.driver = AsyncGraphDatabase.driver(
            neo4j_uri, 
            auth=(neo4j_user, neo4j_password)
        )
        self.extractor = extractor
    
    async def process_document(
        self, 
        document: Document,
        chunks: List[Any]
    ) -> GraphUpdateResult:
        """Process a document and update the graph.
        
        This is called from the main ingestion pipeline.
        """
        start_time = datetime.now()
        errors = []
        
        try:
            # Combine chunks into full text
            full_text = "\n\n".join([c.chunk_text for c in chunks])
            
            # Extract entities and relations
            extraction = await self.extractor.extract(
                document_text=full_text,
                metadata={
                    'document_id': document.document_id,
                    'source_id': document.source_id,
                    'title': document.title,
                }
            )
            
            # Merge with document metadata
            entities = self._enrich_with_document_metadata(
                extraction['entities'], 
                document
            )
            relations = extraction['relations']
            
            # Update graph
            async with self.driver.session() as session:
                result = await session.execute_write(
                    self._merge_document_subgraph,
                    document_id=document.document_id,
                    pg_id=str(document.id),
                    entities=entities,
                    relations=relations,
                    doc_metadata={
                        'title': document.title,
                        'source_id': document.source_id,
                        'ingested_at': document.ingested_at.isoformat(),
                    }
                )
            
            duration = (datetime.now() - start_time).total_seconds() * 1000
            
            return GraphUpdateResult(
                document_id=document.document_id,
                nodes_created=result['nodes_created'],
                nodes_updated=result['nodes_updated'],
                relationships_created=result['relationships_created'],
                relationships_updated=result['relationships_updated'],
                errors=errors,
                duration_ms=duration
            )
            
        except Exception as e:
            logger.exception(f"Failed to process document {document.document_id}")
            duration = (datetime.now() - start_time).total_seconds() * 1000
            return GraphUpdateResult(
                document_id=document.document_id,
                nodes_created=0,
                nodes_updated=0,
                relationships_created=0,
                relationships_updated=0,
                errors=[str(e)],
                duration_ms=duration
            )
    
    def _enrich_with_document_metadata(
        self, 
        entities: List[Dict],
        document: Document
    ) -> List[Dict]:
        """Enrich extracted entities with document metadata."""
        # Add document as entity if not present
        doc_entity = {
            'id': document.document_id,
            'type': 'Document',
            'name': document.title or document.document_id,
            'properties': {
                'pg_id': str(document.id),
                'source_id': document.source_id,
                'fingerprint': document.fingerprint,
            },
            'confidence': 1.0
        }
        
        # Add metadata entities
        metadata_entities = []
        
        if document.doc_metadata:
            meta = document.doc_metadata
            
            # Add relator as entity
            if relator := meta.get('relator'):
                metadata_entities.append({
                    'id': self._normalize_minister_name(relator),
                    'type': 'Ministro',
                    'name': relator,
                    'properties': {},
                    'confidence': 1.0
                })
            
            # Add processo
            if processo := meta.get('processo'):
                metadata_entities.append({
                    'id': str(processo).replace('/', '-'),
                    'type': 'Processo',
                    'name': f"Processo {processo}",
                    'properties': {'numero': processo},
                    'confidence': 1.0
                })
        
        return [doc_entity] + entities + metadata_entities
    
    def _normalize_minister_name(self, name: str) -> str:
        """Normalize minister name to ID."""
        # Extract last name and first initial
        parts = name.strip().upper().split()
        if len(parts) >= 2:
            return f"{parts[-1]}_{parts[0][0]}"
        return name.upper().replace(' ', '_')
    
    @staticmethod
    async def _merge_document_subgraph(
        tx,
        document_id: str,
        pg_id: str,
        entities: List[Dict],
        relations: List[Dict],
        doc_metadata: Dict
    ) -> Dict[str, int]:
        """Cypher transaction to merge document subgraph."""
        
        stats = {
            'nodes_created': 0,
            'nodes_updated': 0,
            'relationships_created': 0,
            'relationships_updated': 0
        }
        
        # Merge Document node
        doc_result = await tx.run("""
            MERGE (d:Document {document_id: $doc_id})
            ON CREATE SET 
                d.pg_id = $pg_id,
                d.title = $title,
                d.source_id = $source_id,
                d.created_at = datetime(),
                d.updated_at = datetime()
            ON MATCH SET
                d.updated_at = datetime()
            RETURN d
        """, {
            'doc_id': document_id,
            'pg_id': pg_id,
            'title': doc_metadata.get('title'),
            'source_id': doc_metadata.get('source_id'),
        })
        
        # Merge other entities
        for entity in entities:
            if entity['type'] == 'Document':
                continue  # Already merged
            
            await tx.run("""
                MERGE (e {id: $id})
                ON CREATE SET 
                    e:$label,
                    e.name = $name,
                    e.properties = $props,
                    e.created_at = datetime()
                ON MATCH SET
                    e.name = $name,
                    e.properties = apoc.map.merge(e.properties, $props),
                    e.updated_at = datetime()
            """, {
                'id': entity['id'],
                'label': entity['type'],
                'name': entity['name'],
                'props': entity.get('properties', {})
            })
            stats['nodes_created'] += 1
        
        # Merge relationships
        for rel in relations:
            rel_type = rel['relation_type'].upper()
            
            await tx.run(f"""
                MATCH (a {{id: $source_id}})
                MATCH (b {{id: $target_id}})
                MERGE (a)-[r:{rel_type}]->(b)
                ON CREATE SET
                    r.properties = $props,
                    r.source_text = $source_text,
                    r.created_at = datetime()
                ON MATCH SET
                    r.properties = apoc.map.merge(r.properties, $props),
                    r.updated_at = datetime()
            """, {
                'source_id': rel['source_id'],
                'target_id': rel['target_id'],
                'props': rel.get('properties', {}),
                'source_text': rel.get('source_text', '')
            })
            stats['relationships_created'] += 1
        
        return stats
    
    async def delete_document(self, document_id: str) -> bool:
        """Remove a document and its relationships from the graph.
        
        Called when document is soft-deleted or hard-deleted.
        """
        async with self.driver.session() as session:
            result = await session.run("""
                MATCH (d:Document {document_id: $doc_id})
                OPTIONAL MATCH (d)-[r]-()
                DELETE r, d
                RETURN count(r) as rels_deleted, count(d) as docs_deleted
            """, {'doc_id': document_id})
            
            record = await result.single()
            return record['docs_deleted'] > 0
    
    async def close(self):
        await self.driver.close()
```

### 3.2 Integration with Existing Pipeline

```python
# src/gabi/pipeline/orchestrator.py (modifications)

# Add new phase to PipelinePhase enum
class PipelinePhase(str, Enum):
    """Fases do pipeline."""
    DISCOVERY = "discovery"
    CHANGE_DETECTION = "change_detection"
    FETCH = "fetch"
    PARSE = "parse"
    FINGERPRINT = "fingerprint"
    DEDUPLICATION = "deduplication"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    GRAPH_EXTRACTION = "graph_extraction"  # NEW
    GRAPH_INDEXING = "graph_indexing"      # NEW


# In PipelineOrchestrator.__init__, add graph components
@property
def graph_pipeline(self) -> Any:
    """Lazy init do graph pipeline."""
    if self._graph_pipeline is None:
        from gabi.graphrag.pipeline import GraphConstructionPipeline
        self._graph_pipeline = GraphConstructionPipeline(
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password.get_secret_value(),
        )
    return self._graph_pipeline


# In _processing_phase, add graph steps
async def _processing_phase(...):
    # ... existing code ...
    
    for chunk_data in chunks:
        # ... existing chunk processing ...
        
        # Phase 10: Graph Extraction & Indexing
        if self.config.enable_graph:
            try:
                graph_result = await self.graph_pipeline.process_document(
                    document=persistent_doc,
                    chunks=embedded_chunks
                )
                stats['graph_nodes_created'] = graph_result.nodes_created
                stats['graph_rels_created'] = graph_result.relationships_created
            except Exception as e:
                logger.warning(f"Graph processing failed for {document_id}: {e}")
                # Don't fail the entire pipeline for graph errors
```

## 4. Query-Time Graph Traversal

### 4.1 GraphRAG Search Service

```python
# src/gabi/graphrag/search.py

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import asyncio

from neo4j import AsyncGraphDatabase


@dataclass
class GraphSearchResult:
    """Result from graph-aware search."""
    document_id: str
    title: str
    score: float
    graph_score: float
    citation_chain: List[Dict[str, Any]]
    related_documents: List[Dict[str, Any]]
    conflicting_precedents: List[Dict[str, Any]]
    normative_chain: Optional[Dict[str, Any]]


class GraphRAGSearchService:
    """Graph-aware search service for legal documents."""
    
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        base_search_service: Any,  # Existing SearchService
    ):
        self.driver = AsyncGraphDatabase.driver(
            neo4j_uri, 
            auth=(neo4j_user, neo4j_password)
        )
        self.base_search = base_search_service
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        graph_depth: int = 2,
        include_citations: bool = True,
        include_conflicts: bool = True,
        include_normative_chain: bool = True,
    ) -> Dict[str, Any]:
        """Execute graph-aware search.
        
        Args:
            query: Search query
            limit: Max results to return
            graph_depth: How many hops to traverse
            include_citations: Include citation network
            include_conflicts: Include conflicting precedents
            include_normative_chain: Include normative relationships
        """
        # Phase 1: Base semantic search
        base_results = await self.base_search.search_api(query, limit=limit * 2)
        
        # Phase 2: Enhance with graph context
        enriched_results = []
        
        for hit in base_results.hits:
            graph_context = await self._get_graph_context(
                document_id=hit.document_id,
                depth=graph_depth,
                include_citations=include_citations,
                include_conflicts=include_conflicts,
                include_normative_chain=include_normative_chain,
            )
            
            # Calculate graph-boosted score
            graph_score = self._calculate_graph_score(hit, graph_context)
            
            enriched_results.append(GraphSearchResult(
                document_id=hit.document_id,
                title=hit.title or "",
                score=hit.score,
                graph_score=graph_score,
                citation_chain=graph_context.get('citations', []),
                related_documents=graph_context.get('related', []),
                conflicting_precedents=graph_context.get('conflicts', []),
                normative_chain=graph_context.get('normative_chain'),
            ))
        
        # Re-rank by combined score
        enriched_results.sort(key=lambda x: x.graph_score, reverse=True)
        
        return {
            'query': query,
            'total': len(enriched_results),
            'hits': enriched_results[:limit],
        }
    
    async def _get_graph_context(
        self,
        document_id: str,
        depth: int,
        include_citations: bool,
        include_conflicts: bool,
        include_normative_chain: bool,
    ) -> Dict[str, Any]:
        """Get graph context for a document."""
        context = {}
        
        async with self.driver.session() as session:
            # Citations (both directions)
            if include_citations:
                citations = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})
                    OPTIONAL MATCH (d)-[r:CITA]->(cited:Document)
                    OPTIONAL MATCH (citing:Document)-[r2:CITA]->(d)
                    RETURN {
                        cited: collect(DISTINCT {
                            doc_id: cited.document_id,
                            title: cited.title,
                            context: r.context,
                            confidence: r.confidence
                        }),
                        cited_by: collect(DISTINCT {
                            doc_id: citing.document_id,
                            title: citing.title,
                            context: r2.context,
                            confidence: r2.confidence
                        })
                    } as citations
                """, {'doc_id': document_id})
                
                record = await citations.single()
                context['citations'] = record['citations'] if record else {}
            
            # Conflicting precedents
            if include_conflicts:
                conflicts = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})
                    OPTIONAL MATCH (d)-[:DIVERGES]->(conflict:Document)
                    OPTIONAL MATCH (divergent:Document)-[:DIVERGES]->(d)
                    RETURN collect(DISTINCT {
                        doc_id: coalesce(conflict.document_id, divergent.document_id),
                        title: coalesce(conflict.title, divergent.title),
                        direction: CASE WHEN conflict IS NOT NULL THEN 'outgoing' ELSE 'incoming' END
                    }) as conflicts
                """, {'doc_id': document_id})
                
                record = await conflicts.single()
                context['conflicts'] = record['conflicts'] if record else []
            
            # Normative chain
            if include_normative_chain:
                normative = await session.run("""
                    MATCH (d:Document {document_id: $doc_id})
                    OPTIONAL MATCH chain = (d)-[:REVOGA|MODIFICA*1..5]->(target)
                    WITH d, chain, target
                    ORDER BY length(chain) DESC
                    LIMIT 1
                    RETURN {
                        chain: [node in nodes(chain) | node.document_id],
                        relationships: [rel in relationships(chain) | type(rel)]
                    } as normative_chain
                """, {'doc_id': document_id})
                
                record = await normative.single()
                context['normative_chain'] = record['normative_chain'] if record else None
            
            # Related documents (semantic + graph proximity)
            related = await session.run("""
                MATCH (d:Document {document_id: $doc_id})
                MATCH (d)-[:CITA|FUNDAMENTA|TRATA_DE*1..2]-(related:Document)
                WHERE related.document_id <> d.document_id
                WITH related, count(*) as connection_strength
                ORDER BY connection_strength DESC
                LIMIT 5
                RETURN collect({
                    doc_id: related.document_id,
                    title: related.title,
                    strength: connection_strength
                }) as related
            """, {'doc_id': document_id})
            
            record = await related.single()
            context['related'] = record['related'] if record else []
        
        return context
    
    def _calculate_graph_score(
        self, 
        base_hit: Any, 
        graph_context: Dict[str, Any]
    ) -> float:
        """Calculate graph-boosted relevance score."""
        base_score = base_hit.score
        
        # Boost factors
        citation_boost = 0
        authority_boost = 0
        
        # Boost by citation count
        citations = graph_context.get('citations', {})
        cited_by_count = len(citations.get('cited_by', []))
        citation_boost = min(cited_by_count * 0.05, 0.5)  # Max 0.5 boost
        
        # Boost by authority (documents cited by high-authority documents)
        for citing in citations.get('cited_by', []):
            # Could use PageRank here
            authority_boost += 0.02
        authority_boost = min(authority_boost, 0.3)
        
        # Penalize documents with many conflicts
        conflicts = graph_context.get('conflicts', [])
        conflict_penalty = len(conflicts) * 0.05
        
        return base_score + citation_boost + authority_boost - conflict_penalty
    
    async def find_precedent_chain(
        self,
        document_id: str,
        direction: str = 'both',  # 'forward', 'backward', 'both'
        max_depth: int = 5
    ) -> List[Dict[str, Any]]:
        """Find chain of precedents related to a document.
        
        Args:
            document_id: Starting document
            direction: Search direction
            max_depth: Maximum traversal depth
        """
        async with self.driver.session() as session:
            if direction == 'backward':
                # Documents this one cites
                result = await session.run("""
                    MATCH path = (d:Document {document_id: $doc_id})
                              -[:CITA|FUNDAMENTA*1..%d]->(prec:Document)
                    RETURN [node in nodes(path) | {
                        doc_id: node.document_id,
                        title: node.title
                    }] as chain
                    ORDER BY length(path) ASC
                """ % max_depth, {'doc_id': document_id})
            
            elif direction == 'forward':
                # Documents citing this one
                result = await session.run("""
                    MATCH path = (prec:Document)
                              -[:CITA|FUNDAMENTA*1..%d]->
                              (d:Document {document_id: $doc_id})
                    RETURN [node in nodes(path) | {
                        doc_id: node.document_id,
                        title: node.title
                    }] as chain
                    ORDER BY length(path) ASC
                """ % max_depth, {'doc_id': document_id})
            
            else:  # both
                result = await session.run("""
                    MATCH path = (a:Document)-[:CITA|FUNDAMENTA*1..%d]-(b:Document)
                    WHERE a.document_id = $doc_id OR b.document_id = $doc_id
                    RETURN [node in nodes(path) | {
                        doc_id: node.document_id,
                        title: node.title
                    }] as chain
                    ORDER BY length(path) ASC
                """ % max_depth, {'doc_id': document_id})
            
            chains = []
            async for record in result:
                chains.append(record['chain'])
            
            return chains
    
    async def find_normative_evolution(
        self,
        normative_id: str
    ) -> Dict[str, Any]:
        """Trace the evolution of a normative document."""
        async with self.driver.session() as session:
            # Find what this normative revokes/modifies
            result = await session.run("""
                MATCH (n:Normativo {numero: $norm_id})
                OPTIONAL MATCH (n)-[:REVOGA]->(revoked:Normativo)
                OPTIONAL MATCH (n)-[:MODIFICA]->(modified:Normativo)
                OPTIONAL MATCH (revoked_by:Normativo)-[:REVOGA]->(n)
                OPTIONAL MATCH (modified_by:Normativo)-[:MODIFICA]->(n)
                RETURN {
                    revokes: collect(DISTINCT revoked.numero),
                    modifies: collect(DISTINCT modified.numero),
                    revoked_by: collect(DISTINCT revoked_by.numero),
                    modified_by: collect(DISTINCT modified_by.numero),
                    current_status: CASE 
                        WHEN size(collect(revoked_by)) > 0 THEN 'revoked'
                        WHEN size(collect(modified_by)) > 0 THEN 'modified'
                        ELSE 'active'
                    END
                } as evolution
            """, {'norm_id': normative_id})
            
            record = await result.single()
            return record['evolution'] if record else {}
    
    async def close(self):
        await self.driver.close()
```

## 5. Cypher Query Examples

### 5.1 Common Use Cases

```cypher
// ============================================
// UC1: Find all documents citing a specific sumula
// ============================================
MATCH (s:Sumula {numero: 247})<-[:CITA]-(d:Document)
RETURN d.document_id, d.title, d.date
ORDER BY d.date DESC

// ============================================
// UC2: Find citation network around a document
// ============================================
MATCH (center:Document {document_id: "AC-01234-2024"})
OPTIONAL MATCH (center)-[:CITA]->(cited:Document)
OPTIONAL MATCH (citing:Document)-[:CITA]->(center)
OPTIONAL MATCH (center)-[:FUNDAMENTA]->(funded:Document)
RETURN center.document_id as main_doc,
       collect(DISTINCT {type: 'cited', id: cited.document_id, title: cited.title}) as cited_docs,
       collect(DISTINCT {type: 'citing', id: citing.document_id, title: citing.title}) as citing_docs,
       collect(DISTINCT {type: 'funded', id: funded.document_id, title: funded.title}) as funded_docs

// ============================================
// UC3: Find conflicting precedents on a topic
// ============================================
MATCH (d1:Document)-[:DIVERGE]->(d2:Document)
WHERE d1.date > d2.date  // d1 is newer
RETURN d1.document_id as newer_doc,
       d1.title as newer_title,
       d2.document_id as older_doc,
       d2.title as older_title,
       d1.date as divergence_date
ORDER BY d1.date DESC

// ============================================
// UC4: Trace normative chain
// ============================================
MATCH path = (latest:Normativo)-[:REVOGA|MODIFICA*1..10]->(oldest:Normativo)
WHERE latest.numero = "IN-0075-2022"
RETURN [n in nodes(path) | {tipo: n.tipo, numero: n.numero, ano: n.ano}] as chain,
       [r in relationships(path) | type(r)] as operations

// ============================================
// UC5: Find jurisprudence by minister
// ============================================
MATCH (m:Ministro)-[:RELATADO_POR]-(d:Document)
WHERE m.name CONTAINS "Mendonça"
RETURN d.document_id, d.title, d.date
ORDER BY d.date DESC
LIMIT 20

// ============================================
// UC6: Topic-based search with graph expansion
// ============================================
// Find documents about "licitação", then expand to related docs
MATCH (d:Document)
WHERE d.ementa CONTAINS "licitação" OR d.title CONTAINS "licitação"
WITH d LIMIT 10
MATCH (d)-[:CITA|TRATA_DE*1..2]-(related:Document)
RETURN d.document_id as source,
       collect(DISTINCT related.document_id) as related_docs,
       count(DISTINCT related) as related_count
ORDER BY related_count DESC

// ============================================
// UC7: PageRank for document authority
// ============================================
CALL gds.pageRank.stream('document-graph')
YIELD nodeId, score
RETURN gds.util.asNode(nodeId).document_id as doc_id,
       gds.util.asNode(nodeId).title as title,
       score as authority
ORDER BY score DESC
LIMIT 20

// ============================================
// UC8: Shortest path between two documents
// ============================================
MATCH (start:Document {document_id: "AC-01000-2020"}),
      (end:Document {document_id: "AC-02000-2024"})
MATCH path = shortestPath((start)-[:CITA|FUNDAMENTA*]-(end))
RETURN [n in nodes(path) | n.document_id] as path_nodes,
       length(path) as hops

// ============================================
// UC9: Find orphaned documents (no citations)
// ============================================
MATCH (d:Document)
WHERE NOT (d)-[:CITA]->() AND NOT ()-[:CITA]->(d)
RETURN d.document_id, d.title, d.date
ORDER BY d.date DESC
LIMIT 50

// ============================================
// UC10: Cluster analysis by citation patterns
// ============================================
CALL gds.louvain.stream('document-graph')
YIELD nodeId, communityId
RETURN communityId,
       count(*) as doc_count,
       collect(gds.util.asNode(nodeId).document_id)[0..5] as sample_docs
ORDER BY doc_count DESC
```

## 6. Performance Considerations

### 6.1 Neo4j Configuration

```yaml
# docker-compose.yml additions
services:
  neo4j:
    image: neo4j:5.15-enterprise
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc", "gds"]  # Graph Data Science
      - NEO4J_dbms_memory_heap_initial__size=4G
      - NEO4J_dbms_memory_heap_max__size=8G
      - NEO4J_dbms_memory_pagecache_size=4G
      - NEO4J_dbms_security_procedures_unrestricted=apoc.*,gds.*
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
```

### 6.2 Indexing Strategy

```cypher
// Create indexes for common queries
CREATE INDEX document_id_idx FOR (d:Document) ON (d.document_id);
CREATE INDEX document_date_idx FOR (d:Document) ON (d.date);
CREATE INDEX document_source_idx FOR (d:Document) ON (d.source_id);
CREATE INDEX document_type_idx FOR (d:Document) ON (d.doc_type);

CREATE INDEX ministro_name_idx FOR (m:Ministro) ON (m.name);
CREATE INDEX processo_numero_idx FOR (p:Processo) ON (p.numero);
CREATE INDEX normativo_numero_idx FOR (n:Normativo) ON (n.numero);
CREATE INDEX sumula_numero_idx FOR (s:Sumula) ON (s.numero);

// Full-text index for ementa search
CALL db.index.fulltext.createNodeIndex("documentText", ["Document"], ["title", "ementa", "content_preview"]);

// GDS Graph Projection for algorithms
CALL gds.graph.project(
    'document-graph',
    'Document',
    ['CITA', 'FUNDAMENTA'],
    { relationshipProperties: 'weight' }
);
```

### 6.3 Caching Strategy

```python
# src/gabi/graphrag/cache.py

import hashlib
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import redis.asyncio as redis


class GraphCache:
    """Cache for graph query results."""
    
    def __init__(self, redis_client: redis.Redis, ttl_seconds: int = 3600):
        self.redis = redis_client
        self.ttl = ttl_seconds
    
    def _make_key(self, query_type: str, params: Dict[str, Any]) -> str:
        """Generate cache key from query parameters."""
        param_str = json.dumps(params, sort_keys=True)
        hash_val = hashlib.sha256(param_str.encode()).hexdigest()[:16]
        return f"graph:{query_type}:{hash_val}"
    
    async def get(
        self, 
        query_type: str, 
        params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get cached result."""
        key = self._make_key(query_type, params)
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    async def set(
        self, 
        query_type: str, 
        params: Dict[str, Any], 
        result: Dict[str, Any]
    ):
        """Cache result."""
        key = self._make_key(query_type, params)
        await self.redis.setex(
            key,
            self.ttl,
            json.dumps(result, default=str)
        )
    
    async def invalidate_document(self, document_id: str):
        """Invalidate cache entries for a document."""
        # Pattern matching for invalidation
        pattern = f"graph:*:{document_id}:*"
        keys = await self.redis.keys(pattern)
        if keys:
            await self.redis.delete(*keys)
```

### 6.4 Query Optimization

```python
# src/gabi/graphrag/optimizations.py

class QueryOptimizer:
    """Optimize graph queries based on access patterns."""
    
    @staticmethod
    def estimate_cardinality(
        driver,
        label: str,
        property_name: str,
        property_value: Any
    ) -> int:
        """Estimate result cardinality for query planning."""
        # Use database statistics
        pass
    
    @staticmethod
    def rewrite_traversal(
        start_label: str,
        relationship_types: List[str],
        depth: int
    ) -> str:
        """Rewrite traversal for optimal performance."""
        # Use APOC path expander for variable-length paths
        if depth > 3:
            return f"""
                CALL apoc.path.expandConfig(start, {{
                    relationshipFilter: "{'|'.join(relationship_types)}",
                    minLevel: 1,
                    maxLevel: {depth}
                }}) YIELD path
                RETURN path
            """
        return f"""
            MATCH path = (start)-[:{'|'.join(relationship_types)}*1..{depth}]-(end)
            RETURN path
        """
```

## 7. Incremental Update Strategy

### 7.1 Change Detection

```python
# src/gabi/graphrag/changes.py

from dataclasses import dataclass
from typing import List, Set
from datetime import datetime


@dataclass
class GraphChangeSet:
    """Changes detected in document."""
    document_id: str
    nodes_to_add: List[Dict]
    nodes_to_update: List[Dict]
    nodes_to_remove: List[str]
    relations_to_add: List[Dict]
    relations_to_remove: List[Tuple[str, str, str]]  # (source, target, type)
    timestamp: datetime


class IncrementalGraphUpdater:
    """Handle incremental updates to the graph."""
    
    async def detect_changes(
        self,
        document_id: str,
        new_extraction: Dict[str, Any]
    ) -> GraphChangeSet:
        """Detect changes between existing graph and new extraction."""
        # Get current state from graph
        current = await self._get_current_state(document_id)
        
        # Compare with new extraction
        new_entities = {e['id']: e for e in new_extraction['entities']}
        new_relations = {
            (r['source_id'], r['target_id'], r['relation_type']): r 
            for r in new_extraction['relations']
        }
        
        current_entities = {e['id']: e for e in current['entities']}
        current_relations = {
            (r['source_id'], r['target_id'], r['relation_type']): r 
            for r in current['relations']
        }
        
        # Calculate diffs
        nodes_to_add = [
            new_entities[eid] 
            for eid in new_entities.keys() - current_entities.keys()
        ]
        nodes_to_update = [
            new_entities[eid]
            for eid in new_entities.keys() & current_entities.keys()
            if new_entities[eid] != current_entities[eid]
        ]
        nodes_to_remove = list(current_entities.keys() - new_entities.keys())
        
        relations_to_add = [
            new_relations[rkey]
            for rkey in new_relations.keys() - current_relations.keys()
        ]
        relations_to_remove = list(
            current_relations.keys() - new_relations.keys()
        )
        
        return GraphChangeSet(
            document_id=document_id,
            nodes_to_add=nodes_to_add,
            nodes_to_update=nodes_to_update,
            nodes_to_remove=nodes_to_remove,
            relations_to_add=relations_to_add,
            relations_to_remove=relations_to_remove,
            timestamp=datetime.now()
        )
    
    async def apply_changes(self, changes: GraphChangeSet):
        """Apply detected changes to the graph."""
        async with self.driver.session() as session:
            # Remove old relationships
            for source, target, rel_type in changes.relations_to_remove:
                await session.run(f"""
                    MATCH (a {{id: $source}})-[r:{rel_type}]->(b {{id: $target}})
                    DELETE r
                """, {'source': source, 'target': target})
            
            # Remove old nodes
            for node_id in changes.nodes_to_remove:
                await session.run("""
                    MATCH (n {id: $id})
                    DETACH DELETE n
                """, {'id': node_id})
            
            # Add new nodes
            for node in changes.nodes_to_add:
                await session.run("""
                    CREATE (n:$label {id: $id, name: $name})
                    SET n.properties = $props
                """, {
                    'label': node['type'],
                    'id': node['id'],
                    'name': node['name'],
                    'props': node.get('properties', {})
                })
            
            # Update existing nodes
            for node in changes.nodes_to_update:
                await session.run("""
                    MATCH (n {id: $id})
                    SET n.name = $name,
                        n.properties = apoc.map.merge(n.properties, $props),
                        n.updated_at = datetime()
                """, {
                    'id': node['id'],
                    'name': node['name'],
                    'props': node.get('properties', {})
                })
            
            # Add new relationships
            for rel in changes.relations_to_add:
                rel_type = rel['relation_type'].upper()
                await session.run(f"""
                    MATCH (a {{id: $source}})
                    MATCH (b {{id: $target}})
                    CREATE (a)-[r:{rel_type}]->(b)
                    SET r.properties = $props
                """, {
                    'source': rel['source_id'],
                    'target': rel['target_id'],
                    'props': rel.get('properties', {})
                })
```

### 7.2 Batch Processing

```python
# src/gabi/graphrag/batch.py

class BatchGraphProcessor:
    """Process documents in batches for initial graph construction."""
    
    def __init__(self, batch_size: int = 100):
        self.batch_size = batch_size
    
    async def process_batch(
        self,
        documents: List[Document],
        chunks_map: Dict[str, List[Any]]
    ) -> Dict[str, Any]:
        """Process a batch of documents efficiently."""
        results = {
            'processed': 0,
            'nodes_created': 0,
            'relationships_created': 0,
            'errors': []
        }
        
        # Use UNWIND for efficient bulk operations
        async with self.driver.session() as session:
            # Build batch data
            batch_data = []
            for doc in documents:
                chunks = chunks_map.get(doc.document_id, [])
                full_text = "\n\n".join([c.chunk_text for c in chunks])
                
                extraction = await self.extractor.extract(
                    document_text=full_text,
                    metadata={'document_id': doc.document_id}
                )
                
                batch_data.append({
                    'doc_id': doc.document_id,
                    'pg_id': str(doc.id),
                    'title': doc.title,
                    'entities': extraction['entities'],
                    'relations': extraction['relations']
                })
            
            # Bulk insert using UNWIND
            await session.run("""
                UNWIND $batch as item
                MERGE (d:Document {document_id: item.doc_id})
                ON CREATE SET 
                    d.pg_id = item.pg_id,
                    d.title = item.title,
                    d.created_at = datetime()
            """, {'batch': batch_data})
            
            # Insert entities
            all_entities = []
            for item in batch_data:
                for entity in item['entities']:
                    if entity['type'] != 'Document':
                        all_entities.append({
                            'doc_id': item['doc_id'],
                            **entity
                        })
            
            await session.run("""
                UNWIND $entities as e
                MERGE (n {id: e.id})
                ON CREATE SET n:$label, n.name = e.name
                ON MATCH SET n.name = e.name
            """, {'entities': all_entities})
            
            # Insert relationships
            all_relations = []
            for item in batch_data:
                for rel in item['relations']:
                    all_relations.append(rel)
            
            # Use apoc.periodic.iterate for large batches
            await session.run("""
                CALL apoc.periodic.iterate(
                    "UNWIND $relations as rel RETURN rel",
                    "MATCH (a {id: rel.source_id})
                     MATCH (b {id: rel.target_id})
                     CALL apoc.create.relationship(a, rel.relation_type, 
                         rel.properties, b) YIELD rel as r
                     RETURN count(r)",
                    {batchSize: 1000, params: {relations: $relations}}
                )
            """, {'relations': all_relations})
        
        return results
```

## 8. Integration with Existing Search

### 8.1 Search API Extension

```python
# src/gabi/api/search.py (extensions)

from fastapi import APIRouter, Depends, Query
from typing import Optional, List

from gabi.graphrag.search import GraphRAGSearchService

router = APIRouter()


@router.post("/search/graph")
async def search_graph(
    request: SearchRequest,
    graph_depth: int = Query(2, ge=1, le=5),
    include_citations: bool = True,
    include_conflicts: bool = True,
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service)
):
    """Execute graph-aware search.
    
    Returns documents enhanced with:
    - Citation chains
    - Related documents
    - Conflicting precedents
    - Normative chains
    """
    return await graph_service.search(
        query=request.query,
        limit=request.limit,
        graph_depth=graph_depth,
        include_citations=include_citations,
        include_conflicts=include_conflicts,
    )


@router.get("/documents/{doc_id}/citations")
async def get_citations(
    doc_id: str,
    direction: str = Query("both", enum=["incoming", "outgoing", "both"]),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service)
):
    """Get citation network for a document."""
    citations = await graph_service.get_citations(doc_id, direction)
    return {"document_id": doc_id, "citations": citations}


@router.get("/documents/{doc_id}/precedent-chain")
async def get_precedent_chain(
    doc_id: str,
    max_depth: int = Query(5, ge=1, le=10),
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service)
):
    """Get precedent chain for a document."""
    chain = await graph_service.find_precedent_chain(doc_id, max_depth=max_depth)
    return {"document_id": doc_id, "chain": chain}


@router.get("/normativos/{norm_id}/evolution")
async def get_normative_evolution(
    norm_id: str,
    graph_service: GraphRAGSearchService = Depends(get_graph_search_service)
):
    """Trace evolution of a normative document."""
    evolution = await graph_service.find_normative_evolution(norm_id)
    return {"normative_id": norm_id, "evolution": evolution}
```

### 8.2 Configuration Extensions

```python
# src/gabi/config.py (additions)

class Settings(BaseSettings):
    # ... existing settings ...
    
    # === GraphRAG (Neo4j) ===
    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: SecretStr = Field(default=SecretStr("password"))
    
    graphrag_enabled: bool = Field(default=False)
    graphrag_cache_ttl: int = Field(default=3600)
    graphrag_default_depth: int = Field(default=2)
    graphrag_max_depth: int = Field(default=5)
    
    # LLM for extraction
    graphrag_llm_model: str = Field(default="gpt-4")
    graphrag_llm_temperature: float = Field(default=0.0)
    graphrag_llm_max_tokens: int = Field(default=2000)
```

## 9. Migration Path

### 9.1 Backfill Strategy

```python
# scripts/backfill_graph.py

import asyncio
from gabi.db import get_session
from gabi.graphrag.pipeline import GraphConstructionPipeline


async def backfill_documents():
    """Backfill graph for existing documents."""
    pipeline = GraphConstructionPipeline(...)
    
    async with get_session() as session:
        # Get all documents without graph representation
        result = await session.execute("""
            SELECT d.id, d.document_id, d.title, d.source_id
            FROM documents d
            LEFT JOIN graph_sync gs ON d.document_id = gs.document_id
            WHERE gs.document_id IS NULL
              AND d.is_deleted = false
            ORDER BY d.ingested_at DESC
        """)
        
        documents = result.all()
        
        # Process in batches
        for i in range(0, len(documents), 100):
            batch = documents[i:i+100]
            
            for doc in batch:
                # Get chunks
                chunks_result = await session.execute("""
                    SELECT chunk_text, chunk_index
                    FROM document_chunks
                    WHERE document_id = :doc_id
                    ORDER BY chunk_index
                """, {'doc_id': doc.document_id})
                
                chunks = chunks_result.all()
                
                # Process
                result = await pipeline.process_document(doc, chunks)
                
                # Mark as synced
                await session.execute("""
                    INSERT INTO graph_sync (document_id, synced_at, nodes_created, rels_created)
                    VALUES (:doc_id, NOW(), :nodes, :rels)
                    ON CONFLICT (document_id) DO UPDATE
                    SET synced_at = NOW(),
                        nodes_created = EXCLUDED.nodes_created,
                        rels_created = EXCLUDED.rels_created
                """, {
                    'doc_id': doc.document_id,
                    'nodes': result.nodes_created,
                    'rels': result.relationships_created
                })
            
            await session.commit()
            print(f"Processed batch {i//100 + 1}/{(len(documents)//100) + 1}")


if __name__ == "__main__":
    asyncio.run(backfill_documents())
```

## 10. Summary

This GraphRAG architecture provides:

1. **Rich Graph Model**: Captures legal relationships (citations, revocations, precedents)
2. **Hybrid Extraction**: Combines regex patterns with LLM for high accuracy
3. **Incremental Pipeline**: Integrates with existing GABI pipeline
4. **Graph-Enhanced Search**: Traverses relationships at query time
5. **Performance Optimized**: Caching, batching, and Neo4j best practices
6. **Backward Compatible**: Can run alongside existing search

The implementation follows GABI's existing patterns (async/await, SQLAlchemy, Pydantic) and can be enabled/disabled via configuration.
