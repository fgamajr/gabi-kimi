"""
MCP (Model Context Protocol) - Integração com ChatTCU

Este pacote implementa o servidor MCP para integração com sistemas LLM.

Uso:
    from gabi.mcp.server import create_mcp_app
    
    app = create_mcp_app()
    
    # Ou standalone:
    # python -m gabi.mcp.server

Componentes:
- server.py: Servidor MCP com SSE transport
- tools.py: Ferramentas disponíveis (search_documents, etc)
- resources.py: Recursos acessíveis (document://, source://)

Spec: MCP 2025-03-26
"""

from gabi.mcp.server import create_mcp_app, mcp_server
from gabi.mcp.tools import MCPToolManager, get_tool_manager
from gabi.mcp.resources import MCPResourceManager, get_resource_manager

__all__ = [
    "create_mcp_app",
    "mcp_server",
    "MCPToolManager",
    "get_tool_manager",
    "MCPResourceManager",
    "get_resource_manager",
]

__version__ = "1.0.0"
