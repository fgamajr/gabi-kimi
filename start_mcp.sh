#!/bin/bash
echo "🚀 Starting GABI MCP Server..."
cd "$(dirname "$0")"
export PYTHONPATH=src:$PYTHONPATH
export $(cat .env | grep -v '^#' | xargs)
exec python -m gabi.mcp.server
