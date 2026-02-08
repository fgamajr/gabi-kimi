"""Sistema de Quality Checks do GABI.

Valida qualidade de dados em múltiplas dimensões:
- Completude: Dados ausentes
- Validade: Conformidade com schema
- Consistência: Coerência entre campos
- Atualidade: Frescor dos dados
- Unicidade: Duplicatas

Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (data_catalog.quality_score).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set, Union

from gabi.config import settings

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    """Problema de qualidade detectado.
    
    Attributes:
        dimension: Dimensão (completeness, validity, etc.)
        severity: Severidade (error, warning, info)
        field: Campo afetado
        message: Descrição do problema
        value: Valor que causou o problema
        rule: Regra violada
    """
    dimension: str
    severity: str  # error, warning, info
    field: str
    message: str
    value: Optional[Any] = None
    rule: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            "dimension": self.dimension,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "value": self.value,
            "rule": self.rule,
        }


@dataclass
class QualityReport:
    """Relatório de qualidade.
    
    Attributes:
        entity_id: ID da entidade verificada
        entity_type: Tipo (document, source, etc.)
        score: Score geral (0-100)
        passed: Se passou em todos os checks críticos
        issues: Lista de problemas
        checks_performed: Número de checks executados
        timestamp: Timestamp do relatório
        duration_ms: Duração da verificação
    """
    entity_id: str
    entity_type: str
    score: float = 100.0
    passed: bool = True
    issues: List[QualityIssue] = field(default_factory=list)
    checks_performed: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "score": round(self.score, 2),
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "checks_performed": self.checks_performed,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
        }
    
    def add_issue(
        self,
        dimension: str,
        field: str,
        message: str,
        severity: str = "error",
        value: Optional[Any] = None,
        rule: Optional[str] = None,
    ) -> None:
        """Adiciona problema ao relatório."""
        issue = QualityIssue(
            dimension=dimension,
            severity=severity,
            field=field,
            message=message,
            value=value,
            rule=rule,
        )
        self.issues.append(issue)
        
        if severity == "error":
            self.passed = False
            self.score = max(0, self.score - 10)
        elif severity == "warning":
            self.score = max(0, self.score - 5)


@dataclass
class QualityRule:
    """Regra de qualidade.
    
    Attributes:
        name: Nome da regra
        dimension: Dimensão
        field: Campo a validar
        check: Função de validação
        severity: Severidade se falhar
        message: Mensagem de erro
    """
    name: str
    dimension: str
    field: str
    check: Callable[[Any], bool]
    severity: str = "error"
    message: str = "Validation failed"


class QualityChecker:
    """Verificador de qualidade de dados.
    
    Executa checks em múltiplas dimensões e gera
    relatórios de qualidade.
    
    Attributes:
        rules: Regras configuradas
        strict_mode: Se deve falhar em warnings
    """
    
    # Regras padrão para documentos jurídicos
    DEFAULT_DOCUMENT_RULES = {
        "completeness": {
            "required_fields": ["document_id", "source_id"],
            "content_min_length": 100,
        },
        "validity": {
            "document_id_pattern": r"^[A-Za-z0-9_\-/:]+$",
            "year_range": (1800, datetime.utcnow().year + 1),
        },
        "consistency": {
            "check_dates": True,
        },
    }
    
    def __init__(
        self,
        rules: Optional[Dict[str, Any]] = None,
        strict_mode: bool = False,
    ):
        self.rules = rules or self.DEFAULT_DOCUMENT_RULES.copy()
        self.strict_mode = strict_mode
        self._custom_rules: List[QualityRule] = []
        logger.info(f"QualityChecker inicializado (strict={strict_mode})")
    
    def add_rule(self, rule: QualityRule) -> None:
        """Adiciona regra customizada."""
        self._custom_rules.append(rule)
    
    async def check_document(
        self,
        document: Dict[str, Any],
        document_id: str,
        source_id: str,
    ) -> QualityReport:
        """Verifica qualidade de um documento.
        
        Args:
            document: Dados do documento
            document_id: ID do documento
            source_id: ID da fonte
            
        Returns:
            Relatório de qualidade
        """
        import time
        start_time = time.time()
        
        report = QualityReport(
            entity_id=document_id,
            entity_type="document",
        )
        
        # Completeness
        await self._check_completeness(document, report, document_id, source_id)
        
        # Validity
        await self._check_validity(document, report)
        
        # Consistency
        await self._check_consistency(document, report)
        
        # Custom rules
        await self._check_custom_rules(document, report)
        
        report.duration_ms = int((time.time() - start_time) * 1000)
        report.checks_performed = (
            len(self.rules.get("completeness", {}).get("required_fields", [])) +
            len(self.rules.get("validity", {})) +
            len(self._custom_rules)
        )
        
        # Ajusta score baseado em strict_mode
        if self.strict_mode and report.issues:
            has_warnings = any(i.severity == "warning" for i in report.issues)
            if has_warnings:
                report.passed = False
        
        return report
    
    async def _check_completeness(
        self,
        document: Dict[str, Any],
        report: QualityReport,
        document_id: str,
        source_id: str,
    ) -> None:
        """Verifica completude dos dados."""
        rules = self.rules.get("completeness", {})
        
        # Verifica campos obrigatórios
        for field in rules.get("required_fields", []):
            value = document.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                report.add_issue(
                    dimension="completeness",
                    field=field,
                    message=f"Campo obrigatório ausente: {field}",
                    severity="error",
                    rule="required_field",
                )
        
        # Verifica content
        content = document.get("content", "")
        min_length = rules.get("content_min_length", 100)
        if len(content) < min_length:
            report.add_issue(
                dimension="completeness",
                field="content",
                message=f"Conteúdo muito curto ({len(content)} chars, mínimo {min_length})",
                severity="warning",
                value=len(content),
                rule="min_content_length",
            )
        
        # Verifica título
        title = document.get("title", "")
        if not title or len(title.strip()) < 5:
            report.add_issue(
                dimension="completeness",
                field="title",
                message="Título ausente ou muito curto",
                severity="warning",
                rule="title_present",
            )
    
    async def _check_validity(
        self,
        document: Dict[str, Any],
        report: QualityReport,
    ) -> None:
        """Verifica validade dos dados."""
        rules = self.rules.get("validity", {})
        
        # Verifica pattern do document_id
        pattern = rules.get("document_id_pattern")
        if pattern:
            doc_id = document.get("document_id", "")
            if doc_id and not re.match(pattern, str(doc_id)):
                report.add_issue(
                    dimension="validity",
                    field="document_id",
                    message=f"Formato inválido de document_id: {doc_id}",
                    severity="error",
                    value=doc_id,
                    rule="document_id_format",
                )
        
        # Verifica ano
        year_range = rules.get("year_range")
        if year_range:
            year = document.get("metadata", {}).get("year")
            if year is not None:
                try:
                    year_int = int(year)
                    if year_int < year_range[0] or year_int > year_range[1]:
                        report.add_issue(
                            dimension="validity",
                            field="metadata.year",
                            message=f"Ano fora do intervalo válido: {year_int}",
                            severity="error",
                            value=year_int,
                            rule="year_range",
                        )
                except (ValueError, TypeError):
                    report.add_issue(
                        dimension="validity",
                        field="metadata.year",
                        message=f"Ano inválido: {year}",
                        severity="error",
                        value=year,
                        rule="year_numeric",
                    )
        
        # Verifica URL
        url = document.get("url")
        if url:
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                report.add_issue(
                    dimension="validity",
                    field="url",
                    message=f"URL inválida: {url}",
                    severity="warning",
                    value=url,
                    rule="url_format",
                )
    
    async def _check_consistency(
        self,
        document: Dict[str, Any],
        report: QualityReport,
    ) -> None:
        """Verifica consistência dos dados."""
        rules = self.rules.get("consistency", {})
        
        metadata = document.get("metadata", {})
        
        # Verifica coerência de datas
        if rules.get("check_dates", True):
            year = metadata.get("year")
            date = metadata.get("date")
            
            if year and date:
                try:
                    # Extrai ano da data
                    date_year = None
                    if isinstance(date, str):
                        if len(date) >= 4:
                            date_year = int(date[:4])
                    
                    if date_year and int(year) != date_year:
                        report.add_issue(
                            dimension="consistency",
                            field="metadata",
                            message=f"Ano inconsistente: year={year}, date_year={date_year}",
                            severity="warning",
                            rule="date_consistency",
                        )
                except (ValueError, TypeError):
                    pass
        
        # Verifica coerência título/conteúdo
        title = document.get("title", "")
        content = document.get("content", "")
        
        if title and content:
            # Título deve estar presente no conteúdo ou ser relacionado
            title_words = set(title.lower().split())
            content_words = set(content.lower().split())
            
            # Calcula overlap
            if title_words:
                overlap = len(title_words & content_words) / len(title_words)
                if overlap < 0.1:  # Menos de 10% das palavras do título no conteúdo
                    report.add_issue(
                        dimension="consistency",
                        field="title",
                        message="Título pouco relacionado ao conteúdo",
                        severity="info",
                        value=overlap,
                        rule="title_content_relation",
                    )
    
    async def _check_custom_rules(
        self,
        document: Dict[str, Any],
        report: QualityReport,
    ) -> None:
        """Executa regras customizadas."""
        for rule in self._custom_rules:
            value = document.get(rule.field)
            try:
                if not rule.check(value):
                    report.add_issue(
                        dimension=rule.dimension,
                        field=rule.field,
                        message=rule.message,
                        severity=rule.severity,
                        value=value,
                        rule=rule.name,
                    )
            except Exception as e:
                logger.warning(f"Erro em regra customizada {rule.name}: {e}")
    
    def check_uniqueness(
        self,
        documents: List[Dict[str, Any]],
        key_fields: List[str] = None,
    ) -> List[QualityIssue]:
        """Verifica duplicatas em lista de documentos.
        
        Args:
            documents: Lista de documentos
            key_fields: Campos para identificar duplicatas
            
        Returns:
            Lista de problemas de unicidade
        """
        key_fields = key_fields or ["document_id"]
        issues = []
        seen: Dict[str, int] = {}  # key -> index
        
        for idx, doc in enumerate(documents):
            # Constrói chave
            key_parts = []
            for field in key_fields:
                value = doc.get(field, "")
                key_parts.append(str(value))
            key = "|".join(key_parts)
            
            if key in seen:
                issues.append(QualityIssue(
                    dimension="uniqueness",
                    severity="error",
                    field="_id",
                    message=f"Documento duplicado (mesmo que índice {seen[key]})",
                    value=key,
                    rule="unique_document",
                ))
            else:
                seen[key] = idx
        
        return issues
    
    async def check_source_health(
        self,
        source_id: str,
        documents: List[Dict[str, Any]],
    ) -> QualityReport:
        """Verifica saúde geral de uma fonte.
        
        Args:
            source_id: ID da fonte
            documents: Documentos da fonte
            
        Returns:
            Relatório de qualidade
        """
        report = QualityReport(
            entity_id=source_id,
            entity_type="source",
        )
        
        if not documents:
            report.add_issue(
                dimension="completeness",
                field="documents",
                message="Fonte sem documentos",
                severity="warning",
                rule="source_has_documents",
            )
            return report
        
        # Verifica duplicatas
        uniqueness_issues = self.check_uniqueness(documents)
        for issue in uniqueness_issues:
            report.issues.append(issue)
            report.score = max(0, report.score - 5)
        
        # Estatísticas
        total_docs = len(documents)
        docs_with_content = sum(1 for d in documents if len(d.get("content", "")) > 100)
        docs_with_title = sum(1 for d in documents if d.get("title"))
        
        # Content ratio
        content_ratio = docs_with_content / total_docs if total_docs > 0 else 0
        if content_ratio < 0.9:
            report.add_issue(
                dimension="completeness",
                field="content",
                message=f"{docs_with_content}/{total_docs} documentos com conteúdo adequado",
                severity="warning",
                value=content_ratio,
                rule="source_content_ratio",
            )
        
        # Title ratio
        title_ratio = docs_with_title / total_docs if total_docs > 0 else 0
        if title_ratio < 0.8:
            report.add_issue(
                dimension="completeness",
                field="title",
                message=f"{docs_with_title}/{total_docs} documentos com título",
                severity="warning",
                value=title_ratio,
                rule="source_title_ratio",
            )
        
        # Score final
        report.score = max(0, 100 - len(report.issues) * 5)
        report.passed = len([i for i in report.issues if i.severity == "error"]) == 0
        
        return report
    
    def validate_schema(
        self,
        data: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> List[QualityIssue]:
        """Valida dados contra schema.
        
        Args:
            data: Dados a validar
            schema: Schema de validação
            
        Returns:
            Lista de problemas
        """
        issues = []
        
        for field_name, field_spec in schema.items():
            value = data.get(field_name)
            
            # Required
            if field_spec.get("required") and (value is None or value == ""):
                issues.append(QualityIssue(
                    dimension="validity",
                    severity="error",
                    field=field_name,
                    message=f"Campo obrigatório ausente: {field_name}",
                    rule="required",
                ))
                continue
            
            if value is None:
                continue
            
            # Type
            expected_type = field_spec.get("type")
            if expected_type:
                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                }
                if expected_type in type_map:
                    if not isinstance(value, type_map[expected_type]):
                        issues.append(QualityIssue(
                            dimension="validity",
                            severity="error",
                            field=field_name,
                            message=f"Tipo inválido: esperado {expected_type}",
                            value=type(value).__name__,
                            rule="type_check",
                        ))
            
            # Pattern
            pattern = field_spec.get("pattern")
            if pattern and isinstance(value, str):
                if not re.match(pattern, value):
                    issues.append(QualityIssue(
                        dimension="validity",
                        severity="error",
                        field=field_name,
                        message=f"Não corresponde ao padrão: {pattern}",
                        value=value[:50],
                        rule="pattern",
                    ))
            
            # Min/Max length
            if isinstance(value, str):
                min_len = field_spec.get("minLength")
                max_len = field_spec.get("maxLength")
                
                if min_len and len(value) < min_len:
                    issues.append(QualityIssue(
                        dimension="validity",
                        severity="warning",
                        field=field_name,
                        message=f"Comprimento mínimo: {min_len}",
                        value=len(value),
                        rule="minLength",
                    ))
                
                if max_len and len(value) > max_len:
                    issues.append(QualityIssue(
                        dimension="validity",
                        severity="warning",
                        field=field_name,
                        message=f"Comprimento máximo: {max_len}",
                        value=len(value),
                        rule="maxLength",
                    ))
            
            # Enum
            enum_values = field_spec.get("enum")
            if enum_values and value not in enum_values:
                issues.append(QualityIssue(
                    dimension="validity",
                    severity="error",
                    field=field_name,
                    message=f"Valor não permitido",
                    value=value,
                    rule="enum",
                ))
        
        return issues


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "QualityIssue",
    "QualityReport",
    "QualityRule",
    "QualityChecker",
]
