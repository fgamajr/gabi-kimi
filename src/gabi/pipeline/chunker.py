"""Chunker inteligente para documentos jurídicos.

Implementa estratégias de chunking especializadas para preservar a estrutura
de documentos jurídicos brasileiros (artigos, parágrafos, incisos, etc.).
Inclui deduplicação de chunks e overlap configurável por estratégia.
Baseado em CONTRACTS.md §3.3.
"""

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

from gabi.config import settings
from gabi.pipeline.contracts import Chunk, ChunkingResult
from gabi.types import SectionType


# Regex patterns para estruturas jurídicas brasileiras
LEGAL_PATTERNS = {
    "ementa": re.compile(
        r"(?:^|\n)\s*(?:EMENTA|Ementa)\s*(?::|-)?\s*\n?(.+?)(?=\n\s*(?:RELATÓRIO|Relatório|ACÓRDÃO|Acórdão|DECISÃO|Decisão|ARTIGO|Artigo|\d+\s*\.\s*))",
        re.DOTALL | re.IGNORECASE,
    ),
    "acordao": re.compile(
        r"(?:^|\n)\s*(?:ACÓRDÃO|Acórdão)\s*(?::|-)?\s*\n?(.+?)(?=\n\s*(?:VOTO|Voto|RELATÓRIO|Relatório|DECISÃO|Decisão|ARTIGO|Artigo))",
        re.DOTALL | re.IGNORECASE,
    ),
    "relatorio": re.compile(
        r"(?:^|\n)\s*(?:RELATÓRIO|Relatório)\s*(?::|-)?\s*\n?(.+?)(?=\n\s*(?:VOTO|Voto|ACÓRDÃO|Acórdão|DECISÃO|Decisão))",
        re.DOTALL | re.IGNORECASE,
    ),
    "voto": re.compile(
        r"(?:^|\n)\s*(?:VOTO|Voto)\s*(?::|-)?\s*\n?(.+?)(?=\n\s*(?:ACÓRDÃO|Acórdão|DECISÃO|Decisão))",
        re.DOTALL | re.IGNORECASE,
    ),
    "artigo": re.compile(
        r"(?:^|\n)\s*Art\.?\s*(\d+[\d\.]*)\s*[º°]?\s*(.+?)(?=\n\s*(?:Art\.?\s*\d+|Parágrafo|§|CAPÍTULO|SEÇÃO|TÍTULO|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "paragrafo": re.compile(
        r"(?:^|\n)\s*(?:§|Parágrafo)\s*(\d+[\d\.]*)[º°]?\s*(.+?)(?=\n\s*(?:§|Parágrafo|Art\.?\s*\d+|Inciso|Alinea|Item))",
        re.DOTALL | re.IGNORECASE,
    ),
    "paragrafo_unico": re.compile(
        r"(?:^|\n)\s*(?:Parágrafo\s+[uú]nico|Par\.?\s*[uú]nico)\s*\.?\s*(.+?)(?=\n\s*(?:Art\.?\s*\d+|CAPÍTULO|SEÇÃO|$))",
        re.DOTALL | re.IGNORECASE,
    ),
    "inciso": re.compile(
        r"(?:^|\n)\s*([IVX\d]+)\s*[–\-)]\s*(.+?)(?=\n\s*(?:[IVX\d]+\s*[–\-)]|§|Parágrafo|Art\.?\s*\d+|$))",
        re.DOTALL,
    ),
    "alinea": re.compile(
        r"(?:^|\n)\s*([a-z])\s*[–\-)]\s*(.+?)(?=\n\s*(?:[a-z]\s*[–\-)]|\d+\s*[–\-)]|[IVX]+\s*[–\-)]|$))",
        re.DOTALL,
    ),
    "item": re.compile(
        r"(?:^|\n)\s*(\d+)\s*[–\-)]\s*(.+?)(?=\n\s*(?:\d+\s*[–\-)]|[a-z]\s*[–\-)]|$))",
        re.DOTALL,
    ),
}

# Pattern para detectar fim de sentença (considerando contexto jurídico)
SENTENCE_END_PATTERN = re.compile(
    r'[.!?](?:\s+|$)|\n\s*\n', 
    re.MULTILINE
)


@dataclass
class ChunkingConfig:
    """Configuração para chunking.
    
    Attributes:
        max_tokens: Número máximo de tokens por chunk
        overlap_tokens: Número de tokens de overlap entre chunks
        strategy: Estratégia de chunking
        use_tiktoken: Se deve usar tiktoken ou estimativa por palavras
        enable_chunk_dedup: Se deve deduplicar chunks idênticos
        strategy_overrides: Overrides de overlap por estratégia
    """
    max_tokens: int = 512
    overlap_tokens: int = 50
    strategy: str = "semantic_section"
    use_tiktoken: bool = False
    enable_chunk_dedup: bool = True
    strategy_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def get_overlap_for_strategy(self, strategy: str) -> int:
        """Retorna overlap configurado para uma estratégia específica.
        
        Args:
            strategy: Nome da estratégia
            
        Returns:
            Número de tokens de overlap
        """
        if strategy in self.strategy_overrides:
            return self.strategy_overrides[strategy].get("overlap_tokens", self.overlap_tokens)
        return self.overlap_tokens
    
    def should_use_semantic_overlap(self, strategy: str) -> bool:
        """Verifica se deve usar detecção semântica de overlap.
        
        Args:
            strategy: Nome da estratégia
            
        Returns:
            True se deve usar overlap semântico
        """
        if strategy in self.strategy_overrides:
            return self.strategy_overrides[strategy].get("semantic_overlap", False)
        return False


class Tokenizer:
    """Tokenizer para contagem de tokens.
    
    Tenta usar tiktoken se disponível, senão usa estimativa por palavras.
    """
    
    def __init__(self, use_tiktoken: bool = False):
        self.encoder = None
        self.use_tiktoken = use_tiktoken
        
        if use_tiktoken:
            try:
                import tiktoken
                self.encoder = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                pass
    
    def count_tokens(self, text: str) -> int:
        """Conta tokens no texto.
        
        Args:
            text: Texto para contar tokens
            
        Returns:
            Número de tokens
        """
        if not text:
            return 0
            
        if self.encoder:
            return len(self.encoder.encode(text))
        
        # Estimativa por palavras: ~0.75 tokens por palavra para cl100k_base
        words = len(text.split())
        return int(words * 0.75)
    
    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Trunca texto para máximo de tokens.
        
        Args:
            text: Texto original
            max_tokens: Máximo de tokens permitido
            
        Returns:
            Texto truncado
        """
        if self.count_tokens(text) <= max_tokens:
            return text
        
        if self.encoder:
            tokens = self.encoder.encode(text)
            truncated = self.encoder.decode(tokens[:max_tokens])
            return truncated
        
        # Estimativa: ~1.33 palavras por token
        max_words = int(max_tokens * 1.33)
        words = text.split()
        return " ".join(words[:max_words])


class Chunker:
    """Chunker inteligente para documentos jurídicos.
    
    Implementa múltiplas estratégias de chunking com preservação
    da estrutura semântica de documentos jurídicos.
    Inclui deduplicação de chunks e overlap configurável.
    
    Attributes:
        config: Configuração de chunking
        tokenizer: Tokenizer para contagem de tokens
    """
    
    def __init__(
        self,
        max_tokens: Optional[int] = None,
        overlap_tokens: Optional[int] = None,
        strategy: str = "semantic_section",
        use_tiktoken: bool = False,
        enable_chunk_dedup: bool = True,
        strategy_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Inicializa o Chunker.
        
        Args:
            max_tokens: Máximo de tokens por chunk (default: settings)
            overlap_tokens: Tokens de overlap (default: settings)
            strategy: Estratégia de chunking
            use_tiktoken: Usar tiktoken se disponível
            enable_chunk_dedup: Deduplicar chunks idênticos
            strategy_overrides: Overrides de config por estratégia
        """
        self.config = ChunkingConfig(
            max_tokens=max_tokens or settings.pipeline_chunk_max_tokens,
            overlap_tokens=overlap_tokens or settings.pipeline_chunk_overlap_tokens,
            strategy=strategy,
            use_tiktoken=use_tiktoken,
            enable_chunk_dedup=enable_chunk_dedup,
            strategy_overrides=strategy_overrides or {},
        )
        self.tokenizer = Tokenizer(use_tiktoken=use_tiktoken)
    
    def _compute_chunk_hash(self, text: str) -> str:
        """Computa hash do conteúdo do chunk para deduplicação.
        
        Args:
            text: Texto do chunk
            
        Returns:
            Hash SHA-256 do texto normalizado
        """
        # Normaliza texto para deduplicação
        normalized = text.lower().strip()
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    def _deduplicate_chunks(self, chunks: List[Chunk]) -> List[Chunk]:
        """Remove chunks duplicados baseado no conteúdo.
        
        Args:
            chunks: Lista de chunks
            
        Returns:
            Lista de chunks únicos
        """
        if not self.config.enable_chunk_dedup:
            return chunks
        
        seen_hashes: Set[str] = set()
        unique_chunks: List[Chunk] = []
        
        for chunk in chunks:
            chunk_hash = self._compute_chunk_hash(chunk.text)
            if chunk_hash not in seen_hashes:
                seen_hashes.add(chunk_hash)
                unique_chunks.append(chunk)
        
        # Reindexa chunks após deduplicação
        for i, chunk in enumerate(unique_chunks):
            chunk.index = i
        
        return unique_chunks
    
    def _get_semantic_overlap_boundary(
        self,
        sentences: List[str],
        target_overlap_tokens: int,
    ) -> List[str]:
        """Detecta overlap semântico baseado em limites de sentença.
        
        Seleciona sentenças completas até atingir o target de tokens,
        priorizando sentenças que terminam com contexto completo.
        
        Args:
            sentences: Lista de sentenças do chunk anterior
            target_overlap_tokens: Tokens alvo para overlap
            
        Returns:
            Lista de sentenças para overlap
        """
        if not sentences:
            return []
        
        overlap_sentences = []
        overlap_tokens = 0
        
        # Percorre sentenças do final para o início
        for sentence in reversed(sentences):
            sentence_tokens = self.tokenizer.count_tokens(sentence)
            
            # Adiciona sentença se ainda não excedeu o target
            if overlap_tokens + sentence_tokens <= target_overlap_tokens:
                overlap_sentences.insert(0, sentence)
                overlap_tokens += sentence_tokens
            else:
                # Sentença excede - verifica se é sentença completa
                if overlap_tokens == 0:
                    # Primeira sentença já é maior que o target
                    # Trunca para atingir aproximadamente o target
                    truncated = self.tokenizer.truncate_to_tokens(sentence, target_overlap_tokens)
                    if truncated.strip():
                        overlap_sentences.insert(0, truncated)
                break
        
        return overlap_sentences
    
    def chunk(
        self,
        document_text: str,
        metadata: Optional[Dict[str, Any]] = None,
        document_id: Optional[str] = None,
    ) -> ChunkingResult:
        """Executa chunking do documento.
        
        Args:
            document_text: Texto do documento
            metadata: Metadados do documento
            document_id: ID do documento
            
        Returns:
            Resultado do chunking com chunks gerados
        """
        start_time = time.time()
        metadata = metadata or {}
        
        if not document_text or not document_text.strip():
            return ChunkingResult(
                chunks=[],
                document_id=document_id,
                total_tokens=0,
                total_chars=0,
                chunking_strategy=self.config.strategy,
                duration_seconds=time.time() - start_time,
            )
        
        # Obtém overlap configurado para a estratégia
        effective_overlap = self.config.get_overlap_for_strategy(self.config.strategy)
        use_semantic = self.config.should_use_semantic_overlap(self.config.strategy)
        
        # Seleciona estratégia
        if self.config.strategy == "semantic_section":
            chunks = self._chunk_by_semantic_sections(
                document_text, metadata, effective_overlap, use_semantic
            )
        elif self.config.strategy == "fixed_size":
            chunks = self._chunk_by_fixed_size(
                document_text, metadata, effective_overlap
            )
        elif self.config.strategy == "sentence_boundary":
            chunks = self._chunk_by_sentence_boundary(
                document_text, metadata, effective_overlap, use_semantic
            )
        else:
            # Fallback para semantic_section
            chunks = self._chunk_by_semantic_sections(
                document_text, metadata, effective_overlap, use_semantic
            )
        
        # Deduplica chunks
        original_count = len(chunks)
        chunks = self._deduplicate_chunks(chunks)
        deduped_count = len(chunks)
        
        duration = time.time() - start_time
        total_tokens = sum(c.token_count for c in chunks)
        total_chars = sum(c.char_count for c in chunks)
        
        return ChunkingResult(
            chunks=chunks,
            document_id=document_id,
            total_tokens=total_tokens,
            total_chars=total_chars,
            chunking_strategy=self.config.strategy,
            duration_seconds=duration,
        )
    
    def _chunk_by_semantic_sections(
        self,
        text: str,
        metadata: Dict[str, Any],
        overlap_tokens: int = 50,
        use_semantic_overlap: bool = False,
    ) -> List[Chunk]:
        """Chunking por seções semânticas jurídicas.
        
        Preserva estrutura de artigos, parágrafos, etc.
        Se seção > max_tokens, subdivide por sentenças.
        
        Args:
            text: Texto do documento
            metadata: Metadados
            overlap_tokens: Tokens de overlap para subdivisão
            use_semantic_overlap: Usar detecção semântica de overlap
            
        Returns:
            Lista de chunks
        """
        chunks = []
        chunk_index = 0
        offset = 0
        
        # Extrai seções jurídicas
        sections = self._extract_legal_sections(text)
        
        for section_text, section_type, section_metadata in sections:
            section_tokens = self.tokenizer.count_tokens(section_text)
            
            if section_tokens <= self.config.max_tokens:
                # Seção cabe em um chunk
                chunk = Chunk(
                    text=section_text.strip(),
                    index=chunk_index,
                    token_count=section_tokens,
                    char_count=len(section_text),
                    section_type=section_type,
                    metadata={**metadata, **section_metadata},
                    start_offset=offset,
                    end_offset=offset + len(section_text),
                )
                chunks.append(chunk)
                chunk_index += 1
                offset += len(section_text)
            else:
                # Seção muito grande, subdivide por sentenças
                sub_chunks = self._subdivide_section(
                    section_text, section_type, metadata, chunk_index, offset,
                    overlap_tokens, use_semantic_overlap
                )
                chunks.extend(sub_chunks)
                chunk_index += len(sub_chunks)
                if sub_chunks:
                    offset = sub_chunks[-1].end_offset
        
        return chunks
    
    def _extract_legal_sections(
        self,
        text: str,
    ) -> List[Tuple[str, Optional[SectionType], Dict[str, Any]]]:
        """Extrai seções jurídicas do texto.
        
        Args:
            text: Texto do documento
            
        Returns:
            Lista de tuplas (texto, tipo_seção, metadados)
        """
        sections = []
        matched_spans = set()  # Rastreia spans já processados (posições absolutas no texto)
        
        # Detecta seções estruturais na ordem de prioridade
        section_order = [
            ("ementa", SectionType.EMENTA),
            ("relatorio", SectionType.RELATORIO),
            ("voto", SectionType.VOTO),
            ("acordao", SectionType.ACORDAO),
        ]
        
        for pattern_key, section_type in section_order:
            pattern = LEGAL_PATTERNS.get(pattern_key)
            if pattern:
                for match in pattern.finditer(text):
                    span = match.span()
                    if span not in matched_spans:
                        section_text = match.group(0)
                        sections.append((
                            section_text,
                            section_type,
                            {"section_match": pattern_key},
                        ))
                        matched_spans.add(span)
        
        # Extrai artigos e seus parágrafos
        artigo_pattern = LEGAL_PATTERNS.get("artigo")
        if artigo_pattern:
            for match in artigo_pattern.finditer(text):
                artigo_span = match.span()
                if artigo_span in matched_spans:
                    continue
                    
                artigo_num = match.group(1)
                artigo_start = match.start()
                
                # Encontra posição do próximo artigo ou fim do texto
                next_artigo_match = None
                for next_match in artigo_pattern.finditer(text):
                    if next_match.start() > match.end():
                        next_artigo_match = next_match
                        break
                
                artigo_end = next_artigo_match.start() if next_artigo_match else len(text)
                artigo_full_text = text[artigo_start:artigo_end]
                
                # Extrai parágrafos do artigo (calcula spans absolutos)
                paragrafos = self._extract_paragrafos_with_absolute_spans(
                    artigo_full_text, artigo_start
                )
                
                # Calcula onde termina o caput (antes do primeiro parágrafo)
                first_para_start = None
                for _, _, para_span in paragrafos:
                    if first_para_start is None or para_span[0] < first_para_start:
                        first_para_start = para_span[0]
                
                if first_para_start:
                    # Extrai caput
                    caput_text = text[artigo_start:first_para_start].strip()
                    if caput_text:
                        sections.append((
                            caput_text,
                            SectionType.ARTIGO,
                            {"artigo_numero": artigo_num, "tipo": "caput"},
                        ))
                        matched_spans.add((artigo_start, first_para_start))
                    
                    # Adiciona parágrafos
                    for para_text, para_num, para_span in paragrafos:
                        if para_span not in matched_spans:
                            sections.append((
                                para_text,
                                SectionType.PARAGRAFO,
                                {
                                    "artigo_numero": artigo_num,
                                    "paragrafo_numero": para_num,
                                },
                            ))
                            matched_spans.add(para_span)
                else:
                    # Artigo sem parágrafos - artigo completo
                    sections.append((
                        artigo_full_text.strip(),
                        SectionType.ARTIGO,
                        {"artigo_numero": artigo_num},
                    ))
                    matched_spans.add((artigo_start, artigo_end))
                
                matched_spans.add(artigo_span)
        
        # Extrai parágrafos independentes (não dentro de artigos identificados)
        para_pattern = LEGAL_PATTERNS.get("paragrafo")
        if para_pattern:
            for match in para_pattern.finditer(text):
                span = match.span()
                if span not in matched_spans:
                    para_num = match.group(1)
                    para_text = match.group(0)
                    sections.append((
                        para_text.strip(),
                        SectionType.PARAGRAFO,
                        {"paragrafo_numero": para_num},
                    ))
                    matched_spans.add(span)
        
        # Extrai parágrafo único
        para_unico_pattern = LEGAL_PATTERNS.get("paragrafo_unico")
        if para_unico_pattern:
            for match in para_unico_pattern.finditer(text):
                span = match.span()
                if span not in matched_spans:
                    para_text = match.group(0)
                    sections.append((
                        para_text.strip(),
                        SectionType.PARAGRAFO,
                        {"paragrafo_numero": "único"},
                    ))
                    matched_spans.add(span)
        
        # Se não encontrou seções estruturadas, trata como texto geral
        if not sections and text.strip():
            sections.append((
                text.strip(),
                SectionType.GENERAL,
                {},
            ))
        
        # Ordena seções por posição no texto original
        def get_position(section_tuple):
            section_text = section_tuple[0]
            pos = text.find(section_text)
            return pos if pos >= 0 else len(text)
        
        sections.sort(key=get_position)
        
        return sections
    
    def _extract_paragrafos_with_absolute_spans(
        self,
        text: str,
        offset: int = 0,
    ) -> List[Tuple[str, str, Tuple[int, int]]]:
        """Extrai parágrafos com spans absolutos.
        
        Args:
            text: Texto para extrair parágrafos
            offset: Offset inicial no documento original
            
        Returns:
            Lista de tuplas (texto_parágrafo, número, span_absoluto)
        """
        paragrafos = []
        
        # Parágrafo único
        para_unico_pattern = LEGAL_PATTERNS.get("paragrafo_unico")
        if para_unico_pattern:
            match = para_unico_pattern.search(text)
            if match:
                span = (match.start() + offset, match.end() + offset)
                paragrafos.append((match.group(0), "único", span))
        
        # Parágrafos numerados
        para_pattern = LEGAL_PATTERNS.get("paragrafo")
        if para_pattern:
            for match in para_pattern.finditer(text):
                para_num = match.group(1)
                para_text = match.group(0)
                span = (match.start() + offset, match.end() + offset)
                paragrafos.append((para_text, para_num, span))
        
        return paragrafos
    
    def _extract_paragrafos(
        self,
        text: str,
    ) -> List[Tuple[str, str, Tuple[int, int]]]:
        """Extrai parágrafos de um texto.
        
        Args:
            text: Texto para extrair parágrafos
            
        Returns:
            Lista de tuplas (texto_parágrafo, número, span)
        """
        paragrafos = []
        
        # Parágrafo único
        para_unico_pattern = LEGAL_PATTERNS.get("paragrafo_unico")
        if para_unico_pattern:
            match = para_unico_pattern.search(text)
            if match:
                paragrafos.append((match.group(0), "único", match.span()))
        
        # Parágrafos numerados
        para_pattern = LEGAL_PATTERNS.get("paragrafo")
        if para_pattern:
            for match in para_pattern.finditer(text):
                para_num = match.group(1)
                para_text = match.group(0)
                paragrafos.append((para_text, para_num, match.span()))
        
        return paragrafos
    
    def _subdivide_section(
        self,
        text: str,
        section_type: Optional[SectionType],
        metadata: Dict[str, Any],
        start_index: int,
        start_offset: int,
        overlap_tokens: int = 50,
        use_semantic_overlap: bool = False,
    ) -> List[Chunk]:
        """Subdivide uma seção grande em chunks menores.
        
        Usa limites de sentença para preservar coerência.
        
        Args:
            text: Texto da seção
            section_type: Tipo da seção
            metadata: Metadados
            start_index: Índice inicial dos chunks
            start_offset: Offset inicial
            overlap_tokens: Tokens de overlap
            use_semantic_overlap: Usar detecção semântica de overlap
            
        Returns:
            Lista de chunks subdivididos
        """
        chunks = []
        sentences = self._split_sentences(text)
        
        current_chunk: List[str] = []
        current_tokens = 0
        current_offset = start_offset
        chunk_index = start_index
        
        for sentence in sentences:
            sentence_tokens = self.tokenizer.count_tokens(sentence)
            
            # Se sentença individual é maior que max_tokens, trunca
            if sentence_tokens > self.config.max_tokens:
                if current_chunk:
                    # Salva chunk atual
                    chunk_text = " ".join(current_chunk)
                    chunks.append(Chunk(
                        text=chunk_text.strip(),
                        index=chunk_index,
                        token_count=current_tokens,
                        char_count=len(chunk_text),
                        section_type=section_type,
                        metadata={**metadata, "truncated": False},
                        start_offset=current_offset,
                        end_offset=current_offset + len(chunk_text),
                    ))
                    chunk_index += 1
                    current_chunk = []
                    current_tokens = 0
                
                # Trunca sentença longa
                truncated = self.tokenizer.truncate_to_tokens(
                    sentence, self.config.max_tokens
                )
                chunks.append(Chunk(
                    text=truncated.strip(),
                    index=chunk_index,
                    token_count=self.tokenizer.count_tokens(truncated),
                    char_count=len(truncated),
                    section_type=section_type,
                    metadata={**metadata, "truncated": True},
                    start_offset=current_offset,
                    end_offset=current_offset + len(truncated),
                ))
                chunk_index += 1
                current_offset += len(sentence)
                continue
            
            # Verifica se adicionar sentença excede max_tokens
            if current_tokens + sentence_tokens > self.config.max_tokens and current_chunk:
                # Salva chunk atual
                chunk_text = " ".join(current_chunk)
                chunks.append(Chunk(
                    text=chunk_text.strip(),
                    index=chunk_index,
                    token_count=current_tokens,
                    char_count=len(chunk_text),
                    section_type=section_type,
                    metadata=metadata,
                    start_offset=current_offset,
                    end_offset=current_offset + len(chunk_text),
                ))
                
                # Inicia novo chunk com overlap se configurado
                if overlap_tokens > 0 and current_chunk:
                    if use_semantic_overlap:
                        # Usa detecção semântica de overlap
                        overlap_sentences = self._get_semantic_overlap_boundary(
                            current_chunk, overlap_tokens
                        )
                    else:
                        # Overlap simples por tokens
                        overlap_sentences = []
                        overlap_token_count = 0
                        for s in reversed(current_chunk):
                            s_tokens = self.tokenizer.count_tokens(s)
                            if overlap_token_count + s_tokens <= overlap_tokens:
                                overlap_sentences.insert(0, s)
                                overlap_token_count += s_tokens
                            else:
                                break
                    current_chunk = overlap_sentences
                    current_tokens = sum(
                        self.tokenizer.count_tokens(s) for s in current_chunk
                    )
                else:
                    current_chunk = []
                    current_tokens = 0
                
                chunk_index += 1
                current_offset += len(chunk_text) - sum(len(s) for s in current_chunk)
            
            current_chunk.append(sentence)
            current_tokens += sentence_tokens
        
        # Adiciona chunk final
        if current_chunk:
            chunk_text = " ".join(current_chunk)
            chunks.append(Chunk(
                text=chunk_text.strip(),
                index=chunk_index,
                token_count=current_tokens,
                char_count=len(chunk_text),
                section_type=section_type,
                metadata=metadata,
                start_offset=current_offset,
                end_offset=current_offset + len(chunk_text),
            ))
        
        return chunks
    
    def _split_sentences(self, text: str) -> List[str]:
        """Divide texto em sentenças.
        
        Args:
            text: Texto para dividir
            
        Returns:
            Lista de sentenças
        """
        # Split por fim de sentença, preservando delimitadores
        sentences = []
        current = ""
        
        for char in text:
            current += char
            if char in ".!?" or (char == "\n" and current.strip().endswith("\n")):
                stripped = current.strip()
                if stripped:
                    sentences.append(stripped)
                current = ""
        
        if current.strip():
            sentences.append(current.strip())
        
        return sentences
    
    def _chunk_by_fixed_size(
        self,
        text: str,
        metadata: Dict[str, Any],
        overlap_tokens: int = 50,
    ) -> List[Chunk]:
        """Chunking por tamanho fixo com overlap.
        
        Args:
            text: Texto do documento
            metadata: Metadados
            overlap_tokens: Tokens de overlap
            
        Returns:
            Lista de chunks
        """
        chunks = []
        chunk_index = 0
        
        # Converte tokens para caracteres (estimativa)
        chars_per_token = 4  # Aproximação conservadora
        max_chars = self.config.max_tokens * chars_per_token
        overlap_chars = min(overlap_tokens * chars_per_token, max_chars // 2)
        
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            
            # Tenta quebrar em espaço ou nova linha
            if end < len(text):
                # Procura quebra natural nos últimos 100 caracteres
                search_start = max(start, end - 100)
                for i in range(end, search_start, -1):
                    if i > 0 and text[i - 1] in " \n":
                        end = i
                        break
            
            chunk_text = text[start:end].strip()
            if chunk_text:
                tokens = self.tokenizer.count_tokens(chunk_text)
                chunks.append(Chunk(
                    text=chunk_text,
                    index=chunk_index,
                    token_count=tokens,
                    char_count=len(chunk_text),
                    section_type=SectionType.GENERAL,
                    metadata=metadata,
                    start_offset=start,
                    end_offset=end,
                ))
                chunk_index += 1
            
            # Avança com overlap (garante progresso mínimo)
            if end < len(text):
                start = max(end - overlap_chars, start + 1)
            else:
                start = end
        
        return chunks
    
    def _chunk_by_sentence_boundary(
        self,
        text: str,
        metadata: Dict[str, Any],
        overlap_tokens: int = 50,
        use_semantic_overlap: bool = False,
    ) -> List[Chunk]:
        """Chunking por limites de sentença.
        
        Args:
            text: Texto do documento
            metadata: Metadados
            overlap_tokens: Tokens de overlap
            use_semantic_overlap: Usar detecção semântica de overlap
            
        Returns:
            Lista de chunks
        """
        sentences = self._split_sentences(text)
        return self._subdivide_section(
            " ".join(sentences),
            SectionType.GENERAL,
            metadata,
            0,
            0,
            overlap_tokens,
            use_semantic_overlap,
        )
    
    def estimate_tokens(self, text: str) -> int:
        """Estima número de tokens no texto.
        
        Args:
            text: Texto para estimar
            
        Returns:
            Número estimado de tokens
        """
        return self.tokenizer.count_tokens(text)


# Instância global para uso conveniente
default_chunker = Chunker()


def chunk_document(
    document_text: str,
    metadata: Optional[Dict[str, Any]] = None,
    document_id: Optional[str] = None,
    max_tokens: Optional[int] = None,
    overlap_tokens: Optional[int] = None,
    strategy: str = "semantic_section",
    enable_chunk_dedup: bool = True,
    strategy_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> ChunkingResult:
    """Função utilitária para chunking de documentos.
    
    Args:
        document_text: Texto do documento
        metadata: Metadados do documento
        document_id: ID do documento
        max_tokens: Máximo de tokens por chunk
        overlap_tokens: Tokens de overlap padrão
        strategy: Estratégia de chunking
        enable_chunk_dedup: Deduplicar chunks idênticos
        strategy_overrides: Overrides de config por estratégia
        
    Returns:
        Resultado do chunking
    """
    chunker = Chunker(
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        strategy=strategy,
        enable_chunk_dedup=enable_chunk_dedup,
        strategy_overrides=strategy_overrides,
    )
    return chunker.chunk(document_text, metadata, document_id)
