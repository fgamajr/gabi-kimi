from __future__ import annotations

import sqlite3

from src.backend.repo_index.config import settings


_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL UNIQUE,
    source_path TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    authority_weight REAL NOT NULL,
    language TEXT NOT NULL,
    kind TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    pipeline_fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    is_duplicate INTEGER NOT NULL DEFAULT 0,
    duplicate_of TEXT,
    indexed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL UNIQUE,
    doc_id TEXT NOT NULL REFERENCES files(doc_id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    symbol TEXT,
    chunk_type TEXT NOT NULL,
    chunk_seq INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    authority_weight REAL NOT NULL,
    section_type TEXT NOT NULL,
    chunk_manifest_hash TEXT NOT NULL,
    chunk_feature_hash TEXT NOT NULL,
    entity_density REAL NOT NULL,
    importance_score REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(chunk_id);
CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (chunk_id, provider, model, dims)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    path,
    symbol,
    content,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def get_connection() -> sqlite3.Connection:
    settings.index_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn
