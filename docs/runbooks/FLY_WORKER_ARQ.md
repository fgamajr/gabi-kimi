# Fly.io ARQ Worker (GABI Admin Upload)

Last updated: 2026-03-08

This runbook covers the ARQ worker process that runs alongside the web process on Fly.io, consuming jobs from Redis (Phase 4). Later phases wire it to process upload jobs from admin.worker_jobs.

## Fly.io: Web + Worker Process Groups

The app `gabi-dou-web` runs two process groups defined in `ops/deploy/web/fly.toml`:

- **web** – FastAPI (python ops/bin/web_server.py), 512MB, receives HTTP traffic
- **worker** – ARQ worker (arq src.backend.workers.arq_worker.WorkerSettings), 1GB RAM, no HTTP

Both use the same Docker image and share `[env]` (including `REDIS_URL`). Each process group has its own `[[vm]]` so the worker has 1GB memory for future XML/ZIP processing.

After deploy, scale worker (default is 1 machine per process group):

```bash
fly scale count worker=1 -a gabi-dou-web
fly status -a gabi-dou-web
```

## Running the Worker Locally

1. **Redis** – Local Redis on 6379 or set `REDIS_URL` (e.g. `redis://localhost:6379/0`).

2. **Start the worker** (from repo root, with `src` on PYTHONPATH / run from directory that contains `src`):

   ```bash
   cd /path/to/gabi-kimi
   export REDIS_URL=redis://localhost:6379/0
   arq src.backend.workers.arq_worker.WorkerSettings
   ```

   Or with Python module run (if arq supports it):

   ```bash
   python -m arq src.backend.workers.arq_worker.WorkerSettings
   ```

   Check arq docs: the standard way is `arq module.WorkerSettings`.

3. **Enqueue a test task** (Python):

   ```python
   import asyncio
   from arq import create_pool
   from arq.connections import RedisSettings

   async def main():
       redis = await create_pool(RedisSettings.from_dsn("redis://localhost:6379/0"))
       job = await redis.enqueue_job("test_task", "hello")
       print("Enqueued:", job)
       result = await job.result(timeout=5)
       print("Result:", result)  # echo: hello

   asyncio.run(main())
   ```

   Or use the arq CLI to enqueue (if available), or call the same from a small script in the repo.

## Success Criteria (Phase 4)

1. fly.toml defines web and worker process groups with correct entrypoints
2. Worker process starts and connects to Redis as an ARQ worker
3. Worker process has 1GB+ RAM ([[vm]] processes = ["worker"] memory = "1gb")
4. Enqueuing a test task (e.g. test_task with a string) results in the worker running it and returning the result

## References

- [Fly.io Run multiple process groups](https://fly.io/docs/launch/processes/)
- [arq documentation](https://arq-docs.helpmanual.io/)
