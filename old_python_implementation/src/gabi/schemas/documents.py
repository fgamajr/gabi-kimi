"""Document schemas for GABI API."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    """Status do documento."""
    ACTIVE = "active"
    UPDATED = "updated"
    DELETED = "deleted"
    ERROR = "error"


class DocumentListItem(BaseModel):
    """Item de documento na listagem."""
    id: str = Field(..., description="UUID interno do documento")
    document_id: str = Field(..., description="Identificador externo único")
    source_id: str = Field(..., description="ID da fonte de origem")
    title: Optional[str] = Field(None, description="Título do documento")
    content_preview: Optional[str] = Field(None, description="Preview do conteúdo")
    status: DocumentStatus = Field(..., description="Status do documento")
    is_deleted: bool = Field(..., description="Se foi soft-deletado")
    version: int = Field(..., description="Versão do documento")
    chunks_count: int = Field(..., description="Quantidade de chunks")
    es_indexed: bool = Field(..., description="Se está indexado no ES")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados")
    ingested_at: datetime = Field(..., description="Data de ingestão")
    updated_at: datetime = Field(..., description="Última atualização")
    reindexed_at: Optional[datetime] = Field(None, description="Última reindexação")


class DocumentDetail(BaseModel):
    """Detalhe completo do documento."""
    id: str = Field(..., description="UUID interno")
    document_id: str = Field(..., description="Identificador externo único")
    source_id: str = Field(..., description="ID da fonte")
    fingerprint: str = Field(..., description="Fingerprint SHA-256")
    fingerprint_algorithm: str = Field(..., description="Algoritmo do fingerprint")
    title: Optional[str] = Field(None, description="Título")
    content_preview: Optional[str] = Field(None, description="Preview do conteúdo")
    content_hash: Optional[str] = Field(None, description="Hash do conteúdo completo")
    content_size_bytes: Optional[int] = Field(None, description="Tamanho em bytes")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados extensíveis")
    url: Optional[str] = Field(None, description="URL de origem")
    content_type: Optional[str] = Field(None, description="Tipo MIME")
    language: str = Field(default="pt-BR", description="Idioma")
    status: DocumentStatus = Field(..., description="Status")
    version: int = Field(..., description="Versão")
    is_deleted: bool = Field(..., description="Soft delete flag")
    deleted_at: Optional[datetime] = Field(None, description="Data de deleção")
    deleted_reason: Optional[str] = Field(None, description="Motivo da deleção")
    deleted_by: Optional[str] = Field(None, description="Quem deletou")
    ingested_at: datetime = Field(..., description="Data de ingestão")
    updated_at: datetime = Field(..., description="Última atualização")
    reindexed_at: Optional[datetime] = Field(None, description="Última reindexação")
    es_indexed: bool = Field(..., description="Indexado no ES")
    es_indexed_at: Optional[datetime] = Field(None, description="Data de indexação ES")
    chunks_count: int = Field(..., description="Quantidade de chunks")


class DocumentChunkInfo(BaseModel):
    """Informação de um chunk do documento."""
    id: str = Field(..., description="ID do chunk")
    document_id: str = Field(..., description="ID do documento")
    chunk_index: int = Field(..., description="Índice do chunk")
    content_preview: str = Field(..., description="Preview do conteúdo")
    token_count: Optional[int] = Field(None, description="Quantidade de tokens")
    char_count: int = Field(..., description="Quantidade de caracteres")
    embedding_status: str = Field(..., description="Status do embedding")
    created_at: datetime = Field(..., description="Data de criação")


class DocumentListResponse(BaseModel):
    """Resposta da listagem de documentos."""
    total: int = Field(..., description="Total de documentos")
    page: int = Field(..., description="Página atual")
    page_size: int = Field(..., description="Tamanho da página")
    documents: List[DocumentListItem] = Field(default_factory=list)


class DocumentDetailResponse(BaseModel):
    """Resposta do detalhe do documento."""
    document: DocumentDetail
    chunks: Optional[List[DocumentChunkInfo]] = Field(None, description="Chunks do documento")


class DocumentReindexRequest(BaseModel):
    """Request para reindexar documento."""
    force: bool = Field(default=False, description="Força reindexação mesmo se já estiver atualizado")
    sync_es: bool = Field(default=True, description="Sincroniza com Elasticsearch")


class DocumentReindexResponse(BaseModel):
    """Resposta da reindexação."""
    success: bool = Field(..., description="Sucesso da operação")
    document_id: str = Field(..., description="ID do documento")
    message: str = Field(..., description="Mensagem descritiva")
    reindexed_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentDeleteResponse(BaseModel):
    """Resposta da deleção de documento."""
    success: bool = Field(..., description="Sucesso da operação")
    document_id: str = Field(..., description="ID do documento")
    message: str = Field(..., description="Mensagem descritiva")
    deleted_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentFilterParams(BaseModel):
    """Parâmetros de filtro para listagem."""
    source_id: Optional[str] = Field(None, description="Filtrar por fonte")
    status: Optional[DocumentStatus] = Field(None, description="Filtrar por status")
    is_deleted: Optional[bool] = Field(default=False, description="Incluir deletados")
    es_indexed: Optional[bool] = Field(None, description="Filtrar por indexação ES")
    date_from: Optional[datetime] = Field(None, description="Data inicial")
    date_to: Optional[datetime] = Field(None, description="Data final")
    search: Optional[str] = Field(None, description="Busca em título/conteúdo")
