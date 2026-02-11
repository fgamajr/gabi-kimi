"""Entity and Relation Extraction for GraphRAG.

This module provides LLM-based extraction of entities and relationships
from legal documents, combining regex patterns with LLM analysis.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Pattern
import json
import re
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExtractedEntity:
    """Entity extracted from document text."""
    id: str                          # Normalized ID
    type: str                        # Entity type
    name: str                        # Display name
    properties: Dict[str, Any] = field(default_factory=dict)
    source_text: str = ""            # Original text fragment
    confidence: float = 0.0          # Extraction confidence


@dataclass
class ExtractedRelation:
    """Relationship extracted from document text."""
    source_id: str                   # Source entity ID
    target_id: str                   # Target entity ID
    relation_type: str               # Type of relationship
    properties: Dict[str, Any] = field(default_factory=dict)
    source_text: str = ""            # Supporting text
    confidence: float = 0.0          # Extraction confidence


class LegalEntityExtractor:
    """Extract entities and relations from legal documents using LLM."""
    
    # Document type patterns for normalization
    DOC_PATTERNS: Dict[str, List[str]] = {
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
        'lei': [
            r'Lei\s*(?:n[º°]?\s*)?(\d{1,5})[/-](\d{2,4})',
        ],
        'processo': [
            r'Processo\s*(?:TC|n[º°])?\s*(\d{7,10})[/-](\d{2})[/-](\d)',
            r'TC[\s-]*(\d{7,10})[/-](\d{2})[/-](\d)',
        ],
    }
    
    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        self._compiled_patterns: Dict[str, List[Pattern]] = {}
        self._compile_patterns()
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for performance."""
        for doc_type, patterns in self.DOC_PATTERNS.items():
            self._compiled_patterns[doc_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
    
    async def extract(
        self, 
        document_text: str, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, List[Any]]:
        """Extract entities and relations from document.
        
        Args:
            document_text: Full text of the document
            metadata: Document metadata (source_id, date, etc.)
            
        Returns:
            Dictionary with entities and relations
        """
        metadata = metadata or {}
        
        # Phase 1: Regex pre-extraction for known patterns
        regex_entities = self._extract_regex_patterns(document_text)
        
        # Phase 2: LLM extraction for complex relationships
        llm_result = {"entities": [], "relations": []}
        if self.llm_client:
            try:
                llm_result = await self._extract_with_llm(document_text, regex_entities)
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}")
        
        # Phase 3: Merge and deduplicate
        merged = self._merge_extractions(regex_entities, llm_result)
        
        return merged
    
    def _extract_regex_patterns(self, text: str) -> List[ExtractedEntity]:
        """Extract entities using regex patterns."""
        entities = []
        
        for doc_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    # Normalize ID
                    try:
                        normalized_id = self._normalize_id(doc_type, match.groups())
                        entities.append(ExtractedEntity(
                            id=normalized_id,
                            type=doc_type,
                            name=match.group(0).strip(),
                            properties={'matched_pattern': pattern.pattern},
                            source_text=match.group(0),
                            confidence=0.9
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to normalize ID for {match.group(0)}: {e}")
        
        return entities
    
    def _normalize_id(self, doc_type: str, groups: tuple) -> str:
        """Normalize document ID to canonical format."""
        if doc_type == 'acordao':
            num, year = groups[:2]
            year_str = str(year)
            year_full = year_str if len(year_str) == 4 else f"20{year_str}"
            return f"AC-{int(num):05d}-{year_full}"
        elif doc_type == 'sumula':
            return f"STCU-{int(groups[0]):03d}"
        elif doc_type == 'normativo':
            tipo = groups[0]
            num = groups[1]
            year = groups[2]
            tipo_map = {
                'IN': 'IN', 
                'Port.': 'PORT', 
                'Portaria': 'PORT',
                'Res.': 'RES', 
                'Resolucao': 'RES',
                'Resolução': 'RES',
            }
            return f"{tipo_map.get(tipo, tipo)}-{int(num):04d}-{year}"
        elif doc_type == 'lei':
            num, year = groups[:2]
            return f"LEI-{int(num):05d}-{year}"
        return f"{doc_type}-{'-'.join(str(g) for g in groups)}"
    
    async def _extract_with_llm(
        self, 
        text: str, 
        known_entities: List[ExtractedEntity]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Use LLM to extract relationships and additional entities."""
        
        if not self.llm_client:
            return {"entities": [], "relations": []}
        
        # Truncate text if too long
        max_chars = 15000
        truncated_text = text[:max_chars] if len(text) > max_chars else text
        
        # Build entity context from regex extraction
        entity_context = "\n".join([
            f"- {e.type}: {e.name} (ID: {e.id})" 
            for e in known_entities[:50]
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
        
        try:
            response = await self._call_llm(prompt)
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
        except Exception as e:
            logger.error(f"LLM extraction error: {e}")
        
        return {"entities": [], "relations": []}
    
    async def _call_llm(self, prompt: str) -> str:
        """Call LLM client with prompt."""
        if hasattr(self.llm_client, 'complete'):
            return await self.llm_client.complete(prompt)
        elif hasattr(self.llm_client, 'generate'):
            return await self.llm_client.generate(prompt)
        else:
            raise ValueError("LLM client must have 'complete' or 'generate' method")
    
    def _merge_extractions(
        self, 
        regex_entities: List[ExtractedEntity], 
        llm_result: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Merge regex and LLM extractions, removing duplicates."""
        
        # Convert to dictionaries
        all_entities: Dict[str, Dict[str, Any]] = {}
        
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
        seen_relations: set = set()
        unique_relations: List[Dict[str, Any]] = []
        
        for r in llm_result.get('relations', []):
            rel_key = (r.get('source_id'), r.get('target_id'), r.get('relation_type'))
            if rel_key not in seen_relations:
                seen_relations.add(rel_key)
                unique_relations.append(r)
        
        return {
            'entities': list(all_entities.values()),
            'relations': unique_relations
        }


# Legacy alias for backwards compatibility
EntityExtractor = LegalEntityExtractor
