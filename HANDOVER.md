# GABI DOU — Handover: From System to Script

## What We Had (v1.0–v1.1)

- **Infrastructure**: 5 Fly.io apps (web, worker, db, es, frontend).
- **Stack**: PostgreSQL + Redis + Elasticsearch + MinIO.
- **Pipeline**: Complex worker system:
    - Discovery → Backfill → Download → Extract → BM25 Index → Embed → Verify.
- **Backend**: FastAPI web server with auth, sessions, rate limiting.
- **Frontend**: React frontend with AppShell, search, analytics, chat, pipeline dashboard.

**Status**: All Fly.io infrastructure is now destroyed. Secrets backed up in `.env.fly-backup`.

## The New Vision (v2.0)

We are collapsing the entire backend into a single Python script (`sync_dou.py`) that leverages MongoDB Atlas for both storage and search.

### Architecture

- **Script**: `sync_dou.py` (The Orchestrator).
- **Data Map**: `ops/data/dou_catalog_registry.json` (The Compass).
- **Database**: MongoDB Atlas (Free Tier/Serverless).
- **Search**: MongoDB Atlas Search (Lucene with `lucene.brazilian` analyzer).

### Workflow

1.  **Read Compass**: The script reads `ops/data/dou_catalog_registry.json` to know what files exist.
2.  **Download**: Iterates year by year (starting 2002), downloading ZIPs directly.
3.  **Parse**: Extracts XML content from ZIPs in memory or temp storage.
4.  **Ingest**: Inserts structured documents directly into MongoDB.
5.  **Search Indexing**: MongoDB Atlas automatically updates its Lucene index (BM25) based on the inserted data.

### Key Advantages

- **Simplicity**: No more managing 5 different services and containers. Just one script and one DB.
- **Cost**: MongoDB Atlas Free Tier is sufficient for initial scale vs paying for multiple Fly.io VMs.
- **Search**: Built-in Lucene search in Atlas eliminates the need for a separate Elasticsearch cluster.
- **Maintenance**: No more complex worker queues (Redis/Celery/Arq) or distributed system issues.

## Next Steps

1.  **Create Script**: Implement `sync_dou.py` to handle the download and ingestion loop.
2.  **Setup Atlas**: Configure the MongoDB Atlas cluster and create the Search Index definition.
3.  **Run Backfill**: Execute the script starting from 2002 to repopulate the database.
4.  **Update Frontend**: Point the React frontend (or a simplified version) to query MongoDB Atlas directly (via Data API or a thin serverless function).
