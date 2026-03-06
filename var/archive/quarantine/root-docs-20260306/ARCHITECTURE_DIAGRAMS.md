# GABI Architecture Diagrams

> Last verified: 2026-03-06

## 1. Operational Data Path

```text
in.gov.br catalog
  -> ingest.catalog_scraper / ingest.zip_downloader
  -> ZIP bundles
  -> ingest.xml_parser + ingest.dou_ingest
  -> PostgreSQL dou.*
  -> BM25 / Elasticsearch / chunk backfill
  -> web_server.py + mcp_es_server.py
```

## 2. Registry and Sealing Path

```text
ZIP bundles
  -> ingest.bulk_pipeline
  -> ingest.normalizer
  -> dbsync.registry_ingest
  -> registry.*
  -> commitment/*
  -> proofs/
```

## 3. Retrieval Layers

```text
dou.document
  -> ingest.bm25_indexer
  -> PostgreSQL BM25

dou.document
  -> ingest.es_indexer
  -> gabi_documents_v1

dou.document
  -> scripts/backfill_chunks.py
  -> dou.document_chunk
  -> ingest.embedding_pipeline
  -> gabi_chunks_v1
```

## 4. Hybrid Search

```text
query
  -> search/adapters.py
     -> lexical candidates from gabi_documents_v1
     -> vector candidates from gabi_chunks_v1
     -> reciprocal rank fusion
     -> basic rerank
  -> web_server.py / mcp_es_server.py
```

## 5. Serving Layer

```text
web/index.html
  <- web_server.py
     <- search/adapters.py

VS Code / Claude / Codex
  <- mcp_es_server.py
     <- search/adapters.py
```
