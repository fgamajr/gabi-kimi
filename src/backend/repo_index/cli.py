"""SQLite-backed repo index with FTS5 and optional embedding cache.

Usage:
  python3 -m src.backend.repo_index build
  python3 -m src.backend.repo_index build --with-embeddings
  python3 -m src.backend.repo_index query "multipart reconstruction"
  python3 -m src.backend.repo_index stats
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import ssl
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_DIR = REPO_ROOT / ".ai"
DB_PATH = INDEX_DIR / "repo_index.db"
MANIFEST_PATH = INDEX_DIR / "manifest.json"

SKIP_DIRS = {
    ".ai",
    ".git",
    ".idea",
    ".next",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".venv-mac",
    ".vite",
    ".vscode",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
    "ops/data/raw_export",
}
SKIP_FILES = {
    ".DS_Store",
    "bun.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
SPECIAL_TEXT_FILENAMES = {".dockerignore", ".gitignore", "Dockerfile", "Makefile"}
TEXT_EXTENSIONS = {
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".go",
    ".h",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
MAX_FILE_BYTES = 512_000
MAX_CHUNK_CHARS = 4_000
WINDOW_LINES = 80
WINDOW_OVERLAP = 12

PY_SYMBOL_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)\b")
JS_TS_SYMBOL_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+function|function|class|const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"
)
SH_SYMBOL_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")


@dataclass
class FileRecord:
    path: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    language: str
    kind: str
    content: str


@dataclass
class ChunkRecord:
    path: str
    symbol: str | None
    chunk_type: str
    start_line: int
    end_line: int
    content: str
    chunk_hash: str


@dataclass
class EmbeddingConfig:
    provider: str
    model: str
    dims: int | None
    base_url: str
    api_key: str
    timeout_sec: float
    verify_tls: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _load_dotenv() -> dict[str, str]:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'").strip('"')
        env[key.strip()] = value
    return env


def _env(name: str, dotenv: dict[str, str], default: str | None = None) -> str | None:
    return os.getenv(name) or dotenv.get(name) or default


def _embedding_config(dotenv: dict[str, str]) -> EmbeddingConfig:
    api_key = _env("OPENAI_API_KEY", dotenv) or _env("EMBED_API_KEY", dotenv)
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY or EMBED_API_KEY is required for --with-embeddings")
    dims_raw = _env("EMBED_DIM", dotenv)
    dims = int(dims_raw) if dims_raw and dims_raw.isdigit() else None
    verify_tls = (_env("EMBED_VERIFY_TLS", dotenv, "true") or "true").lower() not in {"0", "false", "no"}
    return EmbeddingConfig(
        provider=_env("EMBED_PROVIDER", dotenv, "openai-compatible") or "openai-compatible",
        model=_env("EMBED_MODEL", dotenv, "text-embedding-3-small") or "text-embedding-3-small",
        dims=dims,
        base_url=_env("EMBED_BASE_URL", dotenv, "https://api.openai.com/v1") or "https://api.openai.com/v1",
        api_key=api_key,
        timeout_sec=float(_env("EMBED_TIMEOUT_SEC", dotenv, "30") or "30"),
        verify_tls=verify_tls,
    )


def _language_for_path(path: Path) -> tuple[str, str]:
    if path.name in SPECIAL_TEXT_FILENAMES:
        return "docker", "build"
    suffix = path.suffix.lower()
    if suffix in {".py"}:
        return "python", "code"
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs"}:
        return "typescript" if suffix in {".ts", ".tsx"} else "javascript", "code"
    if suffix in {".md"}:
        return "markdown", "docs"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".example"}:
        return "config", "config"
    if suffix in {".sh"}:
        return "shell", "script"
    if suffix in {".sql"}:
        return "sql", "config"
    if suffix in TEXT_EXTENSIONS:
        return suffix.lstrip("."), "text"
    return "text", "text"


def _is_text_file(path: Path) -> bool:
    if path.name in SKIP_FILES:
        return False
    if path.name in SPECIAL_TEXT_FILENAMES:
        return True
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    return path.name.endswith(".env.example")


def _should_skip_path(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT)
    parts = rel.parts
    joined = "/".join(parts)
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    if joined.startswith("ops/data/raw_export/"):
        return True
    return False


def _scan_files() -> list[FileRecord]:
    files: list[FileRecord] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if _should_skip_path(path) or not _is_text_file(path):
            continue
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        if size_bytes > MAX_FILE_BYTES:
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        content = raw.decode("utf-8", errors="ignore")
        if not content.strip():
            continue
        language, kind = _language_for_path(path)
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        files.append(
            FileRecord(
                path=rel_path,
                sha256=hashlib.sha256(raw).hexdigest(),
                size_bytes=size_bytes,
                mtime_ns=path.stat().st_mtime_ns,
                language=language,
                kind=kind,
                content=content,
            )
        )
    return files


def _symbol_matches(language: str, line: str) -> str | None:
    if language == "python":
        match = PY_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    if language in {"typescript", "javascript"}:
        match = JS_TS_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    if language == "shell":
        match = SH_SYMBOL_RE.match(line)
        return match.group(1) if match else None
    return None


def _split_large_chunk(
    path: str,
    symbol: str | None,
    chunk_type: str,
    start_line: int,
    lines: list[str],
) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    current: list[str] = []
    current_start = start_line
    current_len = 0
    for idx, line in enumerate(lines, start=start_line):
        line_len = len(line) + 1
        if current and current_len + line_len > MAX_CHUNK_CHARS:
            content = "\n".join(current).strip()
            if content:
                chunks.append(
                    ChunkRecord(
                        path=path,
                        symbol=symbol,
                        chunk_type=chunk_type,
                        start_line=current_start,
                        end_line=idx - 1,
                        content=content,
                        chunk_hash=_sha256_text(f"{path}:{symbol}:{current_start}:{content}"),
                    )
                )
            overlap = current[-WINDOW_OVERLAP:] if len(current) > WINDOW_OVERLAP else current[:]
            current = overlap + [line]
            current_start = max(start_line, idx - len(overlap))
            current_len = sum(len(item) + 1 for item in current)
            continue
        current.append(line)
        current_len += line_len
    content = "\n".join(current).strip()
    if content:
        chunks.append(
            ChunkRecord(
                path=path,
                symbol=symbol,
                chunk_type=chunk_type,
                start_line=current_start,
                end_line=start_line + len(lines) - 1,
                content=content,
                chunk_hash=_sha256_text(f"{path}:{symbol}:{current_start}:{content}"),
            )
        )
    return chunks


def _window_chunks(path: str, text: str, chunk_type: str) -> list[ChunkRecord]:
    lines = text.splitlines()
    chunks: list[ChunkRecord] = []
    step = max(1, WINDOW_LINES - WINDOW_OVERLAP)
    for start in range(0, len(lines), step):
        window = lines[start : start + WINDOW_LINES]
        content = "\n".join(window).strip()
        if not content:
            continue
        start_line = start + 1
        chunks.extend(_split_large_chunk(path, None, chunk_type, start_line, window))
        if start + WINDOW_LINES >= len(lines):
            break
    return chunks


def _markdown_chunks(path: str, text: str) -> list[ChunkRecord]:
    lines = text.splitlines()
    headings: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        match = MD_HEADING_RE.match(line)
        if match:
            headings.append((idx, match.group(1).strip()))
    if not headings:
        return _window_chunks(path, text, "markdown_window")
    chunks: list[ChunkRecord] = []
    if headings[0][0] > 1:
        prelude = lines[: headings[0][0] - 1]
        prelude_text = "\n".join(prelude).strip()
        if prelude_text:
            chunks.extend(_split_large_chunk(path, None, "markdown_prelude", 1, prelude))
    for index, (line_no, title) in enumerate(headings):
        next_line = headings[index + 1][0] if index + 1 < len(headings) else len(lines) + 1
        block = lines[line_no - 1 : next_line - 1]
        chunks.extend(_split_large_chunk(path, title, "markdown_section", line_no, block))
    return chunks


def _code_chunks(path: str, text: str, language: str) -> list[ChunkRecord]:
    lines = text.splitlines()
    symbols: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        symbol = _symbol_matches(language, line)
        if symbol:
            symbols.append((idx, symbol))
    if not symbols:
        return _window_chunks(path, text, "code_window")
    chunks: list[ChunkRecord] = []
    if symbols[0][0] > 1:
        prelude = lines[: symbols[0][0] - 1]
        prelude_text = "\n".join(prelude).strip()
        if prelude_text:
            chunks.extend(_split_large_chunk(path, None, "module_prelude", 1, prelude))
    for index, (line_no, symbol) in enumerate(symbols):
        next_line = symbols[index + 1][0] if index + 1 < len(symbols) else len(lines) + 1
        block = lines[line_no - 1 : next_line - 1]
        chunks.extend(_split_large_chunk(path, symbol, "symbol", line_no, block))
    return chunks


def _chunk_file(file_record: FileRecord) -> list[ChunkRecord]:
    if file_record.language == "markdown":
        return _markdown_chunks(file_record.path, file_record.content)
    if file_record.kind in {"code", "script"}:
        return _code_chunks(file_record.path, file_record.content, file_record.language)
    return _window_chunks(file_record.path, file_record.content, f"{file_record.kind}_window")


def _connect_db() -> sqlite3.Connection:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL,
            language TEXT NOT NULL,
            kind TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            symbol TEXT,
            chunk_type TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            token_count INTEGER NOT NULL,
            chunk_hash TEXT NOT NULL,
            content TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
        CREATE INDEX IF NOT EXISTS idx_chunks_hash ON chunks(chunk_hash);
        CREATE TABLE IF NOT EXISTS embeddings (
            chunk_hash TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chunk_hash, provider, model, dims)
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
    )
    return conn


def _reset_build_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM chunks_fts;
        DELETE FROM chunks;
        DELETE FROM files;
        DELETE FROM meta;
        """
    )


def _load_embedding_cache(
    conn: sqlite3.Connection,
    config: EmbeddingConfig,
) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    dims = config.dims or 0
    for row in conn.execute(
        """
        SELECT chunk_hash, vector_json
        FROM embeddings
        WHERE provider = ? AND model = ? AND dims = ?
        """,
        (config.provider, config.model, dims),
    ):
        cache[row["chunk_hash"]] = json.loads(row["vector_json"])
    return cache


def _openai_embed(texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
    payload: dict[str, Any] = {"input": texts, "model": config.model}
    if config.dims:
        payload["dimensions"] = config.dims
    body = json.dumps(payload).encode("utf-8")
    url = f"{config.base_url.rstrip('/')}/embeddings"
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    context = None
    if not config.verify_tls:
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, timeout=config.timeout_sec, context=context) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [item["embedding"] for item in data["data"]]


def _insert_embedding_cache(
    conn: sqlite3.Connection,
    config: EmbeddingConfig,
    embeddings_by_hash: dict[str, list[float]],
) -> None:
    dims = config.dims or (len(next(iter(embeddings_by_hash.values()))) if embeddings_by_hash else 0)
    rows = [
        (chunk_hash, config.provider, config.model, dims, json.dumps(vector), _now_iso())
        for chunk_hash, vector in embeddings_by_hash.items()
    ]
    conn.executemany(
        """
        INSERT OR REPLACE INTO embeddings (chunk_hash, provider, model, dims, vector_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _build_search_all(path: str, symbol: str | None, content: str) -> str:
    head = f"{path}\n{symbol or ''}".strip()
    return f"{head}\n{content}".strip()


def _write_manifest(payload: dict[str, Any]) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _build_index(args: argparse.Namespace) -> None:
    dotenv = _load_dotenv()
    config = _embedding_config(dotenv) if args.with_embeddings else None
    files = _scan_files()
    conn = _connect_db()
    embedding_cache = _load_embedding_cache(conn, config) if config else {}
    _reset_build_tables(conn)

    file_count = 0
    chunk_count = 0
    embedded_count = 0
    missing_embedding_chunks: dict[str, str] = {}

    for file_record in files:
        indexed_at = _now_iso()
        cur = conn.execute(
            """
            INSERT INTO files (path, sha256, size_bytes, mtime_ns, language, kind, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_record.path,
                file_record.sha256,
                file_record.size_bytes,
                file_record.mtime_ns,
                file_record.language,
                file_record.kind,
                indexed_at,
            ),
        )
        file_id = int(cur.lastrowid)
        file_count += 1
        for chunk in _chunk_file(file_record):
            cur = conn.execute(
                """
                INSERT INTO chunks (
                    file_id, path, symbol, chunk_type, start_line, end_line, token_count, chunk_hash, content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    chunk.path,
                    chunk.symbol,
                    chunk.chunk_type,
                    chunk.start_line,
                    chunk.end_line,
                    _estimate_tokens(chunk.content),
                    chunk.chunk_hash,
                    chunk.content,
                ),
            )
            chunk_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO chunks_fts(rowid, path, symbol, content)
                VALUES (?, ?, ?, ?)
                """,
                (chunk_id, chunk.path, chunk.symbol or "", _build_search_all(chunk.path, chunk.symbol, chunk.content)),
            )
            chunk_count += 1
            if config:
                if chunk.chunk_hash in embedding_cache:
                    embedded_count += 1
                else:
                    missing_embedding_chunks[chunk.chunk_hash] = chunk.content

    if config and missing_embedding_chunks:
        items = list(missing_embedding_chunks.items())
        batch_size = max(1, args.embed_batch_size)
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            vectors = _openai_embed([content for _, content in batch], config)
            for (chunk_hash, _), vector in zip(batch, vectors):
                embedding_cache[chunk_hash] = vector
                embedded_count += 1
        _insert_embedding_cache(conn, config, {key: embedding_cache[key] for key in missing_embedding_chunks})

    manifest = {
        "built_at": _now_iso(),
        "repo_root": str(REPO_ROOT),
        "db_path": str(DB_PATH),
        "file_count": file_count,
        "chunk_count": chunk_count,
        "embedding_count": embedded_count if config else 0,
        "with_embeddings": bool(config),
        "embedding_provider": config.provider if config else None,
        "embedding_model": config.model if config else None,
    }
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", ("manifest", json.dumps(manifest)))
    conn.commit()
    conn.close()
    _write_manifest(manifest)
    print(json.dumps(manifest, indent=2))


def _normalize_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./:-]+", query)
    if not tokens:
        raise ValueError("Query must contain at least one searchable token")
    return " ".join(f'"{token.replace("\"", " ").strip()}"' for token in tokens if token.strip())


def _lexical_results(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    fts_query = _normalize_fts_query(query)
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.path,
            c.symbol,
            c.start_line,
            c.end_line,
            c.content,
            bm25(chunks_fts, 1.2, 0.5, 1.0) AS score
        FROM chunks_fts
        JOIN chunks AS c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (fts_query, limit),
    ).fetchall()
    return [
        {
            "chunk_id": row["id"],
            "path": row["path"],
            "symbol": row["symbol"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "content": row["content"],
            "score": float(row["score"]),
        }
        for row in rows
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _semantic_results(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    config: EmbeddingConfig,
) -> list[dict[str, Any]]:
    query_vector = _openai_embed([query], config)[0]
    dims = config.dims or len(query_vector)
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.path,
            c.symbol,
            c.start_line,
            c.end_line,
            c.content,
            e.vector_json
        FROM chunks AS c
        JOIN embeddings AS e ON e.chunk_hash = c.chunk_hash
        WHERE e.provider = ? AND e.model = ? AND e.dims = ?
        """,
        (config.provider, config.model, dims),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        similarity = _cosine_similarity(query_vector, json.loads(row["vector_json"]))
        scored.append(
            {
                "chunk_id": row["id"],
                "path": row["path"],
                "symbol": row["symbol"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "content": row["content"],
                "score": similarity,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def _rrf_fuse(result_sets: list[list[dict[str, Any]]], limit: int) -> list[dict[str, Any]]:
    rank_scores: dict[int, float] = {}
    rows_by_id: dict[int, dict[str, Any]] = {}
    for results in result_sets:
        for rank, row in enumerate(results, start=1):
            chunk_id = int(row["chunk_id"])
            rank_scores[chunk_id] = rank_scores.get(chunk_id, 0.0) + 1.0 / (60 + rank)
            rows_by_id.setdefault(chunk_id, row)
    fused = []
    for chunk_id, score in sorted(rank_scores.items(), key=lambda item: item[1], reverse=True):
        row = dict(rows_by_id[chunk_id])
        row["score"] = score
        fused.append(row)
    return fused[:limit]


def _short_preview(content: str) -> str:
    preview = " ".join(content.strip().split())
    return preview[:240] + ("..." if len(preview) > 240 else "")


def _query_index(args: argparse.Namespace) -> None:
    if not DB_PATH.exists():
        raise RuntimeError(f"Repo index not found at {DB_PATH}. Run build first.")
    conn = _connect_db()
    lexical = _lexical_results(conn, args.query, max(args.limit * 3, 20)) if args.mode in {"lexical", "hybrid"} else []
    semantic: list[dict[str, Any]] = []
    mode = args.mode
    if args.mode in {"semantic", "hybrid"}:
        try:
            dotenv = _load_dotenv()
            config = _embedding_config(dotenv)
            has_cache = conn.execute("SELECT 1 FROM embeddings LIMIT 1").fetchone() is not None
            if has_cache:
                semantic = _semantic_results(conn, args.query, max(args.limit * 3, 20), config)
            elif args.mode == "semantic":
                raise RuntimeError("Semantic mode requires an embedding cache. Run build --with-embeddings first.")
            else:
                mode = "lexical"
        except RuntimeError:
            if args.mode == "semantic":
                raise
            mode = "lexical"
    if mode == "lexical":
        results = lexical[: args.limit]
    elif mode == "semantic":
        results = semantic[: args.limit]
    else:
        results = _rrf_fuse([lexical, semantic], args.limit)
    payload = {
        "mode": mode,
        "query": args.query,
        "count": len(results),
        "results": [
            {
                "path": row["path"],
                "symbol": row["symbol"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "score": row["score"],
                "preview": _short_preview(row["content"]),
            }
            for row in results
        ],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    conn.close()


def _stats(args: argparse.Namespace) -> None:
    del args
    if not DB_PATH.exists():
        raise RuntimeError(f"Repo index not found at {DB_PATH}. Run build first.")
    conn = _connect_db()
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedding_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    manifest_row = conn.execute("SELECT value FROM meta WHERE key = 'manifest'").fetchone()
    manifest = json.loads(manifest_row[0]) if manifest_row else {}
    payload = {
        "db_path": str(DB_PATH),
        "manifest_path": str(MANIFEST_PATH),
        "file_count": file_count,
        "chunk_count": chunk_count,
        "embedding_cache_count": embedding_count,
        "manifest": manifest,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local repo index for code/docs search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="Build or refresh the local repo index")
    build.add_argument("--with-embeddings", action="store_true", help="Populate embedding cache with OpenAI-compatible API")
    build.add_argument("--embed-batch-size", type=int, default=16, help="Embedding batch size for API calls")
    build.set_defaults(func=_build_index)

    query = sub.add_parser("query", help="Query the local repo index")
    query.add_argument("query", help="Search query")
    query.add_argument("--mode", choices=["lexical", "semantic", "hybrid"], default="hybrid")
    query.add_argument("--limit", type=int, default=8)
    query.set_defaults(func=_query_index)

    stats = sub.add_parser("stats", help="Show repo index statistics")
    stats.set_defaults(func=_stats)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
