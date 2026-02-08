"""Módulo de fingerprinting de documentos.

Implementa geração de fingerprints canônicos para deduplicação cross-source.
Baseado em CONTRACTS.md §2.4 e INVARIANTS.md.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from gabi.pipeline.contracts import ParsedDocument, DocumentFingerprint


@dataclass
class FingerprinterConfig:
    """Configuração do fingerprinter.
    
    Attributes:
        algorithm: Algoritmo de hash (padrão: sha256)
        normalize_case: Converter para lowercase antes de hash
        normalize_whitespace: Remover whitespace excessivo
        include_metadata: Incluir metadados no cálculo do hash
        metadata_keys: Lista de chaves de metadados a incluir (vazio = todas)
    """
    algorithm: str = "sha256"
    normalize_case: bool = True
    normalize_whitespace: bool = True
    include_metadata: bool = False
    metadata_keys: list = field(default_factory=list)


class Fingerprinter:
    """Gerador de fingerprints canônicos para documentos.
    
    Implementa fingerprinting determinístico baseado em SHA-256
    do conteúdo normalizado. Usado para deduplicação cross-source.
    
    Example:
        >>> config = FingerprinterConfig(normalize_case=True)
        >>> fingerprinter = Fingerprinter(config)
        >>> fingerprint = fingerprinter.compute(parsed_doc)
    """
    
    def __init__(self, config: Optional[FingerprinterConfig] = None):
        """Inicializa o fingerprinter.
        
        Args:
            config: Configuração opcional
        """
        self.config = config or FingerprinterConfig()
        self._validate_algorithm()
    
    def _validate_algorithm(self) -> None:
        """Valida se o algoritmo é suportado."""
        supported = {"sha256", "sha512", "sha1", "md5"}
        if self.config.algorithm not in supported:
            raise ValueError(
                f"Algoritmo não suportado: {self.config.algorithm}. "
                f"Suportados: {supported}"
            )
    
    def _normalize_content(self, content: str) -> str:
        """Normaliza o conteúdo do documento.
        
        Aplica normalizações configuradas:
        - Remove whitespace excessivo (se configurado)
        - Converte para lowercase (se configurado)
        
        Args:
            content: Conteúdo original
            
        Returns:
            Conteúdo normalizado
        """
        normalized = content
        
        if self.config.normalize_whitespace:
            # Remove espaços em branco excessivos
            # - Remove leading/trailing whitespace
            # - Substitui múltiplos espaços/tab/newlines por um único espaço
            normalized = normalized.strip()
            normalized = re.sub(r'\s+', ' ', normalized)
        
        if self.config.normalize_case:
            normalized = normalized.lower()
        
        return normalized
    
    def _compute_content_hash(self, content: str) -> str:
        """Calcula o hash SHA-256 do conteúdo.
        
        Args:
            content: Conteúdo normalizado
            
        Returns:
            Hash hexadecimal SHA-256
        """
        content_bytes = content.encode('utf-8')
        
        if self.config.algorithm == "sha256":
            return hashlib.sha256(content_bytes).hexdigest()
        elif self.config.algorithm == "sha512":
            return hashlib.sha512(content_bytes).hexdigest()
        elif self.config.algorithm == "sha1":
            return hashlib.sha1(content_bytes).hexdigest()
        elif self.config.algorithm == "md5":
            return hashlib.md5(content_bytes).hexdigest()
        else:
            # Fallback (nunca deve acontecer devido à validação)
            return hashlib.sha256(content_bytes).hexdigest()
    
    def _compute_metadata_hash(self, metadata: Dict[str, Any]) -> str:
        """Calcula hash dos metadados se configurado.
        
        Args:
            metadata: Metadados do documento
            
        Returns:
            Hash hexadecimal dos metadados ou string vazia
        """
        if not self.config.include_metadata:
            return ""
        
        # Seleciona chaves específicas ou usa todas
        if self.config.metadata_keys:
            selected = {
                k: metadata[k] 
                for k in self.config.metadata_keys 
                if k in metadata
            }
        else:
            selected = metadata
        
        # Ordena por chave para garantir determinismo
        metadata_str = str(sorted(selected.items()))
        
        if self.config.algorithm == "sha256":
            return hashlib.sha256(metadata_str.encode('utf-8')).hexdigest()
        elif self.config.algorithm == "sha512":
            return hashlib.sha512(metadata_str.encode('utf-8')).hexdigest()
        elif self.config.algorithm == "sha1":
            return hashlib.sha1(metadata_str.encode('utf-8')).hexdigest()
        elif self.config.algorithm == "md5":
            return hashlib.md5(metadata_str.encode('utf-8')).hexdigest()
        else:
            return hashlib.sha256(metadata_str.encode('utf-8')).hexdigest()
    
    def compute(self, document: ParsedDocument) -> DocumentFingerprint:
        """Computa o fingerprint de um documento parseado.
        
        Normaliza o conteúdo e calcula o hash SHA-256. Opcionalmente
        inclui metadados no hash se configurado.
        
        Args:
            document: Documento parseado
            
        Returns:
            DocumentFingerprint com hash e informações de normalização
            
        Raises:
            ValueError: Se o documento não tiver conteúdo
        """
        if not document.content:
            raise ValueError(f"Documento sem conteúdo: {document.document_id}")
        
        # Normaliza o conteúdo
        content_normalized = self._normalize_content(document.content)
        
        # Calcula hash do conteúdo
        content_hash = self._compute_content_hash(content_normalized)
        
        # Calcula hash dos metadados (se configurado)
        metadata_hash = self._compute_metadata_hash(document.metadata)
        
        # Fingerprint final combina content_hash e metadata_hash (se presente)
        if metadata_hash:
            combined = f"{content_hash}:{metadata_hash}"
            final_fingerprint = hashlib.sha256(combined.encode('utf-8')).hexdigest()
        else:
            final_fingerprint = content_hash
        
        # Prepara componentes para auditoria
        components = {
            "content_hash": content_hash,
            "content_length": str(len(document.content)),
            "normalized_length": str(len(content_normalized)),
        }
        
        if metadata_hash:
            components["metadata_hash"] = metadata_hash
        
        return DocumentFingerprint(
            fingerprint=final_fingerprint,
            algorithm=self.config.algorithm,
            document_id=document.document_id,
            source_id=document.source_id,
            components=components,
        )
    
    def compute_from_text(
        self, 
        text: str, 
        document_id: str = "",
        source_id: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> DocumentFingerprint:
        """Computa fingerprint a partir de texto puro.
        
        Método utilitário para casos onde não há um ParsedDocument completo.
        
        Args:
            text: Texto para fingerprinting
            document_id: ID opcional do documento
            source_id: ID opcional da fonte
            metadata: Metadados opcionais
            
        Returns:
            DocumentFingerprint calculado
        """
        doc = ParsedDocument(
            document_id=document_id or "unknown",
            source_id=source_id or "unknown",
            content=text,
            metadata=metadata or {},
        )
        return self.compute(doc)
    
    def compare(
        self, 
        fp1: DocumentFingerprint, 
        fp2: DocumentFingerprint
    ) -> bool:
        """Compara dois fingerprints para igualdade.
        
        Args:
            fp1: Primeiro fingerprint
            fp2: Segundo fingerprint
            
        Returns:
            True se os fingerprints são idênticos
        """
        return fp1.fingerprint == fp2.fingerprint
    
    def get_fingerprint_info(self, fingerprint: DocumentFingerprint) -> Dict[str, Any]:
        """Retorna informações detalhadas sobre um fingerprint.
        
        Args:
            fingerprint: Fingerprint para analisar
            
        Returns:
            Dicionário com informações do fingerprint
        """
        return {
            "fingerprint": fingerprint.fingerprint,
            "algorithm": fingerprint.algorithm,
            "document_id": fingerprint.document_id,
            "source_id": fingerprint.source_id,
            "components": fingerprint.components,
            "created_at": fingerprint.created_at.isoformat(),
        }
