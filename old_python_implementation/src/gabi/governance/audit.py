"""Sistema de auditoria do GABI.

Registra eventos de auditoria com hash chain para integridade,
suporte a compliance e investigação.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (audit_log).
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import select, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.types import AuditEventType, AuditSeverity
from gabi.models.audit import AuditLog
from gabi.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """Evento de auditoria.
    
    Attributes:
        event_type: Tipo do evento
        severity: Severidade
        user_id: ID do usuário
        user_email: Email do usuário
        session_id: ID da sessão
        ip_address: Endereço IP
        user_agent: User agent
        resource_type: Tipo do recurso
        resource_id: ID do recurso
        action_details: Detalhes da ação
        before_state: Estado anterior
        after_state: Estado posterior
        request_id: ID da requisição
        correlation_id: ID de correlação
    """
    event_type: AuditEventType
    severity: AuditSeverity = AuditSeverity.INFO
    
    # Usuário
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    # Recurso
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    
    # Detalhes
    action_details: Dict[str, Any] = field(default_factory=dict)
    before_state: Optional[Dict[str, Any]] = None
    after_state: Optional[Dict[str, Any]] = None
    
    # Tracing
    request_id: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "user_id": self.user_id,
            "user_email": self.user_email,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "action_details": self.action_details,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
        }


@dataclass
class AuditQuery:
    """Query para busca de eventos de auditoria.
    
    Attributes:
        event_types: Tipos de evento
        severities: Severidades
        user_ids: IDs de usuário
        resource_types: Tipos de recurso
        resource_ids: IDs de recurso
        start_date: Data inicial
        end_date: Data final
        request_id: ID da requisição
        limit: Limite de resultados
        offset: Offset para paginação
    """
    event_types: Optional[List[AuditEventType]] = None
    severities: Optional[List[AuditSeverity]] = None
    user_ids: Optional[List[str]] = None
    resource_types: Optional[List[str]] = None
    resource_ids: Optional[List[str]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    request_id: Optional[str] = None
    limit: int = 100
    offset: int = 0


class AuditLogger:
    """Logger de auditoria do GABI.
    
    Registra eventos com hash chain para garantia de integridade.
    Implementa logging estruturado para compliance.
    
    Attributes:
        db_session: Sessão do banco de dados
        enabled: Se auditoria está habilitada
        sync_to_console: Se deve logar também no console
    """
    
    def __init__(
        self,
        db_session: AsyncSession,
        enabled: bool = True,
        sync_to_console: bool = False,
    ):
        self.db_session = db_session
        self.enabled = enabled and settings.audit_enabled
        self.sync_to_console = sync_to_console
        self._last_hash: Optional[str] = None
        logger.info(f"AuditLogger inicializado (enabled={self.enabled})")
    
    async def log(
        self,
        event: AuditEvent,
    ) -> Optional[AuditLog]:
        """Registra evento de auditoria.
        
        Args:
            event: Evento a registrar
            
        Returns:
            Registro criado ou None se desabilitado
        """
        if not self.enabled:
            return None
        
        try:
            # Obtém hash anterior
            previous_hash = await self._get_last_hash()
            
            # Calcula hash do evento
            event_hash = self._calculate_hash(event, previous_hash)
            
            # Cria registro
            audit_record = AuditLog(
                event_type=event.event_type,
                severity=event.severity,
                user_id=event.user_id,
                user_email=event.user_email,
                session_id=event.session_id,
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                action_details=event.action_details,
                before_state=event.before_state,
                after_state=event.after_state,
                previous_hash=previous_hash,
                event_hash=event_hash,
                request_id=event.request_id,
                correlation_id=event.correlation_id,
            )
            
            self.db_session.add(audit_record)
            await self.db_session.commit()
            
            self._last_hash = event_hash
            
            # Log no console se configurado
            if self.sync_to_console:
                logger.info(f"AUDIT: {event.event_type.value} - {event.resource_type}:{event.resource_id}")
            
            return audit_record
            
        except Exception as e:
            logger.error(f"Erro ao registrar auditoria: {e}")
            await self.db_session.rollback()
            return None
    
    async def log_simple(
        self,
        event_type: AuditEventType,
        resource_type: str,
        resource_id: Optional[str] = None,
        severity: AuditSeverity = AuditSeverity.INFO,
        user_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditLog]:
        """Registra evento simples.
        
        Args:
            event_type: Tipo do evento
            resource_type: Tipo do recurso
            resource_id: ID do recurso
            severity: Severidade
            user_id: ID do usuário
            details: Detalhes adicionais
            
        Returns:
            Registro criado ou None
        """
        event = AuditEvent(
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=severity,
            user_id=user_id,
            action_details=details or {},
        )
        return await self.log(event)
    
    # Métodos de conveniência para eventos comuns
    
    async def log_document_viewed(
        self,
        document_id: str,
        user_id: Optional[str] = None,
        user_email: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """Registra visualização de documento."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DOCUMENT_VIEWED,
            resource_type="document",
            resource_id=document_id,
            user_id=user_id,
            user_email=user_email,
            request_id=request_id,
        ))
    
    async def log_document_searched(
        self,
        query: str,
        result_count: int,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """Registra busca de documentos."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DOCUMENT_SEARCHED,
            resource_type="search",
            user_id=user_id,
            request_id=request_id,
            action_details={"query": query, "result_count": result_count},
        ))
    
    async def log_document_created(
        self,
        document_id: str,
        source_id: str,
        user_id: Optional[str] = None,
        before_state: Optional[Dict] = None,
        after_state: Optional[Dict] = None,
    ) -> Optional[AuditLog]:
        """Registra criação de documento."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DOCUMENT_CREATED,
            resource_type="document",
            resource_id=document_id,
            user_id=user_id,
            action_details={"source_id": source_id},
            before_state=before_state,
            after_state=after_state,
        ))
    
    async def log_document_updated(
        self,
        document_id: str,
        user_id: Optional[str] = None,
        before_state: Optional[Dict] = None,
        after_state: Optional[Dict] = None,
    ) -> Optional[AuditLog]:
        """Registra atualização de documento."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DOCUMENT_UPDATED,
            severity=AuditSeverity.WARNING,
            resource_type="document",
            resource_id=document_id,
            user_id=user_id,
            before_state=before_state,
            after_state=after_state,
        ))
    
    async def log_document_deleted(
        self,
        document_id: str,
        user_id: Optional[str] = None,
        reason: Optional[str] = None,
        before_state: Optional[Dict] = None,
    ) -> Optional[AuditLog]:
        """Registra deleção de documento."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DOCUMENT_DELETED,
            severity=AuditSeverity.WARNING,
            resource_type="document",
            resource_id=document_id,
            user_id=user_id,
            action_details={"reason": reason},
            before_state=before_state,
        ))
    
    async def log_sync_started(
        self,
        source_id: str,
        run_id: str,
        trigger: str = "scheduled",
        triggered_by: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """Registra início de sincronização."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.SYNC_STARTED,
            resource_type="source",
            resource_id=source_id,
            user_id=triggered_by,
            action_details={"run_id": run_id, "trigger": trigger},
        ))
    
    async def log_sync_completed(
        self,
        source_id: str,
        run_id: str,
        status: str,
        stats: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditLog]:
        """Registra conclusão de sincronização."""
        severity = AuditSeverity.INFO if status == "success" else AuditSeverity.WARNING
        return await self.log(AuditEvent(
            event_type=AuditEventType.SYNC_COMPLETED,
            severity=severity,
            resource_type="source",
            resource_id=source_id,
            action_details={"run_id": run_id, "status": status, "stats": stats},
        ))
    
    async def log_sync_failed(
        self,
        source_id: str,
        run_id: str,
        error: str,
        severity: AuditSeverity = AuditSeverity.ERROR,
    ) -> Optional[AuditLog]:
        """Registra falha de sincronização."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.SYNC_FAILED,
            severity=severity,
            resource_type="source",
            resource_id=source_id,
            action_details={"run_id": run_id, "error": error},
        ))
    
    async def log_config_changed(
        self,
        config_key: str,
        user_id: str,
        before_value: Any,
        after_value: Any,
    ) -> Optional[AuditLog]:
        """Registra mudança de configuração."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.CONFIG_CHANGED,
            severity=AuditSeverity.WARNING,
            resource_type="config",
            resource_id=config_key,
            user_id=user_id,
            before_state={"value": before_value},
            after_state={"value": after_value},
        ))
    
    async def log_user_login(
        self,
        user_id: str,
        user_email: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """Registra login de usuário."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.USER_LOGIN,
            resource_type="user",
            resource_id=user_id,
            user_id=user_id,
            user_email=user_email,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
        ))
    
    async def log_user_logout(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> Optional[AuditLog]:
        """Registra logout de usuário."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.USER_LOGOUT,
            resource_type="user",
            resource_id=user_id,
            user_id=user_id,
            session_id=session_id,
        ))
    
    async def log_dlq_message_created(
        self,
        source_id: str,
        url: str,
        error_type: str,
        error_message: str,
    ) -> Optional[AuditLog]:
        """Registra criação de mensagem na DLQ."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.DLQ_MESSAGE_CREATED,
            severity=AuditSeverity.WARNING,
            resource_type="dlq",
            resource_id=f"{source_id}:{url}",
            action_details={
                "source_id": source_id,
                "url": url,
                "error_type": error_type,
                "error_message": error_message[:500],  # Limita tamanho
            },
        ))
    
    async def log_quality_check_failed(
        self,
        source_id: str,
        document_id: str,
        issues: List[str],
    ) -> Optional[AuditLog]:
        """Registra falha em verificação de qualidade."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.QUALITY_CHECK_FAILED,
            severity=AuditSeverity.WARNING,
            resource_type="document",
            resource_id=document_id,
            action_details={
                "source_id": source_id,
                "quality_issues": issues,
            },
        ))
    
    async def log_crawl_started(
        self,
        source_id: str,
        job_id: str,
        url_count: int,
    ) -> Optional[AuditLog]:
        """Registra início de crawling."""
        return await self.log(AuditEvent(
            event_type=AuditEventType.SYNC_STARTED,
            resource_type="crawl",
            resource_id=job_id,
            action_details={
                "source_id": source_id,
                "job_id": job_id,
                "url_count": url_count,
            },
        ))
    
    async def log_crawl_completed(
        self,
        source_id: str,
        job_id: str,
        status: str,
        stats: Dict[str, Any],
    ) -> Optional[AuditLog]:
        """Registra conclusão de crawling."""
        severity = AuditSeverity.INFO if status == "completed" else AuditSeverity.WARNING
        return await self.log(AuditEvent(
            event_type=AuditEventType.SYNC_COMPLETED,
            severity=severity,
            resource_type="crawl",
            resource_id=job_id,
            action_details={
                "source_id": source_id,
                "status": status,
                "stats": stats,
            },
        ))
    
    # Métodos de consulta
    
    async def query(self, query: AuditQuery) -> List[AuditLog]:
        """Busca eventos de auditoria.
        
        Args:
            query: Parâmetros da busca
            
        Returns:
            Lista de eventos
        """
        stmt = select(AuditLog)
        
        # Aplica filtros
        if query.event_types:
            stmt = stmt.where(AuditLog.event_type.in_([e.value for e in query.event_types]))
        
        if query.severities:
            stmt = stmt.where(AuditLog.severity.in_([s.value for s in query.severities]))
        
        if query.user_ids:
            stmt = stmt.where(AuditLog.user_id.in_(query.user_ids))
        
        if query.resource_types:
            stmt = stmt.where(AuditLog.resource_type.in_(query.resource_types))
        
        if query.resource_ids:
            stmt = stmt.where(AuditLog.resource_id.in_(query.resource_ids))
        
        if query.start_date:
            stmt = stmt.where(AuditLog.timestamp >= query.start_date)
        
        if query.end_date:
            stmt = stmt.where(AuditLog.timestamp <= query.end_date)
        
        if query.request_id:
            stmt = stmt.where(AuditLog.request_id == query.request_id)
        
        # Ordenação e paginação
        stmt = stmt.order_by(desc(AuditLog.timestamp))
        stmt = stmt.limit(query.limit).offset(query.offset)
        
        result = await self.db_session.execute(stmt)
        return result.scalars().all()
    
    async def get_by_resource(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Busca eventos por recurso.
        
        Args:
            resource_type: Tipo do recurso
            resource_id: ID do recurso
            limit: Limite de resultados
            
        Returns:
            Lista de eventos
        """
        return await self.query(AuditQuery(
            resource_types=[resource_type],
            resource_ids=[resource_id],
            limit=limit,
        ))
    
    async def get_by_user(
        self,
        user_id: str,
        limit: int = 100,
    ) -> List[AuditLog]:
        """Busca eventos por usuário.
        
        Args:
            user_id: ID do usuário
            limit: Limite de resultados
            
        Returns:
            Lista de eventos
        """
        return await self.query(AuditQuery(
            user_ids=[user_id],
            limit=limit,
        ))
    
    async def verify_integrity(
        self,
        start_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Verifica integridade da cadeia de hashes.
        
        Args:
            start_date: Data inicial para verificação
            
        Returns:
            Resultado da verificação
        """
        stmt = select(AuditLog).order_by(AuditLog.timestamp)
        
        if start_date:
            stmt = stmt.where(AuditLog.timestamp >= start_date)
        
        result = await self.db_session.execute(stmt)
        records = result.scalars().all()
        
        errors = []
        previous_hash = None
        
        for record in records:
            # Verifica previous_hash
            if record.previous_hash != previous_hash:
                errors.append({
                    "record_id": str(record.id),
                    "timestamp": record.timestamp.isoformat(),
                    "expected_previous": previous_hash,
                    "actual_previous": record.previous_hash,
                    "error": "Hash chain broken",
                })
            
            # Verifica event_hash
            # Recalcula hash para verificar integridade (mesma fórmula do _calculate_hash)
            # NOTA: O hash deve ser calculado com os mesmos campos usados em _calculate_hash,
            # mas usamos o timestamp do registro original para validação
            calculated_hash = self._calculate_hash_from_record(record)
            
            if calculated_hash != record.event_hash:
                errors.append({
                    "record_id": str(record.id),
                    "timestamp": record.timestamp.isoformat(),
                    "error": "Event hash mismatch",
                })
            
            previous_hash = record.event_hash
        
        return {
            "verified_count": len(records),
            "error_count": len(errors),
            "errors": errors,
            "integrity_ok": len(errors) == 0,
        }
    
    async def get_statistics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Retorna estatísticas de auditoria.
        
        Args:
            start_date: Data inicial
            end_date: Data final
            
        Returns:
            Estatísticas
        """
        filters = []
        if start_date:
            filters.append(AuditLog.timestamp >= start_date)
        if end_date:
            filters.append(AuditLog.timestamp <= end_date)
        
        where_clause = and_(*filters) if filters else None
        
        # Total de eventos
        stmt = select(func.count()).select_from(AuditLog)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self.db_session.execute(stmt)
        total_events = result.scalar()
        
        # Por tipo
        stmt = select(
            AuditLog.event_type,
            func.count()
        ).group_by(AuditLog.event_type)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self.db_session.execute(stmt)
        by_type = {row[0]: row[1] for row in result.fetchall()}
        
        # Por severidade
        stmt = select(
            AuditLog.severity,
            func.count()
        ).group_by(AuditLog.severity)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self.db_session.execute(stmt)
        by_severity = {row[0]: row[1] for row in result.fetchall()}
        
        return {
            "total_events": total_events,
            "by_event_type": by_type,
            "by_severity": by_severity,
            "period": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None,
            },
        }
    
    # Métodos auxiliares
    
    async def _get_last_hash(self) -> Optional[str]:
        """Obtém hash do último evento."""
        if self._last_hash:
            return self._last_hash
        
        result = await self.db_session.execute(
            select(AuditLog.event_hash)
            .order_by(desc(AuditLog.timestamp))
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return row
    
    def _calculate_hash(
        self,
        event: AuditEvent,
        previous_hash: Optional[str],
    ) -> str:
        """Calcula hash do evento.
        
        Args:
            event: Evento
            previous_hash: Hash anterior
            
        Returns:
            Hash SHA-256
        """
        timestamp = datetime.utcnow().isoformat()
        data = (
            f"{event.event_type.value}|"
            f"{event.severity.value}|"
            f"{event.user_id or ''}|"
            f"{event.resource_type or ''}|"
            f"{event.resource_id or ''}|"
            f"{timestamp}|"
            f"{previous_hash or ''}|"
            f"{event.request_id or ''}|"
            f"{event.correlation_id or ''}"
        )
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _calculate_hash_from_record(
        self,
        record: AuditLog,
    ) -> str:
        """Calcula hash a partir de um registro existente.
        
        Usado para verificação de integridade. Deve usar exatamente
        os mesmos campos e formato de _calculate_hash.
        
        Args:
            record: Registro de auditoria existente
            
        Returns:
            Hash SHA-256 calculado
        """
        data = (
            f"{record.event_type.value}|"
            f"{record.severity.value}|"
            f"{record.user_id or ''}|"
            f"{record.resource_type or ''}|"
            f"{record.resource_id or ''}|"
            f"{record.timestamp.isoformat()}|"
            f"{record.previous_hash or ''}|"
            f"{record.request_id or ''}|"
            f"{record.correlation_id or ''}"
        )
        return hashlib.sha256(data.encode()).hexdigest()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AuditEvent",
    "AuditQuery",
    "AuditLogger",
]
