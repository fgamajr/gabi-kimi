"""GABI Embedding Services Module.

Serviço de alto nível para geração de embeddings com:
- Cache de embeddings no Redis
- Fallback quando TEI indisponível
- Métricas e observabilidade
- Rate limiting por cliente

Baseado em GABI_SPECS_FINAL_v1.md §2.3.8, §E-002

Example:
    >>> from gabi.services.embedding_service import EmbeddingService
    >>> service = EmbeddingService()
    >>> embeddings = await service.embed_batch(["texto 1", "texto 2"])
    >>> print(f"Cache hit rate: {service.metrics.cache_hit_rate:.2%}")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, Union

from gabi.config import settings

if TYPE_CHECKING:
    from redis.asyncio import Redis
from gabi.pipeline.embedder import (
    CircuitBreakerOpenError,
    Embedder,
    EmbeddingError,
    TEIConnectionError,
)
from gabi.pipeline.contracts import EmbeddedChunk, EmbeddingResult

logger = logging.getLogger(__name__)


class EmbeddingBackend(Protocol):
    """Protocolo para backends de embedding."""
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Gera embeddings para lista de textos."""
        ...
    
    async def close(self) -> None:
        """Fecha conexões."""
        ...


class LocalEmbeddingBackend:
    """Backend de embeddings local (fallback).
    
    Usa sentence-transformers localmente quando TEI indisponível.
    Mais lento que TEI, mas garante disponibilidade.
    """
    
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.embeddings_model
        self._model: Any = None
        self._dimensions: int = 384
    
    def _load_model(self) -> Any:
        """Lazy loading do modelo."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                
                logger.info(f"Loading local embedding model: {self.model_name}")
                self._model = SentenceTransformer(self.model_name)
                logger.info("Local embedding model loaded successfully")
            except ImportError:
                raise EmbeddingError(
                    "sentence-transformers not installed. "
                    "Install with: pip install sentence-transformers"
                )
        return self._model
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Gera embeddings localmente."""
        import asyncio
        
        model = self._load_model()
        
        # Executa em thread separada (modelo é CPU-bound)
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,  # Default executor
            lambda: model.encode(texts, convert_to_numpy=True).tolist(),
        )
        
        return embeddings
    
    async def close(self) -> None:
        """Libera recursos."""
        self._model = None


@dataclass
class CacheConfig:
    """Configuração do cache Redis.
    
    Attributes:
        ttl_seconds: Tempo de vida do cache
        prefix: Prefixo das chaves
        enabled: Se cache está habilitado
    """
    ttl_seconds: int = 86400  # 24 horas
    prefix: str = "emb:"
    enabled: bool = True


@dataclass
class EmbeddingMetrics:
    """Métricas de embeddings.
    
    Attributes:
        total_requests: Total de requisições
        cache_hits: Hits no cache
        cache_misses: Misses no cache
        tei_requests: Requisições ao TEI
        fallback_requests: Requisições ao fallback
        errors: Total de erros
        total_duration_ms: Tempo total em ms
    """
    total_requests: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    tei_requests: int = 0
    fallback_requests: int = 0
    errors: int = 0
    total_duration_ms: float = 0.0
    
    @property
    def cache_hit_rate(self) -> float:
        """Taxa de cache hit."""
        if self.cache_hits + self.cache_misses == 0:
            return 0.0
        return self.cache_hits / (self.cache_hits + self.cache_misses)
    
    @property
    def average_latency_ms(self) -> float:
        """Latência média."""
        if self.total_requests == 0:
            return 0.0
        return self.total_duration_ms / self.total_requests


class EmbeddingService:
    """Serviço de alto nível para geração de embeddings.
    
    Responsabilidades:
    - Cache de embeddings no Redis
    - Fallback para backend local quando TEI indisponível
    - Métricas e logging
    - Rate limiting por cliente
    
    Attributes:
        embedder: Cliente TEI
        fallback_backend: Backend local para fallback
        redis_client: Cliente Redis para cache
        cache_config: Configuração de cache
        metrics: Métricas acumuladas
    
    Example:
        >>> service = EmbeddingService()
        >>> chunks = ["texto 1", "texto 2"]
        >>> result = await service.embed_batch(chunks)
        >>> print(f"Cache hit rate: {service.metrics.cache_hit_rate:.2%}")
    """
    
    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        fallback_backend: Optional[EmbeddingBackend] = None,
        redis_client: Optional["Redis"] = None,
        cache_config: Optional[CacheConfig] = None,
        enable_fallback: bool = True,
    ):
        """Inicializa o serviço.
        
        Args:
            embedder: Cliente TEI (cria novo se None)
            fallback_backend: Backend de fallback (cria novo se None)
            redis_client: Cliente Redis (deve ser injetado)
            cache_config: Configuração de cache
            enable_fallback: Se deve usar fallback quando TEI falha
        """
        self.embedder = embedder or Embedder()
        self.fallback_backend = fallback_backend
        self.redis_client = redis_client
        self.cache_config = cache_config or CacheConfig()
        self.enable_fallback = enable_fallback
        self.metrics = EmbeddingMetrics()
        
        # Inicializa fallback se habilitado
        if self.enable_fallback and self.fallback_backend is None:
            try:
                self.fallback_backend = LocalEmbeddingBackend()
            except Exception as e:
                logger.warning(f"Could not initialize fallback backend: {e}")
        
        logger.info(
            f"EmbeddingService initialized: cache_enabled={self.cache_config.enabled}, "
            f"fallback_enabled={self.enable_fallback and self.fallback_backend is not None}"
        )
    
    async def close(self) -> None:
        """Fecha conexões."""
        await self.embedder.close()
        if self.fallback_backend:
            await self.fallback_backend.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def _get_cache_key(self, text: str) -> str:
        """Gera chave de cache.
        
        Args:
            text: Texto
            
        Returns:
            Chave de cache
        """
        import hashlib
        
        model_hash = hashlib.md5(self.embedder.model.encode()).hexdigest()[:8]
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return f"{self.cache_config.prefix}{model_hash}:{content_hash}"
    
    async def _get_from_cache(self, text: str) -> Optional[List[float]]:
        """Busca embedding no cache.
        
        Args:
            text: Texto
            
        Returns:
            Embedding cacheado ou None
        """
        if not self.cache_config.enabled or self.redis_client is None:
            return None
        
        try:
            key = self._get_cache_key(text)
            cached = await self.redis_client.get(key)
            
            if cached:
                # Redis pode retornar string ou bytes
                if isinstance(cached, bytes):
                    cached = cached.decode()
                
                embedding = json.loads(cached)
                
                # Valida dimensionalidade
                if len(embedding) == self.embedder.EMBEDDING_DIMENSIONS:
                    return embedding
                else:
                    logger.warning(f"Cached embedding has wrong dimensions: {len(embedding)}")
                    return None
            
            return None
        except Exception as e:
            logger.debug(f"Cache get error: {e}")
            return None
    
    async def _set_in_cache(self, text: str, embedding: List[float]) -> None:
        """Armazena embedding no cache.
        
        Args:
            text: Texto
            embedding: Embedding a cachear
        """
        if not self.cache_config.enabled or self.redis_client is None:
            return
        
        try:
            key = self._get_cache_key(text)
            value = json.dumps(embedding)
            await self.redis_client.setex(
                key,
                self.cache_config.ttl_seconds,
                value,
            )
        except Exception as e:
            logger.debug(f"Cache set error: {e}")
    
    async def _embed_with_fallback(
        self,
        texts: List[str],
        use_fallback: bool = True,
    ) -> List[List[float]]:
        """Embed com fallback para backend local.
        
        Args:
            texts: Lista de textos
            use_fallback: Se pode usar fallback
            
        Returns:
            Lista de embeddings
        """
        try:
            # Tenta TEI primeiro
            embeddings = await self.embedder.embed_batch(texts)
            self.metrics.tei_requests += 1
            return embeddings
            
        except (CircuitBreakerOpenError, TEIConnectionError) as e:
            if not use_fallback or not self.fallback_backend:
                raise
            
            logger.warning(f"TEI unavailable, using fallback: {e}")
            embeddings = await self.fallback_backend.embed_batch(texts)
            self.metrics.fallback_requests += 1
            
            # Valida dimensionalidade do fallback também
            if embeddings and len(embeddings[0]) != self.embedder.EMBEDDING_DIMENSIONS:
                raise DimensionalityError(
                    f"Fallback embedding has {len(embeddings[0])} dimensions, "
                    f"expected {self.embedder.EMBEDDING_DIMENSIONS}"
                )
            
            return embeddings
    
    async def embed_batch(
        self,
        texts: List[str],
        use_cache: bool = True,
        use_fallback: bool = True,
    ) -> List[List[float]]:
        """Gera embeddings com cache, request coalescing e fallback.
        
        Args:
            texts: Lista de textos
            use_cache: Se deve usar cache
            use_fallback: Se deve usar fallback quando TEI falha
            
        Returns:
            Lista de embeddings (384 dimensões cada)
            
        Raises:
            EmbeddingError: Se não conseguir gerar embeddings
        """
        start_time = time.time()
        self.metrics.total_requests += 1
        
        if not texts:
            return []
        
        try:
            # Verifica cache e requests pendentes para cada texto
            results: List[Optional[List[float]]] = [None] * len(texts)
            missing_indices: List[int] = []
            missing_texts: List[str] = []
            pending_waits: List[tuple[int, str, asyncio.Future]] = []  # (index, cache_key, future)
            
            for i, text in enumerate(texts):
                cache_key = self._get_cache_key(text)
                
                # 1. Verifica cache primeiro
                if use_cache and self.cache_config.enabled:
                    cached = await self._get_from_cache(text)
                    if cached:
                        results[i] = cached
                        self.metrics.cache_hits += 1
                        continue
                
                # 2. Verifica request pendente (coalescing)
                if cache_key in self._pending:
                    pending_waits.append((i, cache_key, self._pending[cache_key]))
                    continue
                
                # 3. Precisa buscar
                missing_indices.append(i)
                missing_texts.append(text)
                self.metrics.cache_misses += 1
            
            # Aguarda requests pendentes (coalescing)
            for i, cache_key, future in pending_waits:
                try:
                    embedding = await future
                    results[i] = embedding
                    self.metrics.cache_hits += 1  # Hit via coalescing
                except Exception:
                    # Se falhar, adiciona para buscar novamente
                    missing_indices.append(i)
                    missing_texts.append(texts[i])
            
            # Se todos no cache ou coalescing, retorna
            if not missing_texts:
                duration = (time.time() - start_time) * 1000
                self.metrics.total_duration_ms += duration
                return results  # type: ignore
            
            # Cria futures para novos requests
            futures: Dict[str, asyncio.Future] = {}
            for text in missing_texts:
                cache_key = self._get_cache_key(text)
                future = asyncio.Future()
                self._pending[cache_key] = future
                futures[text] = future
            
            # Embed os que faltam
            try:
                embeddings = await self._embed_with_fallback(
                    missing_texts,
                    use_fallback=use_fallback,
                )
                
                # Preenche resultados, cacheia e completa futures
                for text, embedding in zip(missing_texts, embeddings):
                    cache_key = self._get_cache_key(text)
                    
                    # Encontra o índice original
                    for idx, t in zip(missing_indices, missing_texts):
                        if t == text:
                            results[idx] = embedding
                            break
                    
                    # Cacheia
                    if use_cache and self.cache_config.enabled:
                        await self._set_in_cache(text, embedding)
                    
                    # Completa o future para outros waiters
                    if cache_key in futures:
                        futures[text].set_result(embedding)
                        del self._pending[cache_key]
                        
            except Exception as e:
                # Propaga erro para todos os futures pendentes
                for text in missing_texts:
                    cache_key = self._get_cache_key(text)
                    if cache_key in futures and cache_key in self._pending:
                        futures[text].set_exception(e)
                        del self._pending[cache_key]
                raise
            
            duration = (time.time() - start_time) * 1000
            self.metrics.total_duration_ms += duration
            return results  # type: ignore
                
        except Exception as e:
            self.metrics.errors += 1
            logger.error(f"Embedding batch failed: {e}")
            raise EmbeddingError(f"Failed to generate embeddings: {e}") from e
    
    async def embed(
        self,
        texts: Union[str, List[str]],
        use_cache: bool = True,
        use_fallback: bool = True,
    ) -> Union[List[float], List[List[float]]]:
        """Gera embeddings para texto(s).
        
        Args:
            texts: Texto ou lista de textos
            use_cache: Se deve usar cache
            use_fallback: Se deve usar fallback
            
        Returns:
            Embedding único ou lista
        """
        if isinstance(texts, str):
            results = await self.embed_batch([texts], use_cache, use_fallback)
            return results[0]
        return await self.embed_batch(texts, use_cache, use_fallback)
    
    async def embed_chunks(
        self,
        chunks: List[Any],
        document_id: Optional[str] = None,
        use_cache: bool = True,
    ) -> EmbeddingResult:
        """Embed chunks com metadados.
        
        Args:
            chunks: Lista de objetos Chunk
            document_id: ID do documento
            use_cache: Se deve usar cache
            
        Returns:
            EmbeddingResult
        """
        start_time = time.time()
        
        if not chunks:
            return EmbeddingResult(
                chunks=[],
                document_id=document_id,
                model=self.embedder.model,
            )
        
        # Extrai textos e gera embeddings
        texts = [c.text for c in chunks]
        embeddings = await self.embed_batch(texts, use_cache=use_cache)
        
        # Cria EmbeddedChunks
        embedded_chunks = []
        total_tokens = 0
        
        for chunk, embedding in zip(chunks, embeddings):
            from datetime import datetime
            
            embedded_chunk = EmbeddedChunk(
                text=chunk.text,
                index=chunk.index,
                token_count=chunk.token_count,
                char_count=chunk.char_count,
                section_type=chunk.section_type,
                metadata=chunk.metadata,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                embedding=embedding,
                embedding_model=self.embedder.model,
                embedding_dimensions=self.embedder.EMBEDDING_DIMENSIONS,
                embedded_at=datetime.utcnow(),
            )
            embedded_chunks.append(embedded_chunk)
            total_tokens += chunk.token_count
        
        duration = time.time() - start_time
        
        return EmbeddingResult(
            chunks=embedded_chunks,
            document_id=document_id,
            model=self.embedder.model,
            batch_size=self.embedder.batch_size,
            total_embeddings=len(embedded_chunks),
            duration_seconds=duration,
            tokens_processed=total_tokens,
        )
    
    async def invalidate_cache(self, text: str) -> bool:
        """Invalida cache para texto específico.
        
        Args:
            text: Texto
            
        Returns:
            True se removeu do cache
        """
        if not self.cache_config.enabled or self.redis_client is None:
            return False
        
        try:
            key = self._get_cache_key(text)
            result = await self.redis_client.delete(key)
            return result > 0
        except Exception as e:
            logger.debug(f"Cache invalidate error: {e}")
            return False
    
    async def clear_cache(self, pattern: str = "*") -> int:
        """Limpa cache.
        
        Args:
            pattern: Padrão de chaves a limpar
            
        Returns:
            Número de chaves removidas
        """
        if not self.cache_config.enabled or self.redis_client is None:
            return 0
        
        try:
            full_pattern = f"{self.cache_config.prefix}{pattern}"
            keys = await self.redis_client.keys(full_pattern)
            if keys:
                return await self.redis_client.delete(*keys)
            return 0
        except Exception as e:
            logger.debug(f"Cache clear error: {e}")
            return 0
    
    def get_metrics(self) -> Dict[str, Any]:
        """Retorna métricas do serviço."""
        return {
            "total_requests": self.metrics.total_requests,
            "cache_hits": self.metrics.cache_hits,
            "cache_misses": self.metrics.cache_misses,
            "cache_hit_rate": self.metrics.cache_hit_rate,
            "tei_requests": self.metrics.tei_requests,
            "fallback_requests": self.metrics.fallback_requests,
            "errors": self.metrics.errors,
            "average_latency_ms": self.metrics.average_latency_ms,
            "cache_enabled": self.cache_config.enabled,
            "fallback_enabled": self.enable_fallback and self.fallback_backend is not None,
            "request_coalescing_enabled": True,
            "pending_requests": len(self._pending),
            "model": self.embedder.model,
            "dimensions": self.embedder.EMBEDDING_DIMENSIONS,
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Verifica saúde do serviço.
        
        Returns:
            Status de saúde
        """
        status = {
            "service": "embedding",
            "status": "healthy",
            "embedder": self.embedder.get_stats(),
            "cache": {
                "enabled": self.cache_config.enabled,
                "connected": self.redis_client is not None,
            },
            "fallback": {
                "enabled": self.enable_fallback,
                "available": self.fallback_backend is not None,
            },
        }
        
        # Verifica circuit breaker
        cb_state = self.embedder.circuit_breaker.state
        if cb_state.value == "open":
            status["status"] = "degraded"
            status["reason"] = "circuit_breaker_open"
        
        return status


# Import para corrigir referência
from gabi.pipeline.embedder import DimensionalityError
