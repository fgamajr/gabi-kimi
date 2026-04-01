from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import typer
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from src.backend.repo_index.config import settings
from src.backend.repo_index.embeddings import OpenAICompatibleEmbeddingProvider
from src.backend.repo_index.ingest.pipeline import RepositoryIndexer
from src.backend.repo_index.repo_semantics import classify_source
from src.backend.repo_index.retrieval.scoring import (
    get_scoring_policy,
    register_scoring_feedback,
)
from src.backend.repo_index.retrieval.service import RetrievalService
from src.backend.repo_index.storage.db import get_connection

app = typer.Typer(no_args_is_help=True)
debug_app = typer.Typer(no_args_is_help=True)


def _load_dotenv() -> dict[str, str]:
    env_path = settings.repo_root / ".env"
    if not env_path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("'").strip('"')
    return env


def _configure_embeddings_from_env() -> None:
    dotenv = _load_dotenv()
    settings.embedding_api_key = (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("EMBED_API_KEY")
        or dotenv.get("OPENAI_API_KEY")
        or dotenv.get("EMBED_API_KEY")
        or ""
    )
    if settings.embedding_api_key:
        settings.embedding_base_url = (
            os.getenv("EMBED_BASE_URL")
            or dotenv.get("EMBED_BASE_URL")
            or settings.embedding_base_url
        )
        settings.embedding_model = (
            os.getenv("EMBED_MODEL")
            or dotenv.get("EMBED_MODEL")
            or settings.embedding_model
        )
        dims_raw = os.getenv("EMBED_DIM") or dotenv.get("EMBED_DIM")
        settings.embedding_dims = (
            int(dims_raw)
            if dims_raw and dims_raw.isdigit()
            else settings.embedding_dims
        )
        verify = (
            os.getenv("EMBED_VERIFY_TLS") or dotenv.get("EMBED_VERIFY_TLS", "true")
        ).lower()
        settings.embedding_verify_tls = verify not in {"0", "false", "no"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_preview(content: str) -> str:
    preview = " ".join(content.strip().split())
    return preview[:240] + ("..." if len(preview) > 240 else "")


@app.command()
def build(
    with_embeddings: bool = typer.Option(
        False, "--with-embeddings", help="Populate embedding cache"
    ),
    embed_batch_size: int = typer.Option(
        16, "--embed-batch-size", help="Embedding API batch size"
    ),
) -> None:
    """Build or refresh the local repo index."""
    _configure_embeddings_from_env()
    indexer = RepositoryIndexer()
    summary = indexer.build(full=True)
    if with_embeddings:
        _populate_embeddings(batch_size=embed_batch_size)
    typer.echo(json.dumps(summary, indent=2))


def _populate_embeddings(batch_size: int) -> None:
    _configure_embeddings_from_env()
    provider = OpenAICompatibleEmbeddingProvider()
    conn = get_connection()
    rows = conn.execute(
        "SELECT chunk_id, text FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.chunk_id = c.chunk_id)"
    ).fetchall()
    if not rows:
        typer.echo("No missing embeddings.")
        conn.close()
        return
    items = list(rows)
    embedded = 0
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        vectors = provider.embed([row["text"] for row in batch])
        for row, vector in zip(batch, vectors):
            conn.execute(
                """
                INSERT OR REPLACE INTO embeddings (chunk_id, provider, model, dims, vector_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["chunk_id"],
                    settings.embedding_provider,
                    settings.embedding_model,
                    settings.embedding_dims or len(vector),
                    json.dumps(vector),
                    _now_iso(),
                ),
            )
            embedded += 1
        conn.commit()
    conn.close()
    typer.echo(f"Embedded {embedded} chunks.")


@app.command()
def query(
    text: str = typer.Argument(..., help="Search query"),
    mode: str = typer.Option(
        "hybrid", "--mode", help="Search mode: lexical, semantic, hybrid"
    ),
    limit: int = typer.Option(8, "--limit", help="Number of results"),
    explain: bool = typer.Option(
        False, "--explain", help="Include trace and scoring details"
    ),
) -> None:
    """Search the repo index."""
    hits, metadata = RetrievalService().search(
        query=text, top_k=limit, mode=mode, explain=explain
    )
    payload = {
        "mode": metadata["mode"],
        "query": text,
        "count": len(hits),
        "results": [
            {
                "path": hit.path,
                "symbol": hit.symbol,
                "start_line": hit.start_line,
                "end_line": hit.end_line,
                "score": hit.score,
                "score_breakdown": hit.score_breakdown if explain else {},
                "reasons": hit.reasons if explain else [],
                "preview": _short_preview(hit.content),
            }
            for hit in hits
        ],
    }
    if explain and metadata.get("trace"):
        payload["trace"] = metadata["trace"]
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def stats() -> None:
    """Show repo index statistics."""
    conn = get_connection()
    file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    embedding_count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    manifest_path = settings.manifests_root / "latest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else {}
    )
    conn.close()
    payload = {
        "db_path": str(settings.db_path),
        "manifest_path": str(manifest_path),
        "file_count": file_count,
        "chunk_count": chunk_count,
        "embedding_cache_count": embedding_count,
        "manifest": manifest,
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


@app.command("feedback-answer")
def feedback_answer(
    text: str = typer.Argument(..., help="Query text"),
    success: bool = typer.Option(
        ..., "--success/--failure", help="Whether the answer was good"
    ),
    query_type: str | None = typer.Option(
        None, "--query-type", help="Override query type"
    ),
    note: str | None = typer.Option(None, "--note", help="Optional note"),
) -> None:
    """Register feedback to adapt scoring profiles."""
    from src.backend.repo_index.retrieval.service import _classify_query

    classification = _classify_query(text, top_k=8)
    profile = register_scoring_feedback(
        query_type=query_type or classification.query_type,
        success=success,
        query=text,
        note=note,
    )
    typer.echo(
        json.dumps(
            {
                "query": text,
                "query_type": profile.query_type,
                "success": success,
                "weights": profile.weights,
                "source": profile.source,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@debug_app.command("list-docs")
def debug_list_docs(limit: int = 20, include_duplicates: bool = False) -> None:
    conn = get_connection()
    stmt = "SELECT * FROM files"
    if not include_duplicates:
        stmt += " WHERE is_duplicate = 0"
    stmt += " ORDER BY source_path LIMIT ?"
    rows = conn.execute(stmt, (limit,)).fetchall()
    conn.close()
    payload = [
        {
            "doc_id": row["doc_id"],
            "source_path": row["source_path"],
            "source_type": row["source_type"],
            "authority_weight": row["authority_weight"],
            "language": row["language"],
            "is_duplicate": bool(row["is_duplicate"]),
            "duplicate_of": row["duplicate_of"],
        }
        for row in rows
    ]
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@debug_app.command("stats")
def debug_stats() -> None:
    source_file_count = len(RepositoryIndexer().discover_paths())
    conn = get_connection()
    indexed_docs = conn.execute(
        "SELECT COUNT(*) FROM files WHERE is_duplicate = 0"
    ).fetchone()[0]
    duplicate_docs = conn.execute(
        "SELECT COUNT(*) FROM files WHERE is_duplicate = 1"
    ).fetchone()[0]
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    by_source = conn.execute(
        "SELECT source_type, COUNT(*) FROM files WHERE is_duplicate = 0 GROUP BY source_type"
    ).fetchall()
    by_section = conn.execute(
        "SELECT section_type, COUNT(*) FROM chunks GROUP BY section_type"
    ).fetchall()
    conn.close()
    payload = {
        "source_files_discovered": source_file_count,
        "indexed_documents": indexed_docs,
        "duplicates_skipped": duplicate_docs,
        "chunk_count": chunk_count,
        "source_type_counts": {key or "unknown": value for key, value in by_source},
        "section_type_counts": {key or "unknown": value for key, value in by_section},
        "latest_manifest": str(settings.manifests_root / "latest.json"),
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@debug_app.command("compare-chunks")
def debug_compare_chunks() -> None:
    manifest_paths = sorted(
        path
        for path in settings.manifests_root.glob("*.json")
        if path.name != "latest.json"
    )
    if len(manifest_paths) < 2:
        typer.echo("Need at least 2 manifests to compare.")
        raise typer.Exit(code=1)
    left = json.loads(manifest_paths[-2].read_text(encoding="utf-8"))
    right = json.loads(manifest_paths[-1].read_text(encoding="utf-8"))
    left_map = {row["source_path"]: row for row in left["documents"]}
    right_map = {row["source_path"]: row for row in right["documents"]}
    changed_paths = []
    for source_path in sorted(set(left_map) | set(right_map)):
        if left_map.get(source_path) != right_map.get(source_path):
            changed_paths.append(source_path)
    payload = {
        "left_manifest": str(manifest_paths[-2]),
        "right_manifest": str(manifest_paths[-1]),
        "identical": len(changed_paths) == 0,
        "left_chunk_count": left["summary"]["chunks"],
        "right_chunk_count": right["summary"]["chunks"],
        "left_document_count": left["summary"]["documents"],
        "right_document_count": right["summary"]["documents"],
        "changed_paths": changed_paths[:25],
        "changed_path_count": len(changed_paths),
    }
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@debug_app.command("scoring-profiles")
def debug_scoring_profiles() -> None:
    typer.echo(
        json.dumps(get_scoring_policy().profiles(), indent=2, ensure_ascii=False)
    )


@debug_app.command("scoring-feedback")
def debug_scoring_feedback(limit: int = 20) -> None:
    typer.echo(
        json.dumps(
            get_scoring_policy().feedback_history(limit=limit),
            indent=2,
            ensure_ascii=False,
        )
    )


class _WatchHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        self.indexer = RepositoryIndexer()

    def _handle(self, src_path: str, deleted: bool = False) -> None:
        path = Path(src_path)
        if classify_source(path) is None:
            return
        if deleted:
            rel = path.relative_to(settings.repo_root).as_posix()
            conn = get_connection()
            existing = conn.execute(
                "SELECT id FROM files WHERE source_path = ?", (rel,)
            ).fetchone()
            if existing:
                file_id = existing["id"]
                conn.execute(
                    "DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE file_id = ?)",
                    (file_id,),
                )
                conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
                conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
                conn.commit()
            conn.close()
            typer.echo(f"Deleted index state for {rel}")
            return
        result = self.indexer.build(full=False, paths=[path])
        typer.echo(
            json.dumps(
                {"path": str(path.relative_to(settings.repo_root)), **result},
                ensure_ascii=False,
            )
        )

    def on_created(self, event) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._handle(event.src_path)

    def on_deleted(self, event) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._handle(event.src_path, deleted=True)


@app.command()
def watch() -> None:
    """Watch repository changes and auto-index."""
    handler = _WatchHandler()
    observer = Observer()
    for dirname in ["src", "ops", "tests", "docs"]:
        target = settings.repo_root / dirname
        if target.exists():
            observer.schedule(handler, str(target), recursive=True)
    observer.start()
    typer.echo("Watching source directories...")
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()


app.add_typer(debug_app, name="debug")


def main() -> None:
    app()
