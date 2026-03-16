# GABI Handover

Updated: 2026-03-16
Branch: `frontend`
Last pushed commit before this handover: `aeccb7d`

## What Is Already Pushed

The repo-side no-VM migration is on `origin/frontend`.

Included in `aeccb7d`:
- portable Docker storage paths via env vars instead of `/media/psf/...`
- repo-local defaults under `./.data/*`
- portable ES cursor path
- repo MCP installer for `Zed`, `Kiro`, and `Kilo`
- updated `README.md` and `.env.example`

## Goal

Continue this project from a Mac clone without depending on the Ubuntu VM.

## Current Reality

The overnight raw rebuild finished previously into Mongo with about `15.77M` documents, but the current Linux stack is no longer trustworthy as a continuation point:
- Elasticsearch is currently restarting
- the current blocker is a bind-mount ownership / lock problem on the portable ES data path
- no backfill should be resumed from this VM state

Observed error in Elasticsearch logs:
- `failed to obtain node locks`
- `AccessDeniedException: /usr/share/elasticsearch/data/node.lock`

This means the repo-side portability work is pushed, but the live VM runtime is not the place to continue from.

## Local-Only Changes Not Pushed

These files still have local edits in the VM and were intentionally not pushed in the portability commit:
- `AGENTS.md`
- `ops/bin/mcp_es_server.py`
- `ops/setup_elasticsearch.sh`
- `src/backend/core/config.py`
- `src/backend/ingest/dou_processor.py`
- `src/backend/ingest/field_extractors.py`
- `src/backend/ingest/sync_dou.py`
- `src/backend/main.py`

Also present locally only:
- `GEMINI.MD`
- `ops/bin/monitor_ingest.sh`
- `ops/bin/run_overnight_ingest.sh`

Do not assume those changes exist on the Mac after clone.

## Recommended Mac Continuation

1. Clone the repo and checkout `frontend`.
2. Create env file:

```bash
cp .env.example .env
```

3. Prepare data directories:

```bash
mkdir -p .data/mongo .data/elasticsearch .data/dou
```

4. Start fresh:

```bash
docker compose build
docker compose up -d
```

5. Install repo MCP entries for local desktop clients:

```bash
python3 ops/bin/install_repo_mcp_clients.py --create-missing
```

6. Verify services:

```bash
docker compose ps
curl -s http://127.0.0.1:8001/
```

## If Elasticsearch Fails On The Mac Too

If the same bind-mount ownership problem appears on macOS, try:

```bash
rm -rf .data/elasticsearch
mkdir -p .data/elasticsearch
docker compose up -d elasticsearch
```

If that still fails, the next fallback is to switch Elasticsearch from a bind mount to a named Docker volume.

## Data / Index Status Summary

Known good historical checkpoints from the VM session:
- raw Mongo ingest previously completed through the current registry coverage
- count observed: about `15,771,256`
- Elasticsearch backfill was running successfully for a while after tuning:
  - heap raised to `1g`
  - batch size reduced to `500`
  - timeout raised to `300s`

But because the current ES container is now restarting, treat the Mac as a fresh continuation point.

## MCP / Tooling Status

Machine-wide MCP infrastructure was already normalized earlier.

Repo-local installer added for:
- `Zed`
- `Kiro`
- `Kilo`

Mac-side Claude / Codex native configs were not updated in this commit. Those remain separate machine-level concerns.

## Next Best Step On The Mac

After clone and boot:
1. verify Docker stack comes up cleanly
2. verify `gabi-es` MCP works locally
3. decide whether to:
   - restart raw ingest from zero on the Mac, or
   - restore a known-good Mongo snapshot first and then backfill ES

If restarting ES backfill from Mongo, use the stabilized form:

```bash
docker compose exec -T backend env ES_TIMEOUT_SEC=300 python -m src.backend.ingest.es_indexer backfill --recreate-index --batch-size 500
```

## Important Constraint

The repo is now much closer to VM-free, but this handover does not mean every machine-level integration is finished. It means the repo itself can now be cloned and run on a Mac without hardcoded VM filesystem paths.
