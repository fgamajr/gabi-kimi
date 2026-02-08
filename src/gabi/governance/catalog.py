"""Catálogo de dados do GABI.

Gerencia o inventário de datasets, metadados de governança,
informações de propriedade e qualidade.
Baseado em GABI_SPECS_FINAL_v1.md Seção 2.7.1 (data_catalog).
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import UUID, uuid4

from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from gabi.config import settings
from gabi.types import SensitivityLevel

logger = logging.getLogger(__name__)


@dataclass
class DataAsset:
    """Ativo de dados no catálogo.
    
    Attributes:
        id: Identificador único do ativo
        name: Nome do ativo
        description: Descrição detalhada
        asset_type: Tipo (source, dataset, document, index)
        source_id: ID da fonte associada (se aplicável)
        
        # Governança
        owner_email: Email do responsável
        sensitivity: Nível de sensibilidade
        pii_fields: Campos com PII
        
        # Qualidade
        quality_score: Score de 0-100
        quality_issues: Lista de problemas encontrados
        last_quality_check: Última verificação de qualidade
        
        # Metadados
        schema: Schema dos dados
        sample_data: Amostra dos dados
        lineage_sources: Fontes de lineage
        
        # Estatísticas
        record_count: Número de registros
        size_bytes: Tamanho em bytes
        freshness_hours: Idade dos dados em horas
        
        # Retenção
        retention_days: Dias de retenção
        purge_after: Data de expurgo
        
        # Timestamps
        created_at: Criação
        updated_at: Última atualização
        last_accessed_at: Último acesso
    """
    id: str
    name: str
    description: Optional[str] = None
    asset_type: str = "dataset"  # source, dataset, document, index
    source_id: Optional[str] = None
    
    # Governança
    owner_email: str = ""
    sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL
    pii_fields: List[str] = field(default_factory=list)
    
    # Qualidade
    quality_score: Optional[int] = None
    quality_issues: List[Dict[str, Any]] = field(default_factory=list)
    last_quality_check: Optional[datetime] = None
    
    # Metadados
    schema: Dict[str, Any] = field(default_factory=dict)
    sample_data: Optional[List[Dict]] = None
    lineage_sources: List[str] = field(default_factory=list)
    
    # Estatísticas
    record_count: int = 0
    size_bytes: int = 0
    freshness_hours: Optional[float] = None
    
    # Retenção
    retention_days: int = 2555  # ~7 anos padrão
    purge_after: Optional[datetime] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "asset_type": self.asset_type,
            "source_id": self.source_id,
            "owner_email": self.owner_email,
            "sensitivity": self.sensitivity.value,
            "pii_fields": self.pii_fields,
            "quality_score": self.quality_score,
            "quality_issues": self.quality_issues,
            "last_quality_check": self.last_quality_check.isoformat() if self.last_quality_check else None,
            "schema": self.schema,
            "record_count": self.record_count,
            "size_bytes": self.size_bytes,
            "freshness_hours": self.freshness_hours,
            "retention_days": self.retention_days,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class CatalogSearchResult:
    """Resultado de busca no catálogo.
    
    Attributes:
        assets: Ativos encontrados
        total: Total de resultados
        page: Página atual
        page_size: Tamanho da página
        query: Query utilizada
    """
    assets: List[DataAsset]
    total: int
    page: int = 1
    page_size: int = 20
    query: Optional[str] = None


class DataCatalog:
    """Catálogo de dados do GABI.
    
    Gerencia o inventário de datasets com metadados
    de governança, qualidade e lineage.
    
    Attributes:
        db_session: Sessão do banco de dados
        cache: Cache em memória de assets frequentemente acessados
    """
    
    def __init__(self, db_session: AsyncSession):
        self.db_session = db_session
        self._cache: Dict[str, DataAsset] = {}
        self._cache_ttl: Dict[str, datetime] = {}
        self._cache_duration = 300  # 5 minutos
        logger.info("DataCatalog inicializado")
    
    async def register_asset(
        self,
        asset_id: str,
        name: str,
        asset_type: str,
        owner_email: str,
        description: Optional[str] = None,
        source_id: Optional[str] = None,
        sensitivity: SensitivityLevel = SensitivityLevel.INTERNAL,
        pii_fields: Optional[List[str]] = None,
        retention_days: int = 2555,
        schema: Optional[Dict[str, Any]] = None,
    ) -> DataAsset:
        """Registra um novo ativo no catálogo.
        
        Args:
            asset_id: ID único do ativo
            name: Nome do ativo
            asset_type: Tipo (source, dataset, document, index)
            owner_email: Email do responsável
            description: Descrição
            source_id: ID da fonte
            sensitivity: Nível de sensibilidade
            pii_fields: Campos com PII
            retention_days: Dias de retenção
            schema: Schema dos dados
            
        Returns:
            Ativo registrado
        """
        from gabi.models.source import SourceRegistry
        
        # Verifica se já existe
        existing = await self.get_asset(asset_id)
        if existing:
            logger.warning(f"Asset {asset_id} já existe, atualizando")
            return await self.update_asset(asset_id, name=name, description=description)
        
        # Cria asset
        asset = DataAsset(
            id=asset_id,
            name=name,
            asset_type=asset_type,
            owner_email=owner_email,
            description=description,
            source_id=source_id,
            sensitivity=sensitivity,
            pii_fields=pii_fields or [],
            retention_days=retention_days,
            schema=schema or {},
            purge_after=datetime.utcnow() + timedelta(days=retention_days) if retention_days > 0 else None,
        )
        
        # Persiste no banco (via modelo SourceRegistry ou tabela dedicada)
        try:
            # Usa tabela data_catalog se disponível
            await self._persist_asset(asset)
            logger.info(f"Asset {asset_id} registrado no catálogo")
        except Exception as e:
            logger.error(f"Erro ao persistir asset {asset_id}: {e}")
            raise
        
        # Atualiza cache
        self._cache[asset_id] = asset
        self._cache_ttl[asset_id] = datetime.utcnow()
        
        return asset
    
    async def _persist_asset(self, asset: DataAsset) -> None:
        """Persiste asset no banco de dados.
        
        Args:
            asset: Asset a persistir
        """
        from gabi.models.source import SourceRegistry
        
        # Verifica se existe source_registry com esse ID
        result = await self.db_session.execute(
            select(SourceRegistry).where(SourceRegistry.id == asset.id)
        )
        source = result.scalar_one_or_none()
        
        if source:
            # Atualiza campos de governança
            source.owner_email = asset.owner_email
            source.sensitivity = asset.sensitivity
            source.retention_days = asset.retention_days
            await self.db_session.commit()
        else:
            # Tenta inserir em data_catalog via SQL raw (usando parâmetros seguros)
            try:
                from sqlalchemy import text
                sql = text("""
                    INSERT INTO data_catalog (
                        id, name, description, owner_email, sensitivity,
                        pii_fields, quality_score, quality_issues,
                        retention_days, record_count, size_bytes,
                        created_at, updated_at
                    ) VALUES (
                        :id, :name, :description, :owner_email, :sensitivity,
                        :pii_fields::jsonb, :quality_score, :quality_issues::jsonb,
                        :retention_days, :record_count, :size_bytes,
                        NOW(), NOW()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        description = EXCLUDED.description,
                        owner_email = EXCLUDED.owner_email,
                        updated_at = NOW()
                """)
                await self.db_session.execute(sql, {
                    "id": asset.id,
                    "name": asset.name,
                    "description": asset.description,
                    "owner_email": asset.owner_email,
                    "sensitivity": asset.sensitivity.value,
                    "pii_fields": json.dumps(asset.pii_fields),
                    "quality_score": asset.quality_score,
                    "quality_issues": json.dumps(asset.quality_issues),
                    "retention_days": asset.retention_days,
                    "record_count": asset.record_count,
                    "size_bytes": asset.size_bytes,
                })
                await self.db_session.commit()
            except Exception as e:
                logger.warning(f"Não foi possível persistir em data_catalog: {e}")
                await self.db_session.rollback()
    
    async def get_asset(self, asset_id: str) -> Optional[DataAsset]:
        """Obtém asset do catálogo.
        
        Args:
            asset_id: ID do asset
            
        Returns:
            Asset ou None
        """
        # Verifica cache
        if asset_id in self._cache:
            cache_time = self._cache_ttl.get(asset_id)
            if cache_time and (datetime.utcnow() - cache_time).seconds < self._cache_duration:
                return self._cache[asset_id]
        
        # Busca no banco
        try:
            from sqlalchemy import text
            result = await self.db_session.execute(
                text("SELECT * FROM data_catalog WHERE id = :id"),
                {"id": asset_id}
            )
            row = result.fetchone()
            
            if row:
                asset = self._row_to_asset(row)
                self._cache[asset_id] = asset
                self._cache_ttl[asset_id] = datetime.utcnow()
                return asset
                
        except Exception as e:
            logger.warning(f"Erro ao buscar asset {asset_id}: {e}")
        
        # Fallback: busca em source_registry
        from gabi.models.source import SourceRegistry
        result = await self.db_session.execute(
            select(SourceRegistry).where(SourceRegistry.id == asset_id)
        )
        source = result.scalar_one_or_none()
        
        if source:
            asset = DataAsset(
                id=source.id,
                name=source.name,
                description=source.description,
                asset_type="source",
                owner_email=source.owner_email,
                sensitivity=source.sensitivity,
                record_count=source.document_count,
                created_at=source.created_at,
                updated_at=source.updated_at,
            )
            self._cache[asset_id] = asset
            self._cache_ttl[asset_id] = datetime.utcnow()
            return asset
        
        return None
    
    def _serialize_json_field(self, value: Any) -> Any:
        """Serializa campo JSON para o banco de dados.
        
        Converte Python objects para JSON strings quando necessário.
        """
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            return value  # PostgreSQL JSONB aceita objetos Python
        if isinstance(value, str):
            try:
                # Verifica se já é um JSON válido
                json.loads(value)
                return value
            except (json.JSONDecodeError, TypeError):
                return value
        return value
    
    def _deserialize_json_field(self, value: Any) -> Any:
        """Desserializa campo JSON do banco de dados.
        
        Converte strings JSON para objetos Python quando necessário.
        """
        if value is None:
            return None
        if isinstance(value, (list, dict)):
            return value  # Já é um objeto Python (PostgreSQL JSONB)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value
    
    def _row_to_asset(self, row) -> DataAsset:
        """Converte row do banco para DataAsset."""
        return DataAsset(
            id=row.id,
            name=row.name,
            description=row.description,
            owner_email=row.owner_email,
            sensitivity=SensitivityLevel(row.sensitivity) if row.sensitivity else SensitivityLevel.INTERNAL,
            pii_fields=self._deserialize_json_field(row.pii_fields) or [],
            quality_score=row.quality_score,
            quality_issues=self._deserialize_json_field(row.quality_issues) or [],
            retention_days=row.retention_days,
            record_count=row.record_count or 0,
            size_bytes=row.size_bytes or 0,
            created_at=row.created_at,
            updated_at=row.updated_at,
            last_accessed_at=getattr(row, 'last_accessed_at', None),
        )
    
    async def update_asset(
        self,
        asset_id: str,
        **kwargs
    ) -> Optional[DataAsset]:
        """Atualiza asset no catálogo.
        
        Args:
            asset_id: ID do asset
            **kwargs: Campos a atualizar
            
        Returns:
            Asset atualizado ou None
        """
        asset = await self.get_asset(asset_id)
        if not asset:
            return None
        
        # Atualiza campos
        valid_fields = {
            'name', 'description', 'owner_email', 'sensitivity',
            'pii_fields', 'retention_days', 'schema'
        }
        
        for field_name, value in kwargs.items():
            if field_name in valid_fields and hasattr(asset, field_name):
                setattr(asset, field_name, value)
        
        asset.updated_at = datetime.utcnow()
        
        # Persiste
        await self._persist_asset(asset)
        
        # Atualiza cache
        self._cache[asset_id] = asset
        self._cache_ttl[asset_id] = datetime.utcnow()
        
        return asset
    
    async def update_quality_score(
        self,
        asset_id: str,
        score: int,
        issues: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Atualiza score de qualidade do asset.
        
        Args:
            asset_id: ID do asset
            score: Score de 0-100
            issues: Lista de problemas
            
        Returns:
            True se atualizado
        """
        asset = await self.get_asset(asset_id)
        if not asset:
            return False
        
        asset.quality_score = max(0, min(100, score))
        asset.quality_issues = issues or []
        asset.last_quality_check = datetime.utcnow()
        asset.updated_at = datetime.utcnow()
        
        # Persiste
        try:
            from sqlalchemy import text
            await self.db_session.execute(
                text("""
                    UPDATE data_catalog 
                    SET quality_score = :score,
                        quality_issues = :issues::jsonb,
                        last_quality_check = NOW(),
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": asset_id,
                    "score": asset.quality_score,
                    "issues": json.dumps(issues or []),
                }
            )
            await self.db_session.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar quality score: {e}")
            await self.db_session.rollback()
        
        # Atualiza cache
        self._cache[asset_id] = asset
        
        return True
    
    async def update_statistics(
        self,
        asset_id: str,
        record_count: Optional[int] = None,
        size_bytes: Optional[int] = None,
    ) -> bool:
        """Atualiza estatísticas do asset.
        
        Args:
            asset_id: ID do asset
            record_count: Novo contador de registros
            size_bytes: Novo tamanho
            
        Returns:
            True se atualizado
        """
        asset = await self.get_asset(asset_id)
        if not asset:
            return False
        
        if record_count is not None:
            asset.record_count = record_count
        if size_bytes is not None:
            asset.size_bytes = size_bytes
        
        asset.updated_at = datetime.utcnow()
        
        # Persiste
        try:
            from sqlalchemy import text
            await self.db_session.execute(
                text("""
                    UPDATE data_catalog 
                    SET record_count = :record_count,
                        size_bytes = :size_bytes,
                        updated_at = NOW()
                    WHERE id = :id
                """),
                {
                    "id": asset_id,
                    "record_count": asset.record_count,
                    "size_bytes": asset.size_bytes,
                }
            )
            await self.db_session.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar estatísticas: {e}")
            await self.db_session.rollback()
        
        # Atualiza cache
        self._cache[asset_id] = asset
        
        return True
    
    async def search(
        self,
        query: Optional[str] = None,
        asset_type: Optional[str] = None,
        sensitivity: Optional[SensitivityLevel] = None,
        owner: Optional[str] = None,
        min_quality_score: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> CatalogSearchResult:
        """Busca assets no catálogo.
        
        Args:
            query: Texto de busca
            asset_type: Filtra por tipo
            sensitivity: Filtra por sensibilidade
            owner: Filtra por dono
            min_quality_score: Score mínimo de qualidade
            page: Página
            page_size: Tamanho da página
            
        Returns:
            Resultado da busca
        """
        try:
            from sqlalchemy import text
            from sqlalchemy import select, func, or_
            
            # Constrói query usando parâmetros seguros (proteção contra SQL injection)
            where_clauses = []
            params = {}
            
            if query:
                where_clauses.append("(name ILIKE :query OR description ILIKE :query)")
                params["query"] = f"%{query}%"
            
            if asset_type:
                where_clauses.append("asset_type = :asset_type")
                params["asset_type"] = asset_type
            
            if sensitivity:
                where_clauses.append("sensitivity = :sensitivity")
                params["sensitivity"] = sensitivity.value
            
            if owner:
                where_clauses.append("owner_email = :owner")
                params["owner"] = owner
            
            if min_quality_score is not None:
                where_clauses.append("quality_score >= :min_score")
                params["min_score"] = min_quality_score
            
            # Count total - usa SQL parametrizado seguro
            if where_clauses:
                where_sql = " AND ".join(where_clauses)
                count_sql = text(f"SELECT COUNT(*) FROM data_catalog WHERE {where_sql}")
                count_sql = count_sql.bindparams(**params)
            else:
                count_sql = text("SELECT COUNT(*) FROM data_catalog")
            
            result = await self.db_session.execute(count_sql)
            total = result.scalar()
            
            # Query paginada - usa SQL parametrizado seguro
            offset = (page - 1) * page_size
            params["limit"] = page_size
            params["offset"] = offset
            
            if where_clauses:
                where_sql = " AND ".join(where_clauses)
                query_sql = text(f"""
                    SELECT * FROM data_catalog 
                    WHERE {where_sql}
                    ORDER BY updated_at DESC
                    LIMIT :limit OFFSET :offset
                """).bindparams(**params)
            else:
                query_sql = text("""
                    SELECT * FROM data_catalog 
                    ORDER BY updated_at DESC
                    LIMIT :limit OFFSET :offset
                """).bindparams(**params)
            
            result = await self.db_session.execute(query_sql)
            rows = result.fetchall()
            
            assets = [self._row_to_asset(row) for row in rows]
            
            return CatalogSearchResult(
                assets=assets,
                total=total,
                page=page,
                page_size=page_size,
                query=query,
            )
            
        except Exception as e:
            logger.error(f"Erro na busca do catálogo: {e}")
            return CatalogSearchResult(assets=[], total=0, page=page, page_size=page_size)
    
    async def list_by_owner(self, owner_email: str) -> List[DataAsset]:
        """Lista assets por dono.
        
        Args:
            owner_email: Email do dono
            
        Returns:
            Lista de assets
        """
        result = await self.search(owner=owner_email)
        return result.assets
    
    async def get_expired_assets(self) -> List[DataAsset]:
        """Retorna assets com retenção expirada.
        
        Returns:
            Lista de assets expirados
        """
        try:
            from sqlalchemy import text
            result = await self.db_session.execute(
                text("""
                    SELECT * FROM data_catalog 
                    WHERE purge_after IS NOT NULL 
                    AND purge_after < NOW()
                """)
            )
            rows = result.fetchall()
            return [self._row_to_asset(row) for row in rows]
        except Exception as e:
            logger.error(f"Erro ao buscar assets expirados: {e}")
            return []
    
    async def delete_asset(self, asset_id: str) -> bool:
        """Remove asset do catálogo.
        
        Args:
            asset_id: ID do asset
            
        Returns:
            True se removido
        """
        try:
            from sqlalchemy import text
            await self.db_session.execute(
                text("DELETE FROM data_catalog WHERE id = :id"),
                {"id": asset_id}
            )
            await self.db_session.commit()
            
            # Remove do cache
            if asset_id in self._cache:
                del self._cache[asset_id]
                del self._cache_ttl[asset_id]
            
            return True
        except Exception as e:
            logger.error(f"Erro ao deletar asset {asset_id}: {e}")
            await self.db_session.rollback()
            return False
    
    def invalidate_cache(self, asset_id: Optional[str] = None) -> None:
        """Invalida cache do catálogo.
        
        Args:
            asset_id: ID específico ou None para todo cache
        """
        if asset_id:
            if asset_id in self._cache:
                del self._cache[asset_id]
                del self._cache_ttl[asset_id]
        else:
            self._cache.clear()
            self._cache_ttl.clear()
    
    async def get_catalog_summary(self) -> Dict[str, Any]:
        """Retorna resumo do catálogo.
        
        Returns:
            Estatísticas do catálogo
        """
        try:
            from sqlalchemy import text
            
            # Total de assets
            result = await self.db_session.execute(
                text("SELECT COUNT(*) FROM data_catalog")
            )
            total_assets = result.scalar()
            
            # Por sensibilidade
            result = await self.db_session.execute(
                text("SELECT sensitivity, COUNT(*) FROM data_catalog GROUP BY sensitivity")
            )
            by_sensitivity = {row.sensitivity: row.count for row in result.fetchall()}
            
            # Total de registros
            result = await self.db_session.execute(
                text("SELECT SUM(record_count) FROM data_catalog")
            )
            total_records = result.scalar() or 0
            
            # Total em bytes
            result = await self.db_session.execute(
                text("SELECT SUM(size_bytes) FROM data_catalog")
            )
            total_bytes = result.scalar() or 0
            
            # Assets expirados
            expired = await self.get_expired_assets()
            
            return {
                "total_assets": total_assets,
                "by_sensitivity": by_sensitivity,
                "total_records": total_records,
                "total_bytes": total_bytes,
                "total_gb": round(total_bytes / (1024**3), 2),
                "expired_assets_count": len(expired),
            }
            
        except Exception as e:
            logger.error(f"Erro ao gerar resumo do catálogo: {e}")
            return {
                "total_assets": 0,
                "error": str(e),
            }


from datetime import timedelta


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "DataAsset",
    "CatalogSearchResult",
    "DataCatalog",
]
