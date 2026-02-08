# AGENT-5: MCP Server Agent

## Role
Start and validate Model Context Protocol server for ChatTCU integration

## Scope
- src/gabi/mcp/
- MCP tools and resources
- Integration with main API

## YOLO Mode Instructions
1. **STANDALONE MODE** - Start MCP even if ChatTCU not available
2. **TOOL REGISTRATION** - Verify all tools register correctly
3. **MOCK RESPONSES** - If services unavailable, return mock data for testing
4. **SPEC COMPLIANCE** - Ensure 2025-03-26 MCP spec compliance

## Tasks

### PHASE 1: Wait for API (Blocked until AGENT-3 completes)
Poll `.swarm/status/AGENT-3.json` for `status == "completed"`

### PHASE 2: MCP Server Startup (5-10 min)
```bash
# Determine MCP port (default 3000, but check availability)
if lsof -Pi :3000 -sTCP:LISTEN -t >/dev/null ; then
    export MCP_PORT=3001
else
    export MCP_PORT=3000
fi

# Start MCP server
# (Implementation depends on how MCP server is started in this project)
python -c "
from src.gabi.mcp.server import MCPServer
# Start server
" &
MCP_PID=$!
echo $MCP_PID > .swarm/agents/5-mcp/mcp.pid

# Wait for startup
sleep 3
```

### PHASE 3: MCP Tools Validation (10-15 min)
```bash
# Verify tools are registered
python -c "
from src.gabi.mcp.tools import TOOLS
print(f'Registered tools: {list(TOOLS.keys())}')
"

# Test tool execution if possible
python -c "
from src.gabi.mcp.tools import search_documents_tool
# Test with sample query
result = search_documents_tool(query='test', sources=['tcu_acordaos'])
print(f'Tool result: {result}')
" 2>/dev/null || echo "Tool test skipped (dependencies not ready)"
```

### PHASE 4: Resources Validation (15-20 min)
```bash
# Verify resources
python -c "
from src.gabi.mcp.resources import RESOURCES
print(f'Available resources: {list(RESOURCES.keys())}')
"

# Test resource endpoints
curl -s http://localhost:${MCP_PORT}/resources 2>/dev/null || echo "Resources endpoint not available"
```

### PHASE 5: Spec Compliance Check (20-25 min)
```bash
# Verify MCP spec 2025-03-26 compliance
# Check protocol version
# Validate schema
python -c "
from src.gabi.mcp.server import PROTOCOL_VERSION
print(f'MCP Protocol Version: {PROTOCOL_VERSION}')
assert PROTOCOL_VERSION >= '2025-03-26', 'Protocol version outdated!'
"
```

## Output Artifacts
Write to `.swarm/artifacts/AGENT-5-report.md`:
- MCP server status
- Registered tools list
- Registered resources list
- Protocol version
- ChatTCU connectivity status

## Status Updates
Write to `.swarm/status/AGENT-5.json` every 2 minutes.

## Dependencies
- AGENT-3 (MCP needs API for backend calls)

## Blocks
- AGENT-8 (needs MCP for integration tests)
