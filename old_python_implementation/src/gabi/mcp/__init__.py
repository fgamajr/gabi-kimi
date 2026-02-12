"""
GABI MCP (Model Context Protocol) Module.

This module provides MCP server implementations for ChatTCU integration:
- Legacy MCP Server (server.py, tools.py, resources.py)
- Hybrid Search MCP Server (server_hybrid.py, tools_hybrid.py, resources_hybrid.py)

The Hybrid Search MCP Server is the recommended implementation for new deployments,
providing:
- search_exact: Exact search by specific fields
- search_semantic: Semantic/meaning-based search  
- search_hybrid: Combined exact + semantic with RRF
- SSE transport for real-time communication
- JWT authentication via Keycloak
- Redis-based rate limiting
"""

# Legacy exports (for backwards compatibility)
from gabi.mcp.server import MCPServer, create_mcp_app, get_current_user
from gabi.mcp.tools import MCPToolManager, get_tool_manager, TOOL_SCHEMAS
from gabi.mcp.resources import MCPResourceManager, get_resource_manager, RESOURCE_PATTERNS

# New Hybrid Search exports (recommended)
from gabi.mcp.server_hybrid import (
    MCPHybridSearchServer,
    create_mcp_hybrid_app,
    get_mcp_server,
)
from gabi.mcp.tools_hybrid import (
    HybridSearchToolManager,
    get_hybrid_tool_manager,
    TOOL_SCHEMAS as HYBRID_TOOL_SCHEMAS,
    EXACT_SEARCH_FIELDS,
)
from gabi.mcp.resources_hybrid import (
    HybridSearchResourceManager,
    get_hybrid_resource_manager,
    RESOURCE_PATTERNS as HYBRID_RESOURCE_PATTERNS,
    DocumentResource,
    ChunkResource,
    SourceResource,
)

__all__ = [
    # Legacy
    "MCPServer",
    "create_mcp_app",
    "MCPToolManager",
    "get_tool_manager",
    "TOOL_SCHEMAS",
    "MCPResourceManager",
    "get_resource_manager",
    "RESOURCE_PATTERNS",
    "get_current_user",
    
    # Hybrid Search (New)
    "MCPHybridSearchServer",
    "create_mcp_hybrid_app",
    "get_mcp_server",
    "HybridSearchToolManager",
    "get_hybrid_tool_manager",
    "HYBRID_TOOL_SCHEMAS",
    "EXACT_SEARCH_FIELDS",
    "HybridSearchResourceManager",
    "get_hybrid_resource_manager",
    "HYBRID_RESOURCE_PATTERNS",
    "DocumentResource",
    "ChunkResource",
    "SourceResource",
]

# Version
__version__ = "2.0.0"
