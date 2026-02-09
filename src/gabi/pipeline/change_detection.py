"""Engine de detecção de mudanças em URLs.

Detecta alterações em recursos remotos através de:
1. ETag (header HTTP)
2. Last-Modified (header HTTP)
3. Content-Length (header HTTP)
4. Content-Hash (SHA-256 do conteúdo)

Cache persistente em PostgreSQL via ChangeDetectionCache.

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.
"""

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

import httpx
from sqlalchemy import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from gabi.pipeline.contracts import ChangeCheckResult, ChangeDetectionSummary
from gabi.models.cache import ChangeDetectionCache
from gabi.types import ChangeDetectionResult
from gabi.db import get_session, DatabaseManager


logger = logging.getLogger(__name__)


@dataclass
class URLCheckRequest:
    """Requisição para verificação de URL.
    
    Attributes:
        url: URL a ser verificada
        source_id: ID da fonte
        priority: Prioridade da verificação
    """
    url: str
    source_id: str
    priority: int = 0


@dataclass
class HTTPHeaders:
    """Headers HTTP relevantes para detecção de mudança.
    
    Attributes:
        etag: Header ETag
        last_modified: Header Last-Modified
        content_length: Content-Length em bytes
        content_type: Content-Type
    """
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    content_length: Optional[int] = None
    content_type: Optional[str] = None


class ChangeDetector:
    """Detector de mudanças em URLs.
    
    Implementa estratégias de detecção:
    1. ETag (mais confiável)
    2. Last-Modified
    3. Content-Length
    4. Content-Hash (SHA-256, fallback)
    
    Usa HTTP HEAD primeiro para eficiência,
    faz GET completo apenas quando necessário.
    
    Cache persistente em PostgreSQL.
    
    Example:
        detector = ChangeDetector()
        
        # Verificação única
        result = await detector.check_url("https://example.com/doc.pdf", "source_1")
        
        # Verificação em batch
        urls = [URLCheckRequest("https://a.com", "s1"), ...]
        summary = await detector.check_batch(urls)
    """
    
    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        user_agent: str = "GABI-ChangeDetector/1.0"
    ):
        """Inicializa o detector de mudanças.
        
        Args:
            db_manager: DatabaseManager para operações de cache
            timeout: Timeout para requisições HTTP
            max_retries: Número máximo de retries
            user_agent: User-Agent para requisições
        """
        self.db_manager = db_manager
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self._client: Optional[httpx.AsyncClient] = None

    def _get_db_manager(self) -> DatabaseManager:
        """Inicializa DatabaseManager sob demanda.
        
        Evita inicializar o engine antes do necessário.
        """
        if self.db_manager is None:
            self.db_manager = DatabaseManager()
        return self.db_manager
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Obtém ou cria cliente HTTP.
        
        Returns:
            Cliente HTTP async
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True
            )
        return self._client
    
    async def close(self) -> None:
        """Fecha o cliente HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def __aenter__(self):
        """Context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
    
    def _extract_headers(self, response: httpx.Response) -> HTTPHeaders:
        """Extrai headers relevantes de uma resposta HTTP.
        
        Args:
            response: Resposta HTTP
            
        Returns:
            Headers extraídos
        """
        headers = response.headers
        
        content_length = None
        if "content-length" in headers:
            try:
                content_length = int(headers["content-length"])
            except (ValueError, TypeError):
                pass
        
        return HTTPHeaders(
            etag=headers.get("etag"),
            last_modified=headers.get("last-modified"),
            content_length=content_length,
            content_type=headers.get("content-type")
        )
    
    def _compute_content_hash(self, content: bytes) -> str:
        """Computa hash SHA-256 do conteúdo.
        
        Args:
            content: Conteúdo em bytes
            
        Returns:
            Hash SHA-256 hexadecimal
        """
        return hashlib.sha256(content).hexdigest()
    
    def _parse_http_date(self, date_str: Optional[str]) -> Optional[float]:
        """Parse HTTP date string to Unix timestamp.
        
        Handles RFC 7232 format variations:
        - IMF-fixdate: Sun, 06 Nov 1994 08:49:37 GMT
        - RFC 850: Sunday, 06-Nov-94 08:49:37 GMT
        - ANSI C's asctime(): Sun Nov  6 08:49:37 1994
        
        Args:
            date_str: Date string from HTTP header
            
        Returns:
            Unix timestamp or None if parsing fails
        """
        if not date_str:
            return None
        
        # RFC 7231 date formats
        formats = [
            "%a, %d %b %Y %H:%M:%S GMT",      # IMF-fixdate
            "%A, %d-%b-%y %H:%M:%S GMT",       # RFC 850
            "%a %b %d %H:%M:%S %Y",            # ANSI C asctime
        ]
        
        date_str = date_str.strip()
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Assume GMT/UTC for all HTTP dates
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except ValueError:
                continue
        
        # Try ISO format as fallback
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            pass
        
        logger.debug(f"Failed to parse date: {date_str}")
        return None
    
    def _detect_change_method(
        self,
        cached: Optional[ChangeDetectionCache],
        headers: HTTPHeaders,
        content_hash: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Detecta mudança comparando valores atuais com cache.
        
        Prioridade de detecção:
        1. ETag (mais confiável)
        2. Last-Modified (with timestamp comparison for clock skew)
        3. Content-Length
        4. Content-Hash (fallback)
        
        Args:
            cached: Entrada em cache (pode ser None para URLs novas)
            headers: Headers HTTP atuais
            content_hash: Hash do conteúdo (se disponível)
            
        Returns:
            Tuple (has_changed, method_used)
        """
        # URL nova - considera como mudança
        if cached is None:
            # Determina o método que será usado para tracking futuro
            if headers.etag:
                return True, "etag"
            elif headers.last_modified:
                return True, "last_modified"
            elif headers.content_length is not None:
                return True, "content_length"
            elif content_hash:
                return True, "content_hash"
            return True, "none"
        
        # Prioridade 1: ETag
        if cached.etag and headers.etag:
            return cached.etag != headers.etag, "etag"
        
        # Prioridade 2: Last-Modified (with proper date parsing)
        if cached.last_modified and headers.last_modified:
            cached_ts = self._parse_http_date(cached.last_modified)
            current_ts = self._parse_http_date(headers.last_modified)
            
            if cached_ts is not None and current_ts is not None:
                # Allow 2-second tolerance for clock skew
                return abs(cached_ts - current_ts) > 2, "last_modified"
            else:
                # Fallback to string comparison if parsing fails
                return cached.last_modified != headers.last_modified, "last_modified"
        
        # Prioridade 3: Content-Length
        if cached.content_length is not None and headers.content_length is not None:
            return cached.content_length != headers.content_length, "content_length"
        
        # Prioridade 4: Content-Hash
        if cached.content_hash and content_hash:
            return cached.content_hash != content_hash, "content_hash"
        
        # Sem mecanismo de comparação = assumir mudança
        return True, "unknown"
    
    async def _get_or_create_cache(
        self,
        session: AsyncSession,
        url: str,
        source_id: str
    ) -> Optional[ChangeDetectionCache]:
        """Obtém entrada do cache ou retorna None se não existir.
        
        Args:
            session: Sessão do banco de dados
            url: URL do recurso
            source_id: ID da fonte
            
        Returns:
            Entrada do cache ou None
        """
        statement = select(ChangeDetectionCache).where(
            and_(
                ChangeDetectionCache.source_id == source_id,
                ChangeDetectionCache.url == url
            )
        )
        result = await session.execute(statement)
        return result.scalar_one_or_none()
    
    async def _update_cache(
        self,
        session: AsyncSession,
        url: str,
        source_id: str,
        headers: HTTPHeaders,
        content_hash: Optional[str] = None,
        changed: bool = False
    ) -> ChangeDetectionCache:
        """Atualiza ou cria entrada no cache.
        
        Args:
            session: Sessão do banco de dados
            url: URL do recurso
            source_id: ID da fonte
            headers: Headers HTTP
            content_hash: Hash do conteúdo
            changed: Se houve mudança detectada
            
        Returns:
            Entrada atualizada do cache
        """
        cached = await self._get_or_create_cache(session, url, source_id)
        
        now = datetime.utcnow()
        
        if cached is None:
            # Cria nova entrada
            cached = ChangeDetectionCache(
                source_id=source_id,
                url=url,
                etag=headers.etag,
                last_modified=headers.last_modified,
                content_length=headers.content_length,
                content_hash=content_hash,
                last_checked_at=now,
                last_changed_at=now if changed else None,
                check_count=1,
                change_count=1 if changed else 0
            )
            session.add(cached)
        else:
            # Atualiza entrada existente
            if headers.etag:
                cached.etag = headers.etag
            if headers.last_modified:
                cached.last_modified = headers.last_modified
            if headers.content_length is not None:
                cached.content_length = headers.content_length
            if content_hash:
                cached.content_hash = content_hash
                
            cached.last_checked_at = now
            cached.check_count += 1
            
            if changed:
                cached.last_changed_at = now
                cached.change_count += 1
        
        await session.commit()
        await session.refresh(cached)
        return cached
    
    async def _do_head_request(self, url: str) -> Tuple[Optional[HTTPHeaders], Optional[str]]:
        """Executa requisição HEAD para obter headers.
        
        Args:
            url: URL do recurso
            
        Returns:
            Tuple (headers, error_message)
        """
        client = await self._get_client()
        
        for attempt in range(self.max_retries):
            try:
                response = await client.head(url)
                response.raise_for_status()
                return self._extract_headers(response), None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 405:  # Method Not Allowed
                    # HEAD não suportado, retornar sem erro
                    return None, None
                if attempt == self.max_retries - 1:
                    return None, f"HTTP {e.response.status_code}"
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            except httpx.RequestError as e:
                if attempt == self.max_retries - 1:
                    return None, str(e)
                await asyncio.sleep(2 ** attempt)
        
        return None, "Max retries exceeded"
    
    async def _do_get_request(
        self,
        url: str,
        compute_hash: bool = True
    ) -> Tuple[Optional[HTTPHeaders], Optional[str], Optional[bytes], Optional[str]]:
        """Executa requisição GET para obter headers e conteúdo.
        
        Args:
            url: URL do recurso
            compute_hash: Se deve computar hash do conteúdo
            
        Returns:
            Tuple (headers, content_hash, content_bytes, error_message)
        """
        client = await self._get_client()
        
        for attempt in range(self.max_retries):
            try:
                response = await client.get(url)
                response.raise_for_status()
                
                headers = self._extract_headers(response)
                content_hash = None
                content_bytes = None
                
                if compute_hash:
                    # Stream content and compute hash incrementally
                    hasher = hashlib.sha256()
                    chunks = []
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        hasher.update(chunk)
                        chunks.append(chunk)
                    content_hash = hasher.hexdigest()
                    content_bytes = b"".join(chunks)
                
                return headers, content_hash, content_bytes, None
            except httpx.HTTPStatusError as e:
                if attempt == self.max_retries - 1:
                    return None, None, None, f"HTTP {e.response.status_code}"
                await asyncio.sleep(2 ** attempt)
            except httpx.RequestError as e:
                if attempt == self.max_retries - 1:
                    return None, None, None, str(e)
                await asyncio.sleep(2 ** attempt)
        
        return None, None, None, "Max retries exceeded"
    
    async def check_url(
        self,
        url: str,
        source_id: str,
        force_refresh: bool = False
    ) -> ChangeCheckResult:
        """Verifica mudanças em uma única URL.
        
        Estratégia:
        1. Verifica cache existente
        2. Faz HEAD request
        3. Se necessário, faz GET request
        4. Compara e atualiza cache
        
        Args:
            url: URL a verificar
            source_id: ID da fonte
            force_refresh: Ignora cache e força nova verificação
            
        Returns:
            Resultado da verificação
        """
        start_time = time.monotonic()
        
        try:
            db_manager = self._get_db_manager()
            async with db_manager.session() as session:
                # Obtém cache existente
                cached = None
                if not force_refresh:
                    cached = await self._get_or_create_cache(session, url, source_id)
                
                # Tenta HEAD primeiro
                head_headers, head_error = await self._do_head_request(url)
                
                if head_error:
                    # Erro definitivo no HEAD
                    logger.warning(f"HEAD falhou para {url}: {head_error}")
                    return ChangeCheckResult(
                        url=url,
                        result=ChangeDetectionResult.ERROR,
                        etag=None,
                        last_modified=None,
                        content_hash=None,
                        content_length=None,
                        previous_check=cached.last_checked_at if cached else None,
                        current_check=datetime.utcnow()
                    )
                
                # Determina se precisa fazer GET
                need_content_hash = False
                
                if head_headers is None:
                    # HEAD não suportado (405), precisa fazer GET
                    need_content_hash = True
                elif cached is None:
                    # URL nova - se não tem ETag ou Last-Modified, precisa de hash
                    if not head_headers.etag and not head_headers.last_modified:
                        need_content_hash = True
                else:
                    # URL existente - verifica se precisa de hash para comparar
                    if not cached.etag and not cached.last_modified:
                        if not head_headers.etag and not head_headers.last_modified:
                            need_content_hash = True
                
                # Faz GET se necessário
                content_hash = None
                content_bytes = None
                final_headers = head_headers
                
                if need_content_hash:
                    get_headers, content_hash, content_bytes, get_error = await self._do_get_request(url)
                    
                    if get_error:
                        logger.warning(f"GET falhou para {url}: {get_error}")
                        return ChangeCheckResult(
                            url=url,
                            result=ChangeDetectionResult.ERROR,
                            etag=head_headers.etag if head_headers else None,
                            last_modified=head_headers.last_modified if head_headers else None,
                            content_hash=None,
                            content_length=head_headers.content_length if head_headers else None,
                            previous_check=cached.last_checked_at if cached else None,
                            current_check=datetime.utcnow()
                        )
                    
                    # Usa headers do GET se HEAD não funcionou
                    if final_headers is None:
                        final_headers = get_headers
                
                # Detecta mudança
                if final_headers is None:
                    final_headers = HTTPHeaders()
                
                has_changed, method = self._detect_change_method(
                    cached, final_headers, content_hash
                )
                
                # Determina resultado
                if cached is None:
                    result = ChangeDetectionResult.NEW
                elif has_changed:
                    result = ChangeDetectionResult.CHANGED
                else:
                    result = ChangeDetectionResult.UNCHANGED
                
                # Atualiza cache
                await self._update_cache(
                    session, url, source_id,
                    final_headers, content_hash,
                    changed=has_changed
                )
                
                duration = time.monotonic() - start_time
                logger.debug(
                    f"Change check {url}: {result.value} "
                    f"(method={method}, duration={duration:.3f}s)"
                )
                
                return ChangeCheckResult(
                    url=url,
                    result=result,
                    etag=final_headers.etag,
                    last_modified=final_headers.last_modified,
                    content_hash=content_hash,
                    content_length=final_headers.content_length,
                    previous_check=cached.last_checked_at if cached else None,
                    current_check=datetime.utcnow()
                )
                
        except Exception as e:
            logger.error(f"Erro ao verificar {url}: {e}")
            return ChangeCheckResult(
                url=url,
                result=ChangeDetectionResult.ERROR,
                etag=None,
                last_modified=None,
                content_hash=None,
                content_length=None,
                previous_check=None,
                current_check=datetime.utcnow()
            )
    
    async def check_batch(
        self,
        urls: List[URLCheckRequest],
        max_concurrent: int = 10
    ) -> ChangeDetectionSummary:
        """Verifica mudanças em múltiplas URLs.
        
        Args:
            urls: Lista de requisições de verificação
            max_concurrent: Número máximo de verificações paralelas
            
        Returns:
            Resumo da verificação
        """
        import asyncio
        
        start_time = time.monotonic()
        
        new_urls: List[str] = []
        changed_urls: List[str] = []
        unchanged_urls: List[str] = []
        error_urls: List[str] = []
        
        # Cria semáforo para limitar concorrência
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def check_with_semaphore(req: URLCheckRequest) -> ChangeCheckResult:
            async with semaphore:
                return await self.check_url(req.url, req.source_id)
        
        # Executa verificações em paralelo
        tasks = [check_with_semaphore(req) for req in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Processa resultados
        for req, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error(f"Erro na verificação de {req.url}: {result}")
                error_urls.append(req.url)
                continue
            
            if result.result == ChangeDetectionResult.NEW:
                new_urls.append(req.url)
            elif result.result == ChangeDetectionResult.CHANGED:
                changed_urls.append(req.url)
            elif result.result == ChangeDetectionResult.UNCHANGED:
                unchanged_urls.append(req.url)
            else:  # ERROR
                error_urls.append(req.url)
        
        duration = time.monotonic() - start_time
        
        logger.info(
            f"Batch change detection completo: "
            f"{len(new_urls)} new, {len(changed_urls)} changed, "
            f"{len(unchanged_urls)} unchanged, {len(error_urls)} errors, "
            f"{duration:.2f}s"
        )
        
        return ChangeDetectionSummary(
            new_urls=new_urls,
            changed_urls=changed_urls,
            unchanged_urls=unchanged_urls,
            error_urls=error_urls,
            total_checked=len(urls),
            duration_seconds=duration
        )
    
    async def get_cache_stats(
        self,
        source_id: Optional[str] = None
    ) -> Dict[str, int]:
        """Obtém estatísticas do cache.
        
        Args:
            source_id: Filtrar por fonte (opcional)
            
        Returns:
            Estatísticas do cache
        """
        db_manager = self._get_db_manager()
        async with db_manager.session_no_commit() as session:
            statement = select(ChangeDetectionCache)
            
            if source_id:
                statement = statement.where(ChangeDetectionCache.source_id == source_id)
            
            result = await session.execute(statement)
            entries = result.scalars().all()
            
            total = len(entries)
            with_etag = sum(1 for e in entries if e.etag)
            with_last_modified = sum(1 for e in entries if e.last_modified)
            with_content_hash = sum(1 for e in entries if e.content_hash)
            total_checks = sum(e.check_count for e in entries)
            total_changes = sum(e.change_count for e in entries)
            
            return {
                "total_entries": total,
                "with_etag": with_etag,
                "with_last_modified": with_last_modified,
                "with_content_hash": with_content_hash,
                "total_checks": total_checks,
                "total_changes": total_changes,
            }
    
    async def clear_cache(
        self,
        source_id: Optional[str] = None,
        older_than: Optional[datetime] = None
    ) -> int:
        """Limpa entradas do cache.
        
        Args:
            source_id: Limpar apenas de uma fonte
            older_than: Limpar entradas mais antigas que
            
        Returns:
            Número de entradas removidas
        """
        from sqlalchemy import delete
        
        db_manager = self._get_db_manager()
        async with db_manager.session() as session:
            statement = delete(ChangeDetectionCache)
            
            conditions = []
            if source_id:
                conditions.append(ChangeDetectionCache.source_id == source_id)
            if older_than:
                conditions.append(ChangeDetectionCache.last_checked_at < older_than)
            
            if conditions:
                statement = statement.where(and_(*conditions))
            
            result = await session.execute(statement)
            await session.commit()
            
            deleted = result.rowcount
            logger.info(f"Cache limpo: {deleted} entradas removidas")
            return deleted


# Singleton global
try:
    change_detector = ChangeDetector()
except RuntimeError as exc:
    logger.warning("ChangeDetector singleton not initialized: %s", exc)
    change_detector = None


# Exportações
__all__ = [
    "ChangeDetector",
    "URLCheckRequest",
    "HTTPHeaders",
    "change_detector",
]
