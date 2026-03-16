# Machine-Wide Tooling

This repository should not be the source of truth for machine-local agent and MCP state.

Keep these machine-wide instead:

- Claude desktop MCP config: `/home/parallels/.config/Claude/claude_desktop_config.json`
- Claude user commands/prompts/settings: `/home/parallels/.claude/`
- Agent skills: `/home/parallels/.agents/`
- Shared local MCP tool payloads: `/home/parallels/.local/share/ai-devtools/`
- Editor-specific local MCP config backups: `/home/parallels/.config/gabi-kimi/`

What stays in the repo:

- Project source code and scripts
- Project-specific MCP server entrypoints such as `ops/bin/mcp_es_server.py`
- Project instructions in `AGENTS.md`
- Project documentation under `docs/`

What should not be committed:

- `.mcp.json`
- `.dev/`
- `.agents/`
- `.claude/`
- `.cursor/`
- editor-local or machine-local state
