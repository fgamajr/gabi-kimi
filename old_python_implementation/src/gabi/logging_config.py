"""Configuração de logging estruturado do GABI.

Implementa logging JSON para integração com sistemas
de observabilidade e análise de logs.

Baseado em GABI_SPECS_FINAL_v1.md - Observabilidade.
"""

import json
import logging
import logging.handlers
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Optional, Union

from gabi.config import settings


class JSONFormatter(logging.Formatter):
    """Formatter que gera logs em formato JSON.
    
    Facilita parsing por sistemas como ELK, Splunk, etc.
    
    Attributes:
        static_fields: Campos estáticos em todos os logs
    """
    
    def __init__(
        self,
        static_fields: Optional[Dict[str, Any]] = None,
        indent: Optional[int] = None,
    ):
        super().__init__()
        self.static_fields = static_fields or {}
        self.indent = indent
    
    def format(self, record: logging.LogRecord) -> str:
        """Formata registro como JSON."""
        log_data = {
            # Timestamp ISO8601
            "timestamp": datetime.utcnow().isoformat() + "Z",
            
            # Nível
            "level": record.levelname,
            "level_num": record.levelno,
            
            # Mensagem
            "message": record.getMessage(),
            
            # Origem
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "file": record.pathname,
            
            # Ambiente
            "environment": settings.environment.value,
            "service": "gabi",
            "version": "2.1.0",
            
            # Campos estáticos
            **self.static_fields,
        }
        
        # Adiciona campos extras do record
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id
        
        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id
        
        if hasattr(record, "user_id"):
            log_data["user_id"] = record.user_id
        
        if hasattr(record, "source_id"):
            log_data["source_id"] = record.source_id
        
        if hasattr(record, "document_id"):
            log_data["document_id"] = record.document_id
        
        # Exception info
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            log_data["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }
        
        # Stack info
        if record.stack_info:
            log_data["stack_info"] = record.stack_info
        
        # Campos adicionais do record
        for key, value in record.__dict__.items():
            if key not in log_data and not key.startswith("_"):
                if key not in (
                    "args", "asctime", "created", "exc_info", "exc_text",
                    "filename", "funcName", "levelname", "levelno", "lineno",
                    "module", "msecs", "message", "msg", "name", "pathname",
                    "process", "processName", "relativeCreated", "stack_info",
                    "thread", "threadName"
                ):
                    log_data[key] = value
        
        # Converte para JSON
        return json.dumps(log_data, default=str, indent=self.indent)


class StructuredLogger:
    """Logger estruturado com contexto.
    
    Permite adicionar contexto a logs que é automaticamente
    incluído em todas as mensagens subsequentes.
    
    Example:
        logger = StructuredLogger("gabi.pipeline")
        
        with logger.context(request_id="abc123", source_id="tcu"):
            logger.info("Iniciando processamento")
            logger.info("Processado com sucesso")  # Inclui request_id e source_id
    """
    
    def __init__(self, name: str):
        self.name = name
        self._logger = logging.getLogger(name)
        self._context: Dict[str, Any] = {}
    
    def _log(
        self,
        level: int,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = False,
    ) -> None:
        """Método interno de logging."""
        # Merge context + extra
        merged_extra = {**self._context}
        if extra:
            merged_extra.update(extra)
        
        self._logger.log(level, message, extra=merged_extra, exc_info=exc_info)
    
    def debug(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log DEBUG."""
        self._log(logging.DEBUG, message, extra)
    
    def info(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log INFO."""
        self._log(logging.INFO, message, extra)
    
    def warning(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log WARNING."""
        self._log(logging.WARNING, message, extra)
    
    def error(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = True,
    ) -> None:
        """Log ERROR."""
        self._log(logging.ERROR, message, extra, exc_info)
    
    def critical(
        self,
        message: str,
        extra: Optional[Dict[str, Any]] = None,
        exc_info: bool = True,
    ) -> None:
        """Log CRITICAL."""
        self._log(logging.CRITICAL, message, extra, exc_info)
    
    def exception(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Log EXCEPTION (com traceback)."""
        self._log(logging.ERROR, message, extra, exc_info=True)
    
    def bind(self, **context) -> "StructuredLogger":
        """Retorna novo logger com contexto adicional.
        
        Returns:
            Novo StructuredLogger com contexto mesclado
        """
        new_logger = StructuredLogger(self.name)
        new_logger._context = {**self._context, **context}
        return new_logger
    
    def context(self, **kwargs):
        """Context manager para contexto temporário.
        
        Example:
            with logger.context(request_id="abc"):
                logger.info("message")  # Inclui request_id
        """
        return LogContext(self, **kwargs)


class LogContext:
    """Context manager para contexto de log."""
    
    def __init__(self, logger: StructuredLogger, **context):
        self.logger = logger
        self.context = context
        self.previous_context = {}
    
    def __enter__(self):
        self.previous_context = self.logger._context.copy()
        self.logger._context.update(self.context)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger._context = self.previous_context


def setup_logging(
    level: Optional[str] = None,
    json_format: bool = True,
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """Configura logging da aplicação.
    
    Args:
        level: Nível de log (debug, info, warning, error)
        json_format: Se deve usar formato JSON
        log_file: Arquivo de log (opcional)
        max_bytes: Tamanho máximo do arquivo rotacionado
        backup_count: Número de backups mantidos
    """
    level = level or settings.log_level
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Remove handlers existentes
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Formatter
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (opcional)
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Reduz verbosidade de bibliotecas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )
    
    logger = logging.getLogger("gabi")
    logger.info(f"Logging configurado (level={level}, json={json_format})")


def get_logger(name: str) -> StructuredLogger:
    """Obtém logger estruturado.
    
    Args:
        name: Nome do logger
        
    Returns:
        StructuredLogger configurado
    """
    return StructuredLogger(name)


def log_request(
    logger: Union[logging.Logger, StructuredLogger],
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    user_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Log estruturado de requisição HTTP.
    
    Args:
        logger: Logger
        request_id: ID da requisição
        method: Método HTTP
        path: Path da requisição
        status_code: Código de status
        duration_ms: Duração em ms
        user_id: ID do usuário
        extra: Campos extras
    """
    log_data = {
        "request_id": request_id,
        "method": method,
        "path": path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "user_id": user_id,
        **(extra or {}),
    }
    
    if isinstance(logger, StructuredLogger):
        logger.info("HTTP request", extra=log_data)
    else:
        logger.info(
            f"{method} {path} - {status_code} ({duration_ms:.2f}ms)",
            extra=log_data,
        )


def log_pipeline_event(
    logger: Union[logging.Logger, StructuredLogger],
    event: str,
    source_id: str,
    run_id: str,
    details: Optional[Dict[str, Any]] = None,
    level: int = logging.INFO,
) -> None:
    """Log de evento do pipeline.
    
    Args:
        logger: Logger
        event: Tipo de evento
        source_id: ID da fonte
        run_id: ID da execução
        details: Detalhes adicionais
        level: Nível de log
    """
    log_data = {
        "event_type": "pipeline",
        "event": event,
        "source_id": source_id,
        "run_id": run_id,
        **(details or {}),
    }
    
    if isinstance(logger, StructuredLogger):
        logger._log(level, f"Pipeline {event}", log_data)
    else:
        logger.log(level, f"Pipeline {event}: {source_id}/{run_id}", extra=log_data)


def log_audit_event(
    logger: Union[logging.Logger, StructuredLogger],
    event_type: str,
    resource_type: str,
    resource_id: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Log de evento de auditoria.
    
    Args:
        logger: Logger
        event_type: Tipo de evento
        resource_type: Tipo de recurso
        resource_id: ID do recurso
        user_id: ID do usuário
        details: Detalhes
    """
    log_data = {
        "event_type": "audit",
        "audit_event": event_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "user_id": user_id,
        **(details or {}),
    }
    
    if isinstance(logger, StructuredLogger):
        logger.info(f"Audit: {event_type}", extra=log_data)
    else:
        logger.info(
            f"Audit: {event_type} on {resource_type}:{resource_id}",
            extra=log_data,
        )


class RequestIdFilter(logging.Filter):
    """Filter que adiciona request_id aos logs.
    
    Usa contextvar para armazenar request_id por request.
    """
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Adiciona request_id ao record."""
        # Tenta obter de contextvar (se configurado)
        try:
            import contextvars
            request_id_var = contextvars.ContextVar("request_id", default=None)
            request_id = request_id_var.get()
            if request_id:
                record.request_id = request_id
        except (ImportError, AttributeError):
            pass
        
        return True


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Classes
    "JSONFormatter",
    "StructuredLogger",
    "LogContext",
    "RequestIdFilter",
    # Functions
    "setup_logging",
    "get_logger",
    "log_request",
    "log_pipeline_event",
    "log_audit_event",
]
