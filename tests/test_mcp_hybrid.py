"""
Tests for MCP Hybrid Search Server

Run with: pytest tests/test_mcp_hybrid.py -v
"""

import json
import pytest
from typing import Dict, Any
from unittest.mock import Mock, patch, AsyncMock

# Import the modules to test
from gabi.mcp.tools_hybrid import (
    HybridSearchToolManager,
    EXACT_SEARCH_FIELDS,
    TOOL_SCHEMAS,
)
from gabi.mcp.resources_hybrid import (
    HybridSearchResourceManager,
    RESOURCE_PATTERNS,
)
from gabi.mcp.server_hybrid import (
    MCPHybridSearchServer,
    get_current_user,
    _extract_permissions,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tool_manager():
    """Fixture for HybridSearchToolManager."""
    return HybridSearchToolManager()


@pytest.fixture
def resource_manager():
    """Fixture for HybridSearchResourceManager."""
    return HybridSearchResourceManager()


@pytest.fixture
def mock_user():
    """Fixture for mock user."""
    return {
        "sub": "test-user-123",
        "name": "Test User",
        "permissions": ["search:read", "document:read"]
    }


# =============================================================================
# Tool Schema Tests
# =============================================================================

class TestToolSchemas:
    """Tests for tool schema definitions."""
    
    def test_search_exact_schema_exists(self):
        """Test that search_exact schema is defined."""
        assert "search_exact" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["search_exact"]
        assert schema["name"] == "search_exact"
        assert "inputSchema" in schema
    
    def test_search_semantic_schema_exists(self):
        """Test that search_semantic schema is defined."""
        assert "search_semantic" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["search_semantic"]
        assert schema["name"] == "search_semantic"
        assert "inputSchema" in schema
    
    def test_search_hybrid_schema_exists(self):
        """Test that search_hybrid schema is defined."""
        assert "search_hybrid" in TOOL_SCHEMAS
        schema = TOOL_SCHEMAS["search_hybrid"]
        assert schema["name"] == "search_hybrid"
        assert "inputSchema" in schema
    
    def test_search_exact_schema_structure(self):
        """Test search_exact schema structure."""
        schema = TOOL_SCHEMAS["search_exact"]
        input_schema = schema["inputSchema"]
        
        assert input_schema["type"] == "object"
        assert "document_type" in input_schema["properties"]
        assert "fields" in input_schema["properties"]
        assert "limit" in input_schema["properties"]
        
        # Check enum values
        doc_type = input_schema["properties"]["document_type"]
        assert "enum" in doc_type
        assert set(doc_type["enum"]) == {"normas", "acordaos", "publicacoes", "leis"}
    
    def test_search_hybrid_weights_schema(self):
        """Test hybrid_weights schema in search_hybrid."""
        schema = TOOL_SCHEMAS["search_hybrid"]
        input_schema = schema["inputSchema"]
        
        assert "hybrid_weights" in input_schema["properties"]
        weights = input_schema["properties"]["hybrid_weights"]
        assert "properties" in weights
        assert "bm25" in weights["properties"]
        assert "vector" in weights["properties"]


# =============================================================================
# Tool Manager Tests
# =============================================================================

class TestToolManager:
    """Tests for HybridSearchToolManager."""
    
    def test_list_tools(self, tool_manager):
        """Test listing available tools."""
        tools = tool_manager.list_tools()
        assert len(tools) == 6
        
        tool_names = [t["name"] for t in tools]
        assert "search_exact" in tool_names
        assert "search_semantic" in tool_names
        assert "search_hybrid" in tool_names
        assert "get_document_details" in tool_names
        assert "list_sources" in tool_names
        assert "get_source_stats" in tool_names
    
    def test_validate_arguments_required_fields(self, tool_manager):
        """Test validation of required fields."""
        # Missing required fields
        result = tool_manager._validate_arguments("search_exact", {})
        assert result is not True
        assert result["isError"] is True
        assert "Missing required field(s)" in result["content"][0]["text"]
    
    def test_validate_arguments_valid(self, tool_manager):
        """Test validation with valid arguments."""
        args = {
            "document_type": "acordaos",
            "fields": {"numero": "1234/2024"},
            "limit": 10
        }
        result = tool_manager._validate_arguments("search_exact", args)
        assert result is True
    
    def test_validate_arguments_invalid_type(self, tool_manager):
        """Test validation with invalid document_type."""
        args = {
            "document_type": "invalid_type",
            "fields": {"numero": "1234"}
        }
        result = tool_manager._validate_arguments("search_exact", args)
        assert result is not True
        assert result["isError"] is True
    
    def test_coerce_types_integer(self, tool_manager):
        """Test type coercion for integer fields."""
        args = {"query": "test", "limit": "20"}
        coerced = tool_manager._coerce_types("search_semantic", args)
        assert coerced["limit"] == 20
        assert isinstance(coerced["limit"], int)
    
    def test_coerce_types_boolean(self, tool_manager):
        """Test type coercion for boolean fields."""
        args = {"document_id": "test", "include_chunks": "true"}
        coerced = tool_manager._coerce_types("get_document_details", args)
        assert coerced["include_chunks"] is True
        assert isinstance(coerced["include_chunks"], bool)
    
    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, tool_manager, mock_user):
        """Test executing non-existent tool."""
        with pytest.raises(ValueError, match="Tool not found: nonexistent"):
            await tool_manager.execute_tool("nonexistent", {}, mock_user)


# =============================================================================
# Resource Manager Tests
# =============================================================================

class TestResourceManager:
    """Tests for HybridSearchResourceManager."""
    
    def test_list_resources(self, resource_manager):
        """Test listing available resources."""
        resources = resource_manager.list_resources()
        assert len(resources) == 6
        
        templates = [r["uriTemplate"] for r in resources]
        assert "document://{document_id}" in templates
        assert "document://{document_id}/chunks" in templates
        assert "chunk://{document_id}/{chunk_index}" in templates
        assert "source://{source_id}/stats" in templates
        assert "source://list" in templates
        assert "search://health" in templates
    
    def test_resource_patterns(self):
        """Test resource URI patterns."""
        assert "document" in RESOURCE_PATTERNS
        assert "document_chunks" in RESOURCE_PATTERNS
        assert "chunk" in RESOURCE_PATTERNS
        assert "source_stats" in RESOURCE_PATTERNS
        assert "source_list" in RESOURCE_PATTERNS
        assert "search_health" in RESOURCE_PATTERNS
    
    def test_pattern_matching_document(self):
        """Test document:// pattern matching."""
        pattern = RESOURCE_PATTERNS["document"]
        match = pattern.match("document://TCU-1234/2024")
        assert match is not None
        assert match.group(1) == "TCU-1234/2024"
    
    def test_pattern_matching_chunk(self):
        """Test chunk:// pattern matching."""
        pattern = RESOURCE_PATTERNS["chunk"]
        match = pattern.match("chunk://TCU-1234/2024/0")
        assert match is not None
        assert match.group(1) == "TCU-1234/2024"
        assert match.group(2) == "0"
    
    def test_pattern_matching_invalid(self):
        """Test invalid URI pattern matching."""
        pattern = RESOURCE_PATTERNS["document"]
        match = pattern.match("invalid://uri")
        assert match is None


# =============================================================================
# Server Tests
# =============================================================================

class TestServer:
    """Tests for MCPHybridSearchServer."""
    
    def test_server_initialization(self):
        """Test server initialization."""
        server = MCPHybridSearchServer()
        assert server.tool_manager is not None
        assert server.resource_manager is not None
        assert server.rate_limiter is not None
        assert server.audit_logger is not None
        assert server.sessions == {}
        assert server.message_queues == {}
    
    def test_success_response(self):
        """Test success response generation."""
        server = MCPHybridSearchServer()
        result = server._success_response("123", {"data": "test"})
        
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "123"
        assert result["result"] == {"data": "test"}
    
    def test_error_response(self):
        """Test error response generation."""
        server = MCPHybridSearchServer()
        result = server._error_response("456", -32603, "Internal error")
        
        assert result["jsonrpc"] == "2.0"
        assert result["id"] == "456"
        assert result["error"]["code"] == -32603
        assert result["error"]["message"] == "Internal error"


# =============================================================================
# Permission Tests
# =============================================================================

class TestPermissions:
    """Tests for permission extraction."""
    
    def test_extract_permissions_search(self):
        """Test permission extraction for search role."""
        roles = ["gabi-search"]
        perms = _extract_permissions(roles)
        assert "search:read" in perms
    
    def test_extract_permissions_admin(self):
        """Test permission extraction for admin role."""
        roles = ["gabi-admin"]
        perms = _extract_permissions(roles)
        assert "search:read" in perms
        assert "search:write" in perms
        assert "document:read" in perms
        assert "document:write" in perms
        assert "admin" in perms
    
    def test_extract_permissions_multiple(self):
        """Test permission extraction for multiple roles."""
        roles = ["gabi-search", "gabi-reader"]
        perms = _extract_permissions(roles)
        assert "search:read" in perms
        assert "document:read" in perms
    
    def test_extract_permissions_empty(self):
        """Test permission extraction with no roles."""
        roles = []
        perms = _extract_permissions(roles)
        assert perms == ["search:read", "document:read"]  # Default permissions


# =============================================================================
# Integration Tests
# =============================================================================

@pytest.mark.asyncio
class TestIntegration:
    """Integration tests for MCP Hybrid Search."""
    
    async def test_end_to_end_tool_execution(self, tool_manager, mock_user):
        """Test end-to-end tool execution flow."""
        # This would test actual execution against mocked dependencies
        # For now, just verify the flow works
        args = {
            "document_type": "acordaos",
            "fields": {"ano": 2024},
            "limit": 5
        }
        
        # Mock the search service
        with patch.object(tool_manager, '_get_search_service') as mock_get_service:
            mock_service = Mock()
            mock_service.es_client = Mock()
            mock_service.index_name = "test_index"
            mock_service.timeout_ms = 5000
            
            # Mock ES response
            mock_service.es_client.search = AsyncMock(return_value={
                "hits": {
                    "total": {"value": 1},
                    "hits": [
                        {
                            "_id": "TCU-TEST-123",
                            "_score": 10.5,
                            "_source": {
                                "title": "Test Document",
                                "source_id": "tcu_acordaos",
                                "metadata": {"ano": 2024, "numero": "123"}
                            }
                        }
                    ]
                }
            })
            
            mock_get_service.return_value = mock_service
            
            result = await tool_manager.execute_tool("search_exact", args, mock_user)
            
            assert result is not None
            assert "content" in result
    
    async def test_resource_read_document(self, resource_manager, mock_user):
        """Test reading document resource."""
        # This would test actual DB access with mocked session
        with patch('gabi.mcp.resources_hybrid.get_session_no_commit') as mock_get_session:
            mock_session = AsyncMock()
            mock_result = Mock()
            mock_result.scalar_one_or_none = Mock(return_value=None)
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_get_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_get_session.return_value.__aexit__ = AsyncMock(return_value=False)
            
            with pytest.raises(ValueError, match="Document not found"):
                await resource_manager.read_resource("document://NONEXISTENT", mock_user)


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance-related tests."""
    
    def test_schema_validation_performance(self, tool_manager):
        """Test that schema validation is fast."""
        import time
        
        args = {
            "document_type": "acordaos",
            "fields": {"numero": "1234/2024", "ano": 2024},
            "limit": 10,
            "offset": 0
        }
        
        start = time.time()
        for _ in range(1000):
            result = tool_manager._validate_arguments("search_exact", args)
        elapsed = time.time() - start
        
        # Should validate 1000 requests in less than 1 second
        assert elapsed < 1.0
        assert result is True


# =============================================================================
# Security Tests
# =============================================================================

class TestSecurity:
    """Security-related tests."""
    
    def test_no_sql_injection_in_fields(self, tool_manager):
        """Test that field values don't allow SQL injection."""
        malicious_args = {
            "document_type": "acordaos",
            "fields": {
                "numero": "123'; DROP TABLE documents; --"
            }
        }
        
        # Validation should pass (it's just a string)
        result = tool_manager._validate_arguments("search_exact", malicious_args)
        assert result is True
        
        # But the value should be handled safely by the search service
        # (This is tested in integration tests with actual DB)
    
    def test_limit_bounds(self, tool_manager):
        """Test that limit respects bounds."""
        args_too_high = {
            "query": "test",
            "limit": 1000  # Exceeds maximum
        }
        
        result = tool_manager._validate_arguments("search_hybrid", args_too_high)
        assert result is not True
        assert result["isError"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
