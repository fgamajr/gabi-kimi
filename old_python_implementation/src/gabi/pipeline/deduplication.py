"""Módulo de deduplicação de documentos.

Implementa deduplicação cross-source usando fingerprints canônicos
com cache in-memory e distributed lock via Redis para evitar
race conditions em ambientes multi-worker.

Baseado em GABI_SPECS_FINAL_v1.md §2.8.2 e CONTRACTS.md §2.5.
"""

import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.exceptions import DeduplicationError
from gabi.models.document import Document
from gabi.pipeline.contracts import DuplicateCheckResult
from gabi.types import DocumentStatus

logger = logging.getLogger(__name__)


@dataclass
class DedupConfig:
    """Configuração do deduplicator.
    
    Attributes:
        cache_ttl_seconds: Tempo de vida do cache in-memory
        cache_max_size: Tamanho máximo do cache (LRU eviction)
        lock_timeout_seconds: Timeout do distributed lock
        lock_blocking_timeout_seconds: Timeout para adquirir lock
        redis_key_prefix: Prefixo para chaves Redis
    """
    cache_ttl_seconds: int = 300  # 5 minutos
    cache_max_size: int = 10000
    lock_timeout_seconds: int = 30
    lock_blocking_timeout_seconds: int = 5
    redis_key_prefix: str = "gabi:dedup"


class InMemoryFingerprintCache:
    """Cache LRU em memória para fingerprints.
    
    Implementa cache com TTL e limitação de tamanho usando OrderedDict
    para O(1) em operações de acesso, inserção e remoção.
    Usado para reduzir queries ao banco de dados.
    """
    
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 300):
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        # OrderedDict mantém ordem de inserção - O(1) para move_to_end e popitem
        self._cache: OrderedDict[str, tuple[str, datetime]] = OrderedDict()
    
    def get(self, fingerprint: str) -> Optional[str]:
        """Busca fingerprint no cache.
        
        Args:
            fingerprint: Fingerprint a buscar
            
        Returns:
            ID do documento existente ou None
        """
        if fingerprint not in self._cache:
            return None
        
        document_id, timestamp = self._cache[fingerprint]
        
        # Verifica TTL
        if datetime.utcnow() - timestamp > timedelta(seconds=self._ttl_seconds):
            del self._cache[fingerprint]
            return None
        
        # Move para o final (mais recentemente usado) - O(1)
        self._cache.move_to_end(fingerprint)
        
        return document_id
    
    def set(self, fingerprint: str, document_id: str) -> None:
        """Adiciona fingerprint ao cache.
        
        Args:
            fingerprint: Fingerprint a adicionar
            document_id: ID do documento associado
        """
        # Adiciona/atualiza entrada
        self._cache[fingerprint] = (document_id, datetime.utcnow())
        # Move para o final (mais recente) - O(1)
        self._cache.move_to_end(fingerprint)
        
        # Eviction do mais antigo se ultrapassar o limite - O(1)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)
    
    def invalidate(self, fingerprint: str) -> None:
        """Remove fingerprint do cache.
        
        Args:
            fingerprint: Fingerprint a remover
        """
        if fingerprint in self._cache:
            del self._cache[fingerprint]
    
    def clear(self) -> None:
        """Limpa todo o cache."""
        self._cache.clear()
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache.
        
        Returns:
            Dicionário com estatísticas do cache
        """
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "utilization": len(self._cache) / self._max_size * 100 if self._max_size > 0 else 0,
            "ttl_seconds": self._ttl_seconds,
        }


class Deduplicator:
    """Deduplicator com cache in-memory e distributed lock.
    
    Implementa deduplicação cross-source verificando fingerprints
    no PostgreSQL com cache LRU e distributed lock via Redis
    para evitar race conditions.
    
    Example:
        >>> dedup = Deduplicator(db_session, redis_client)
        >>> result = await dedup.check_duplicate(fingerprint)
        >>> if result.is_duplicate:
        ...     print(f"Duplicate of {result.existing_document_id}")
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        redis_client: Optional[Any] = None,
        config: Optional[DedupConfig] = None,
    ):
        """Inicializa o deduplicator.
        
        Args:
            db_session: Sessão SQLAlchemy assíncrona
            redis_client: Cliente Redis para distributed lock (opcional)
            config: Configuração do deduplicator
        """
        self.db = db_session
        self.redis = redis_client
        self.config = config or DedupConfig()
        self.cache = InMemoryFingerprintCache(
            max_size=self.config.cache_max_size,
            ttl_seconds=self.config.cache_ttl_seconds,
        )
    
    async def check_duplicate(
        self,
        fingerprint: str,
        use_cache: bool = True,
    ) -> DuplicateCheckResult:
        """Verifica se um fingerprint é duplicado.
        
        Busca no cache primeiro, depois no banco de dados.
        Documentos deletados (soft delete) são ignorados,
        permitindo re-ingestão.
        
        Args:
            fingerprint: Fingerprint a verificar
            use_cache: Se deve usar cache in-memory
            
        Returns:
            DuplicateCheckResult com informações da verificação
            
        Raises:
            DeduplicationError: Em caso de erro na verificação
        """
        try:
            # 1. Verifica cache
            if use_cache:
                cached_doc_id = self.cache.get(fingerprint)
                if cached_doc_id:
                    logger.debug(f"Cache hit for fingerprint: {fingerprint[:16]}...")
                    return DuplicateCheckResult(
                        is_duplicate=True,
                        existing_document_id=cached_doc_id,
                        fingerprint=fingerprint,
                        confidence=1.0,
                    )
            
            # 2. Verifica banco de dados
            result = await self.db.execute(
                select(Document).where(
                    Document.fingerprint == fingerprint,
                    Document.is_deleted == False,  # noqa: E712 - soft delete check
                )
            )
            existing_doc = result.scalar_one_or_none()
            
            if existing_doc:
                # Adiciona ao cache
                if use_cache:
                    self.cache.set(fingerprint, existing_doc.document_id)
                
                return DuplicateCheckResult(
                    is_duplicate=True,
                    existing_document_id=existing_doc.document_id,
                    fingerprint=fingerprint,
                    confidence=1.0,
                )
            
            # Não é duplicado
            return DuplicateCheckResult(
                is_duplicate=False,
                existing_document_id=None,
                fingerprint=fingerprint,
                confidence=1.0,
            )
            
        except Exception as e:
            logger.error(f"Error checking duplicate: {e}")
            raise DeduplicationError(
                f"Failed to check duplicate: {e}",
                details={"fingerprint": fingerprint},
                cause=e,
            )
    
    async def check_and_lock(
        self,
        fingerprint: str,
        document_id: str,
        use_cache: bool = True,
    ) -> bool:
        """Verifica duplicata com distributed lock.
        
        Usa distributed lock via Redis para evitar race conditions
        quando múltiplos workers processam o mesmo documento
        simultaneamente.
        
        Args:
            fingerprint: Fingerprint a verificar
            document_id: ID do documento sendo processado
            use_cache: Se deve usar cache in-memory
            
        Returns:
            True se é duplicado (não deve processar), False caso contrário
            
        Raises:
            DeduplicationError: Em caso de erro na verificação
        """
        lock_key = f"{self.config.redis_key_prefix}:lock:{fingerprint}"
        
        try:
            # Se não tem Redis, faz check simples
            if not self.redis:
                result = await self.check_duplicate(fingerprint, use_cache)
                return result.is_duplicate
            
            # Tenta adquirir lock distribuído
            lock = self.redis.lock(
                lock_key,
                timeout=self.config.lock_timeout_seconds,
            )
            
            acquired = await lock.acquire(
                blocking_timeout=self.config.lock_blocking_timeout_seconds
            )
            
            if not acquired:
                logger.warning(f"Could not acquire lock for {fingerprint[:16]}...")
                # Se não conseguiu lock, assume que outro worker está processando
                # e considera como duplicado para evitar duplicação
                return True
            
            try:
                # Com lock adquirido, verifica duplicata
                result = await self.check_duplicate(fingerprint, use_cache)
                
                if not result.is_duplicate:
                    # Não é duplicado - adiciona ao cache para prevenir
                    # que outros workers processem o mesmo documento
                    self.cache.set(fingerprint, document_id)
                
                return result.is_duplicate
                
            finally:
                # Sempre libera o lock
                try:
                    await lock.release()
                except Exception as e:
                    logger.warning(f"Error releasing lock: {e}")
                    
        except Exception as e:
            logger.error(f"Error in check_and_lock: {e}")
            raise DeduplicationError(
                f"Failed to check and lock: {e}",
                details={"fingerprint": fingerprint, "document_id": document_id},
                cause=e,
            )
    
    async def mark_processed(
        self,
        fingerprint: str,
        document_id: str,
    ) -> None:
        """Marca um fingerprint como processado.
        
        Adiciona ao cache para futuras verificações rápidas.
        
        Args:
            fingerprint: Fingerprint processado
            document_id: ID do documento processado
        """
        self.cache.set(fingerprint, document_id)
        logger.debug(f"Marked fingerprint as processed: {fingerprint[:16]}...")
    
    def invalidate_cache(self, fingerprint: Optional[str] = None) -> None:
        """Invalida cache.
        
        Args:
            fingerprint: Fingerprint específico para invalidar,
                        ou None para limpar todo o cache
        """
        if fingerprint:
            self.cache.invalidate(fingerprint)
            logger.debug(f"Invalidated cache for: {fingerprint[:16]}...")
        else:
            self.cache.clear()
            logger.debug("Cleared all fingerprint cache")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do cache.
        
        Returns:
            Dicionário com estatísticas do cache
        """
        stats = self.cache.get_stats()
        return {
            "cache_size": stats["size"],
            "cache_max_size": stats["max_size"],
            "cache_ttl_seconds": stats["ttl_seconds"],
            "cache_utilization_percent": stats["utilization"],
        }
