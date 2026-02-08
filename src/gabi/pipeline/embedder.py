"""Embedder com conexão ao TEI (Text Embeddings Inference).

Implementa geração de embeddings 384-dimensionais via TEI com:
- Circuit breaker para falhas
- Retry com exponential backoff
- Validação de dimensionalidade (invariante ADR-001)
- Request coalescing para evitar duplicatas

Baseado em GABI_SPECS_FINAL_v1.md §2.3.8
"""

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

import aiohttp

from gabi.config import settings
from gabi.pipeline.contracts import EmbeddedChunk, EmbeddingResult

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitBreakerState(Enum):
    """Estados do Circuit Breaker."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class EmbeddingError(Exception):
    """Erro base para operações de embedding."""
    pass


class TEIConnectionError(EmbeddingError):
    """Erro de conexão com TEI."""
    pass


class TEIResponseError(EmbeddingError):
    """Erro na resposta do TEI."""
    pass


class DimensionalityError(EmbeddingError):
    """Erro de dimensionalidade - violação ADR-001."""
    pass


class CircuitBreakerOpenError(EmbeddingError):
    """Circuit breaker está aberto."""
    pass


@dataclass
class CircuitBreakerConfig:
    """Configuração do Circuit Breaker.
    
    Attributes:
        failure_threshold: Número de falhas antes de abrir
        recovery_timeout: Tempo em segundos antes de tentar recovery
        half_open_max_calls: Máximo de calls em half-open
    """
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3


@dataclass
class RetryConfig:
    """Configuração de Retry.
    
    Attributes:
        max_retries: Número máximo de tentativas
        base_delay: Delay inicial em segundos
        max_delay: Delay máximo em segundos
        exponential_base: Base para exponential backoff
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0


class CircuitBreaker:
    """Circuit Breaker para proteger contra falhas em cascata.
    
    Implementa padrão Circuit Breaker com estados:
    - CLOSED: Operação normal, passa requests
    - OPEN: Rejeita requests rapidamente
    - HALF_OPEN: Testa se serviço recuperou
    
    Baseado em GABI_SPECS_FINAL_v1.md §E-002
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig(
            failure_threshold=settings.embeddings_circuit_breaker_threshold,
            recovery_timeout=settings.embeddings_circuit_breaker_timeout,
        )
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
    
    @property
    def state(self) -> CircuitBreakerState:
        """Retorna estado atual do circuit breaker."""
        return self._state
    
    @property
    def is_open(self) -> bool:
        """Verifica se circuit breaker está aberto."""
        return self._state == CircuitBreakerState.OPEN
    
    @property
    def is_closed(self) -> bool:
        """Verifica se circuit breaker está fechado."""
        return self._state == CircuitBreakerState.CLOSED
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Executa função protegida pelo circuit breaker.
        
        Args:
            func: Função a ser executada
            *args: Argumentos posicionais
            **kwargs: Argumentos nomeados
            
        Returns:
            Resultado da função
            
        Raises:
            CircuitBreakerOpenError: Se circuit breaker está aberto
            Exception: Exceção original da função
        """
        async with self._lock:
            await self._update_state()
            
            if self._state == CircuitBreakerState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is OPEN. Last failure: "
                    f"{self._last_failure_time and time.time() - self._last_failure_time:.1f}s ago"
                )
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        "Circuit breaker is HALF_OPEN but max calls reached"
                    )
                self._half_open_calls += 1
        
        # Executa fora do lock
        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise
    
    async def _update_state(self) -> None:
        """Atualiza estado do circuit breaker baseado no tempo."""
        if self._state == CircuitBreakerState.OPEN:
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.config.recovery_timeout:
                    logger.info("Circuit breaker transitioning to HALF_OPEN")
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
    
    async def _on_success(self) -> None:
        """Registra sucesso."""
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.half_open_max_calls:
                    logger.info("Circuit breaker transitioning to CLOSED")
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._half_open_calls = 0
            else:
                self._failure_count = max(0, self._failure_count - 1)
    
    async def _on_failure(self) -> None:
        """Registra falha."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitBreakerState.HALF_OPEN:
                logger.warning("Circuit breaker transitioning to OPEN (failure in half-open)")
                self._state = CircuitBreakerState.OPEN
            elif self._failure_count >= self.config.failure_threshold:
                if self._state != CircuitBreakerState.OPEN:
                    logger.warning(f"Circuit breaker transitioning to OPEN ({self._failure_count} failures)")
                    self._state = CircuitBreakerState.OPEN
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do circuit breaker."""
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_calls": self._half_open_calls,
            "last_failure_time": self._last_failure_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
            },
        }


class Embedder:
    """Cliente para geração de embeddings via TEI.
    
    Responsabilidades:
    - Conectar ao servidor TEI
    - Gerar embeddings 384-dimensionais
    - Implementar circuit breaker e retry
    - Validar dimensionalidade (ADR-001)
    - Request coalescing para evitar chamadas duplicadas
    
    Attributes:
        base_url: URL base do servidor TEI
        model: Modelo de embeddings
        dimensions: Dimensionalidade (384 fixo)
        batch_size: Tamanho do batch
        timeout: Timeout em segundos
        circuit_breaker: Circuit breaker para proteção
    
    Baseado em GABI_SPECS_FINAL_v1.md §ADR-001
    """
    
    # Dimensionalidade fixa conforme ADR-001 - IMUTÁVEL
    EMBEDDING_DIMENSIONS: int = 384
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        circuit_breaker_config: Optional[CircuitBreakerConfig] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """Inicializa o Embedder.
        
        Args:
            base_url: URL do TEI (default: settings.embeddings_url)
            model: Modelo (default: settings.embeddings_model)
            batch_size: Tamanho do batch (default: settings.embeddings_batch_size)
            timeout: Timeout em segundos (default: settings.embeddings_timeout)
            max_retries: Máximo de retries (default: settings.embeddings_max_retries)
            circuit_breaker_config: Config do circuit breaker
            session: Sessão aiohttp opcional (para injeção em testes)
        """
        self.base_url = (base_url or settings.embeddings_url).rstrip("/")
        self.model = model or settings.embeddings_model
        self.batch_size = batch_size or settings.embeddings_batch_size
        self.timeout = timeout or settings.embeddings_timeout
        self.max_retries = max_retries or settings.embeddings_max_retries
        
        # Configuração de retry
        self.retry_config = RetryConfig(max_retries=self.max_retries)
        
        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(circuit_breaker_config)
        
        # Sessão HTTP
        self._session = session
        self._owns_session = session is None
        
        # Request coalescing: deduplica requests em andamento
        # Dict[str, asyncio.Future] - chave: hash do texto, valor: Future com resultado
        self._inflight_requests: Dict[str, asyncio.Future] = {}
        self._inflight_lock = asyncio.Lock()
        
        logger.info(
            f"Embedder initialized: model={self.model}, "
            f"dimensions={self.EMBEDDING_DIMENSIONS}, url={self.base_url}"
        )
    
    @property
    def _http_session(self) -> aiohttp.ClientSession:
        """Retorna sessão HTTP (lazy initialization)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"Content-Type": "application/json"},
            )
        return self._session
    
    async def close(self) -> None:
        """Fecha conexões."""
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    def _calculate_delay(self, attempt: int) -> float:
        """Calcula delay para exponential backoff.
        
        Args:
            attempt: Número da tentativa (0-indexed)
            
        Returns:
            Delay em segundos
        """
        delay = min(
            self.retry_config.base_delay * (self.retry_config.exponential_base ** attempt),
            self.retry_config.max_delay,
        )
        # Jitter para evitar thundering herd
        jitter = random.uniform(0, delay * 0.1)
        return delay + jitter
    
    async def _embed_batch_with_retry(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """Embed batch com retry e exponential backoff.
        
        Args:
            texts: Lista de textos para embeddar
            
        Returns:
            Lista de embeddings
            
        Raises:
            TEIConnectionError: Se não conseguir conectar após retries
            TEIResponseError: Se resposta for inválida
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.retry_config.max_retries + 1):
            try:
                return await self._embed_batch_request(texts)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_exception = e
                if attempt < self.retry_config.max_retries:
                    delay = self._calculate_delay(attempt)
                    logger.warning(
                        f"TEI request failed (attempt {attempt + 1}), "
                        f"retrying in {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise TEIConnectionError(
                        f"Failed to connect to TEI after {self.retry_config.max_retries + 1} attempts"
                    ) from e
            except Exception as e:
                # Não faz retry para erros não-transientes
                raise
        
        raise TEIConnectionError("Unexpected end of retry loop") from last_exception
    
    async def _embed_batch_request(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """Faz requisição ao TEI.
        
        Args:
            texts: Lista de textos
            
        Returns:
            Lista de embeddings
        """
        url = f"{self.base_url}/embed"
        
        # TEI aceita lista de textos diretamente
        payload = {"inputs": texts}
        
        async with self._http_session.post(url, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                raise TEIResponseError(
                    f"TEI returned status {response.status}: {text[:200]}"
                )
            
            data = await response.json()
            
            # TEI retorna lista de embeddings
            if isinstance(data, list):
                embeddings = data
            elif isinstance(data, dict) and "embeddings" in data:
                embeddings = data["embeddings"]
            else:
                raise TEIResponseError(f"Unexpected response format: {type(data)}")
            
            return embeddings
    
    def _validate_embeddings(
        self,
        embeddings: List[List[float]],
        expected_count: int,
    ) -> None:
        """Valida embeddings conforme ADR-001.
        
        Args:
            embeddings: Lista de embeddings
            expected_count: Número esperado de embeddings
            
        Raises:
            DimensionalityError: Se dimensionalidade != 384
            TEIResponseError: Se número de embeddings incorreto
        """
        if len(embeddings) != expected_count:
            raise TEIResponseError(
                f"Expected {expected_count} embeddings, got {len(embeddings)}"
            )
        
        for i, embedding in enumerate(embeddings):
            if len(embedding) != self.EMBEDDING_DIMENSIONS:
                raise DimensionalityError(
                    f"CRITICAL: Embedding dimensionality is {len(embedding)}, "
                    f"expected {self.EMBEDDING_DIMENSIONS} (ADR-001). "
                    f"Embedding index: {i}. This is a violation of the architecture!"
                )
    
    def _get_inflight_key(self, text: str) -> str:
        """Gera chave única para request coalescing.
        
        Args:
            text: Texto para gerar chave
            
        Returns:
            Chave hash única
        """
        content = f"{self.model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def embed_batch(
        self,
        chunks: List[str],
    ) -> List[List[float]]:
        """Gera embeddings para lista de chunks.
        
        Principal método de embedding com:
        - Circuit breaker
        - Retry com exponential backoff
        - Validação de dimensionalidade 384 (ADR-001)
        - Batching automático
        - Request coalescing para deduplicar requests em andamento
        
        Args:
            chunks: Lista de textos para embeddar
            
        Returns:
            Lista de embeddings (384 dimensões cada)
            
        Raises:
            CircuitBreakerOpenError: Se circuit breaker está aberto
            DimensionalityError: Se dimensionalidade for diferente de 384
            TEIConnectionError: Se não conseguir conectar ao TEI
            TEIResponseError: Se resposta for inválida
            
        Example:
            >>> embedder = Embedder()
            >>> chunks = ["texto 1", "texto 2"]
            >>> embeddings = await embedder.embed_batch(chunks)
            >>> len(embeddings[0])
            384
        """
        if not chunks:
            return []
        
        # Remove strings vazias mas mantém posição para resultado
        non_empty_indices = [i for i, text in enumerate(chunks) if text.strip()]
        non_empty_chunks = [chunks[i] for i in non_empty_indices]
        
        if not non_empty_chunks:
            # Todos vazios - retorna zeros
            return [[0.0] * self.EMBEDDING_DIMENSIONS for _ in chunks]
        
        # Aplica request coalescing: agrupa textos únicos
        unique_texts: Dict[str, int] = {}  # text -> first index
        text_to_indices: Dict[str, List[int]] = {}  # text -> all indices
        
        for idx, text in zip(non_empty_indices, non_empty_chunks):
            if text not in unique_texts:
                unique_texts[text] = idx
                text_to_indices[text] = [idx]
            else:
                text_to_indices[text].append(idx)
        
        unique_chunks = list(unique_texts.keys())
        unique_embeddings: Dict[str, List[float]] = {}
        
        # Processa em batches
        for batch_start in range(0, len(unique_chunks), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(unique_chunks))
            batch = unique_chunks[batch_start:batch_end]
            
            # Usa request coalescing para evitar duplicatas em andamento
            batch_embeddings = await self._embed_batch_with_coalescing(batch)
            
            # Mapeia resultados
            for text, embedding in zip(batch, batch_embeddings):
                unique_embeddings[text] = embedding
        
        # Reconstrói resultado na ordem original
        all_embeddings: List[Optional[List[float]]] = [None] * len(chunks)
        
        for text, indices in text_to_indices.items():
            embedding = unique_embeddings[text]
            for idx in indices:
                all_embeddings[idx] = embedding
        
        # Preenche embeddings vazios (para chunks vazios)
        zero_embedding = [0.0] * self.EMBEDDING_DIMENSIONS
        for i in range(len(all_embeddings)):
            if all_embeddings[i] is None:
                all_embeddings[i] = zero_embedding
        
        return all_embeddings  # type: ignore
    
    async def _embed_batch_with_coalescing(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """Embed batch com request coalescing.
        
        Deduplica requests em andamento para o mesmo texto,
        retornando o mesmo resultado para múltiplas chamadas simultâneas.
        
        Args:
            texts: Lista de textos únicos para embeddar
            
        Returns:
            Lista de embeddings na mesma ordem
        """
        results: Dict[str, List[float]] = {}
        pending_texts: List[str] = []
        pending_keys: List[str] = []
        
        # Verifica requests em andamento
        async with self._inflight_lock:
            for text in texts:
                key = self._get_inflight_key(text)
                if key in self._inflight_requests:
                    # Já existe request em andamento - aguarda
                    future = self._inflight_requests[key]
                    try:
                        # Tenta obter resultado de request existente
                        result = await asyncio.wait_for(
                            asyncio.shield(future),
                            timeout=self.timeout * 2
                        )
                        results[text] = result
                    except (asyncio.TimeoutError, Exception):
                        # Falhou - processa novamente
                        pending_texts.append(text)
                        pending_keys.append(key)
                else:
                    # Cria novo request
                    future = asyncio.Future()
                    self._inflight_requests[key] = future
                    pending_texts.append(text)
                    pending_keys.append(key)
        
        if pending_texts:
            try:
                # Processa via circuit breaker
                embeddings = await self.circuit_breaker.call(
                    self._embed_batch_with_retry,
                    pending_texts,
                )
                
                # Valida dimensionalidade - INVARIANTE ADR-001
                self._validate_embeddings(embeddings, len(pending_texts))
                
                # Preenche resultados e notifica futures
                for text, key, embedding in zip(pending_texts, pending_keys, embeddings):
                    results[text] = embedding
                    async with self._inflight_lock:
                        future = self._inflight_requests.pop(key, None)
                        if future and not future.done():
                            future.set_result(embedding)
                            
            except Exception as e:
                # Notifica futures de falha
                for key in pending_keys:
                    async with self._inflight_lock:
                        future = self._inflight_requests.pop(key, None)
                        if future and not future.done():
                            future.set_exception(e)
                raise
        
        # Retorna resultados na ordem original
        return [results[text] for text in texts]
    
    async def embed(
        self,
        texts: Union[str, List[str]],
    ) -> Union[List[float], List[List[float]]]:
        """Gera embeddings para texto(s).
        
        Método conveniente que aceita string única ou lista.
        
        Args:
            texts: Texto ou lista de textos
            
        Returns:
            Embedding único ou lista de embeddings
        """
        if isinstance(texts, str):
            results = await self.embed_batch([texts])
            return results[0]
        return await self.embed_batch(texts)
    
    async def embed_chunks(
        self,
        chunks: List[Any],
        document_id: Optional[str] = None,
    ) -> EmbeddingResult:
        """Embed chunks com metadados.
        
        Args:
            chunks: Lista de objetos Chunk
            document_id: ID do documento
            
        Returns:
            EmbeddingResult com chunks embeddados
        """
        start_time = time.time()
        
        if not chunks:
            return EmbeddingResult(
                chunks=[],
                document_id=document_id,
                model=self.model,
                batch_size=self.batch_size,
            )
        
        # Extrai textos
        texts = [c.text for c in chunks]
        
        # Gera embeddings
        embeddings = await self.embed_batch(texts)
        
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
                embedding_model=self.model,
                embedding_dimensions=self.EMBEDDING_DIMENSIONS,
                embedded_at=datetime.utcnow(),
            )
            embedded_chunks.append(embedded_chunk)
            total_tokens += chunk.token_count
        
        duration = time.time() - start_time
        
        return EmbeddingResult(
            chunks=embedded_chunks,
            document_id=document_id,
            model=self.model,
            batch_size=self.batch_size,
            total_embeddings=len(embedded_chunks),
            duration_seconds=duration,
            tokens_processed=total_tokens,
        )
    
    def get_cache_key(self, text: str) -> str:
        """Gera chave de cache para texto.
        
        Args:
            text: Texto
            
        Returns:
            Chave de cache (hash)
        """
        content = f"{self.model}:{text}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do embedder."""
        return {
            "model": self.model,
            "dimensions": self.EMBEDDING_DIMENSIONS,
            "base_url": self.base_url,
            "batch_size": self.batch_size,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "circuit_breaker": self.circuit_breaker.get_stats(),
        }
