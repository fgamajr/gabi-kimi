> Last verified: 2026-03-06

# MCP Dev Setup

This subsystem is a dev-only multi-agent adversarial convergence server. It is isolated under
`.dev/mcp/` and does not import or depend on the host project's runtime modules.

## Purpose

Use this when a primary coding agent wants adversarial review from multiple external models, then
iteratively revise an artifact until:

- the revised artifact produces zero diff against the previous round, and
- every adversarial reviewer returns `APPROVE`

If convergence does not happen by `max_rounds`, the engine returns the best available artifact plus
unresolved objections.

## Architecture

```text
user prompt + artifact
        |
        v
  converge_artifact
        |
        v
  agent selection
        |
        +--> reviewer 1
        +--> reviewer 2
        +--> reviewer 3
        |
        v
  orchestrator revision
        |
        v
   diff + approval check
        |
   converged? ------ no ------> next round
        |
       yes
        v
  final artifact + run log
```

## Files

- `.dev/mcp/server.py`: MCP server entrypoint
- `.dev/mcp/engine.py`: convergence loop
- `.dev/mcp/adapters.py`: DashScope and Anthropic adapters
- `.dev/mcp/selection.py`: prompt-driven reviewer/persona selection
- `.dev/mcp/logger.py`: per-round run logging
- `.dev/mcp/mcp-agents.yaml`: provider/agent/default config
- `.dev/mcp/requirements.txt`: isolated dependency set
- `.dev/mcp/test_system.py`: local non-network self-test

## Provider Notes

### DashScope-compatible agents

Kimi, Qwen, and GLM all use the same OpenAI-compatible base URL and the same API key, changing only
the model string.

- Base URL: `https://coding-intl.dashscope.aliyuncs.com/v1`
- Primary key env: `DASHSCOPE_API_KEY`
- Models:
  - `kimi-k2.5`
  - `qwen3-max`
  - `glm-5`

Thinking mode is handled by the adapter and parsed from `reasoning_content`. The adapter supports:

- OpenAI SDK path if `openai` is installed
- raw HTTP fallback if it is not

In this repository scope, the DashScope-compatible agents do not use per-model keys. They share the
gateway credential:

- `DASHSCOPE_API_KEY`
- fallback aliases: `DASHSCOPE_API_API_KEY`, `ALIBABA_API_KEY`
- optional endpoint override: `DASHSCOPE_BASE_URL`

### Anthropic / Claude

Claude uses the Anthropic Messages API semantics and is handled by a separate adapter.

- Base URL: `https://api.anthropic.com/v1`
- Key env: `ANTHROPIC_API_KEY`
- Model: `claude-sonnet-4-20250514`

Extended thinking is parsed from Anthropic thinking blocks when enabled, though the default config
keeps `enable_thinking: false` for Claude.

## Config Schema

Main config file: `.dev/mcp/mcp-agents.yaml`

Top-level sections:

- `providers`
- `agents`
- `defaults`

Key fields:

- `providers.*.base_url`
- `providers.*.key_env`
- `providers.*.sdk`
- `providers.*.streaming`
- `agents.*.provider`
- `agents.*.model`
- `agents.*.enable_thinking`
- `agents.*.context_window`
- `agents.*.max_response`
- `agents.*.personas`
- `defaults.max_rounds`
- `defaults.parallel`
- `defaults.log_dir`
- `defaults.convergence.zero_diff`
- `defaults.convergence.unanimous_approve`

## Agent Selection

Default behavior:

- reviewers: all available agents with configured API keys
- persona: `general`
- orchestrator priority: `claude -> qwen -> kimi -> zai`

Keyword heuristics:

- `security`, `vuln`, `threat` -> `security`
- `performance`, `optimize`, `latency` -> `performance`
- `architecture`, `design`, `scalability` -> `architecture`

Explicit reviewer constraints:

- `use only Claude and Qwen`
- `use only Kimi`

## MCP Tools

### `agent_config`

Returns providers, agents, defaults, config path, and which agents are currently available based on
API keys.

### `converge_artifact`

Inputs:

- `user_prompt`
- `initial_artifact`
- `artifact_kind`
- `orchestrator`
- `reviewers`
- `max_rounds`
- `conversation_history`
- `run_label`

Output:

- selected agent roster
- per-round metrics
- final artifact
- convergence status
- unresolved objections
- run log path

## Run Logging

Each run is written under:

```text
.dev/mcp/runs/{timestamp}/
```

Per round:

- `artifact.before.txt`
- `artifact.after.txt`
- `diff.patch`
- `metrics.json`
- `reviews/{agent}.json`

Run-level files:

- `run.json`
- `final.json`

## Installation

```bash
python3 -m venv .dev/mcp/.venv
source .dev/mcp/.venv/bin/activate
pip install -r .dev/mcp/requirements.txt
```

## Running

stdio:

```bash
.dev/mcp/.venv/bin/python .dev/mcp/server.py
```

SSE:

```bash
.dev/mcp/.venv/bin/python .dev/mcp/server.py --transport sse --port 8770
```

## Example MCP Client Config

VS Code style:

```json
{
  "servers": {
    "dev-converge": {
      "type": "stdio",
      "command": "/abs/path/to/.dev/mcp/.venv/bin/python",
      "args": ["/abs/path/to/.dev/mcp/server.py"]
    }
  }
}
```

## Example Usage

Natural language:

```text
Use the dev-converge.converge_artifact tool. Review this patch with Claude, Kimi, Qwen, and ZAI.
Treat them as adversarial code reviewers and converge on a final version.
```

Structured:

```json
{
  "user_prompt": "Harden this auth middleware for security and performance.",
  "artifact_kind": "code",
  "initial_artifact": "def middleware(...): ...",
  "reviewers": ["claude", "kimi", "qwen", "zai"],
  "max_rounds": 5
}
```

## API Quirks

- DashScope thinking output arrives in `reasoning_content`, not `content`
- DashScope streaming usage can arrive late in the stream
- Anthropic uses different request and response shapes from OpenAI-compatible APIs
- GLM function calling is not wired here because this subsystem only needs critique and synthesis

## Isolation Guarantee

- everything lives under `.dev/mcp/`
- no imports from `src/backend/ingest/`, `src/backend/search/`, `web_server.py`, or other host project modules
- only `.env.example` is updated at repo root, solely to document the required API keys
