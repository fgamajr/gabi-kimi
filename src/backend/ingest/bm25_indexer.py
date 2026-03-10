"""BM25 index builder, refresher, and search CLI for DOU documents.

Manages the Okapi BM25 search infrastructure:
  - Applies DDL (bm25_schema.sql)
  - Populates document word counts (body_word_count)
  - Builds / refreshes term statistics (bm25_term_stats, bm25_corpus_stats)
  - Interactive search from the command line

Usage:
  python3 -m src.backend.ingest.bm25_indexer build                        # full build
  python3 -m src.backend.ingest.bm25_indexer refresh                      # incremental refresh
  python3 -m src.backend.ingest.bm25_indexer search "portaria saúde"      # search
  python3 -m src.backend.ingest.bm25_indexer stats                        # index statistics
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

DEFAULT_DSN = (
    f"host={os.getenv('PGHOST', 'localhost')} "
    f"port={os.getenv('PGPORT', '5433')} "
    f"dbname={os.getenv('PGDATABASE', 'gabi')} "
    f"user={os.getenv('PGUSER', 'gabi')} "
    f"password={os.getenv('PGPASSWORD', 'gabi')}"
)


def _connect(dsn: str):
    """Return a psycopg2 connection."""
    import psycopg2

    return psycopg2.connect(dsn)


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Build / Apply DDL
# ---------------------------------------------------------------------------

_DDL_PATH = Path(__file__).resolve().parent.parent / "dbsync" / "bm25_schema.sql"


def apply_ddl(conn) -> None:
    """Apply bm25_schema.sql to the database."""
    _ = _DDL_PATH.read_text(encoding="utf-8")  # ensure file exists
    _log(f"Applying DDL from {_DDL_PATH.name} ...")

    # Split on semicolons and execute each statement separately
    # (some statements like CREATE MATERIALIZED VIEW IF NOT EXISTS need special handling)
    cur = conn.cursor()

    # Check if materialized views already exist (IF NOT EXISTS not supported for matviews pre-PG15)
    cur.execute("""
        SELECT matviewname FROM pg_matviews
        WHERE schemaname = 'dou'
          AND matviewname IN ('bm25_term_stats', 'bm25_corpus_stats')
    """)
    existing_matviews = {row[0] for row in cur.fetchall()}

    # Apply column + index
    _log("  Adding body_word_count column...")
    cur.execute("ALTER TABLE dou.document ADD COLUMN IF NOT EXISTS body_word_count integer")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_document_word_count_null
            ON dou.document(id) WHERE body_word_count IS NULL
    """)
    conn.commit()

    # Create / rebuild materialized views
    if "bm25_term_stats" not in existing_matviews:
        _log("  Creating bm25_term_stats materialized view (this may take several minutes)...")
        cur.execute("""
            CREATE MATERIALIZED VIEW dou.bm25_term_stats AS
            SELECT word     AS lexeme,
                   ndoc     AS doc_freq,
                   nentry   AS total_freq
            FROM ts_stat('SELECT body_tsvector FROM dou.document')
            WITH DATA
        """)
        cur.execute("""
            CREATE UNIQUE INDEX idx_bm25_term_lexeme
                ON dou.bm25_term_stats(lexeme)
        """)
        conn.commit()
        _log("  ✓ bm25_term_stats created")
    else:
        _log("  bm25_term_stats already exists (will refresh later)")

    if "bm25_corpus_stats" not in existing_matviews:
        _log("  Creating bm25_corpus_stats materialized view...")
        cur.execute("""
            CREATE MATERIALIZED VIEW dou.bm25_corpus_stats AS
            SELECT count(*)::bigint                              AS total_docs,
                   coalesce(avg(body_word_count)::float8, 300.0) AS avg_doc_length,
                   now()                                         AS refreshed_at
            FROM dou.document
        """)
        conn.commit()
        _log("  ✓ bm25_corpus_stats created")
    else:
        _log("  bm25_corpus_stats already exists (will refresh later)")

    # Create/replace functions and views (idempotent)
    _log("  Creating BM25 search functions...")
    _create_functions(cur)
    conn.commit()
    _log("  ✓ Functions created")

    cur.close()


def _create_functions(cur) -> None:
    """Create/replace all PL/pgSQL functions and views."""

    # ----- bm25_search (unfiltered) -----
    cur.execute("""
CREATE OR REPLACE FUNCTION dou.bm25_search(
    query_text  text,
    max_results integer DEFAULT 20,
    p_k1        float8  DEFAULT 1.2,
    p_b         float8  DEFAULT 0.75
)
RETURNS TABLE(
    doc_id          uuid,
    score           float8,
    identifica      text,
    ementa          text,
    art_type        text,
    pub_date        date,
    edition_section text,
    snippet         text
)
LANGUAGE plpgsql STABLE AS $fn$
DECLARE
    v_N     bigint;
    v_avgdl float8;
    v_tsq   tsquery;
BEGIN
    SELECT cs.total_docs, cs.avg_doc_length
      INTO v_N, v_avgdl
      FROM dou.bm25_corpus_stats cs;

    IF v_N IS NULL OR v_N = 0 THEN RETURN; END IF;
    IF v_avgdl <= 0 THEN v_avgdl := 300.0; END IF;

    v_tsq := plainto_tsquery('pg_catalog.portuguese', query_text);

    RETURN QUERY
    WITH
    q_lex AS (
        SELECT (t).lexeme
        FROM unnest(to_tsvector('pg_catalog.portuguese', query_text)) t
    ),
    candidates AS (
        SELECT d.id, d.body_tsvector, d.body_word_count
        FROM dou.document d
        WHERE d.body_tsvector @@ v_tsq
    ),
    scored AS (
        SELECT c.id,
               SUM(
                   ln((v_N - COALESCE(ts.doc_freq, 1)::float8 + 0.5)
                      / (COALESCE(ts.doc_freq, 1)::float8 + 0.5) + 1.0)
                   * (COALESCE(array_length(dv.positions, 1), 1)::float8 * (p_k1 + 1.0))
                   / (COALESCE(array_length(dv.positions, 1), 1)::float8
                      + p_k1 * (1.0 - p_b
                                + p_b * COALESCE(c.body_word_count, v_avgdl) / v_avgdl))
               ) AS bm25
        FROM candidates c
        CROSS JOIN LATERAL unnest(c.body_tsvector) AS dv
        INNER JOIN q_lex ql ON ql.lexeme = dv.lexeme
        LEFT  JOIN dou.bm25_term_stats ts ON ts.lexeme = dv.lexeme
        GROUP BY c.id
    ),
    top_n AS (
        SELECT s.id, s.bm25
        FROM scored s
        ORDER BY s.bm25 DESC
        LIMIT max_results
    )
    SELECT tn.id,
           tn.bm25,
           d.identifica,
           d.ementa,
           d.art_type,
           e.publication_date,
           e.section,
           ts_headline('pg_catalog.portuguese', d.body_plain, v_tsq,
                       'MaxWords=60, MinWords=25, StartSel=>>>, StopSel=<<<')
    FROM top_n tn
    JOIN dou.document d ON d.id = tn.id
    JOIN dou.edition e  ON e.id = d.edition_id
    ORDER BY tn.bm25 DESC;
END;
$fn$
    """)

    # ----- bm25_search_filtered -----
    cur.execute("""
CREATE OR REPLACE FUNCTION dou.bm25_search_filtered(
    query_text  text,
    max_results integer DEFAULT 20,
    date_from   date    DEFAULT NULL,
    date_to     date    DEFAULT NULL,
    p_section   text    DEFAULT NULL,
    p_art_type  text    DEFAULT NULL,
    p_k1        float8  DEFAULT 1.2,
    p_b         float8  DEFAULT 0.75
)
RETURNS TABLE(
    doc_id          uuid,
    score           float8,
    identifica      text,
    ementa          text,
    art_type        text,
    pub_date        date,
    edition_section text,
    snippet         text
)
LANGUAGE plpgsql STABLE AS $fn$
DECLARE
    v_N     bigint;
    v_avgdl float8;
    v_tsq   tsquery;
BEGIN
    SELECT cs.total_docs, cs.avg_doc_length
      INTO v_N, v_avgdl
      FROM dou.bm25_corpus_stats cs;

    IF v_N IS NULL OR v_N = 0 THEN RETURN; END IF;
    IF v_avgdl <= 0 THEN v_avgdl := 300.0; END IF;

    v_tsq := plainto_tsquery('pg_catalog.portuguese', query_text);

    RETURN QUERY
    WITH
    q_lex AS (
        SELECT (t).lexeme
        FROM unnest(to_tsvector('pg_catalog.portuguese', query_text)) t
    ),
    candidates AS (
        SELECT d.id, d.body_tsvector, d.body_word_count
        FROM dou.document d
        JOIN dou.edition e ON e.id = d.edition_id
        WHERE d.body_tsvector @@ v_tsq
          AND (date_from IS NULL OR e.publication_date >= date_from)
          AND (date_to   IS NULL OR e.publication_date <= date_to)
          AND (p_section IS NULL OR e.section = p_section)
          AND (p_art_type IS NULL OR d.art_type = p_art_type)
    ),
    scored AS (
        SELECT c.id,
               SUM(
                   ln((v_N - COALESCE(ts.doc_freq, 1)::float8 + 0.5)
                      / (COALESCE(ts.doc_freq, 1)::float8 + 0.5) + 1.0)
                   * (COALESCE(array_length(dv.positions, 1), 1)::float8 * (p_k1 + 1.0))
                   / (COALESCE(array_length(dv.positions, 1), 1)::float8
                      + p_k1 * (1.0 - p_b
                                + p_b * COALESCE(c.body_word_count, v_avgdl) / v_avgdl))
               ) AS bm25
        FROM candidates c
        CROSS JOIN LATERAL unnest(c.body_tsvector) AS dv
        INNER JOIN q_lex ql ON ql.lexeme = dv.lexeme
        LEFT  JOIN dou.bm25_term_stats ts ON ts.lexeme = dv.lexeme
        GROUP BY c.id
    ),
    top_n AS (
        SELECT s.id, s.bm25
        FROM scored s
        ORDER BY s.bm25 DESC
        LIMIT max_results
    )
    SELECT tn.id,
           tn.bm25,
           d.identifica,
           d.ementa,
           d.art_type,
           e.publication_date,
           e.section,
           ts_headline('pg_catalog.portuguese', d.body_plain, v_tsq,
                       'MaxWords=60, MinWords=25, StartSel=>>>, StopSel=<<<')
    FROM top_n tn
    JOIN dou.document d ON d.id = tn.id
    JOIN dou.edition e  ON e.id = d.edition_id
    ORDER BY tn.bm25 DESC;
END;
$fn$
    """)

    # ----- bm25_refresh -----
    cur.execute("""
CREATE OR REPLACE FUNCTION dou.bm25_refresh()
RETURNS TABLE(updated_word_counts bigint, total_terms bigint, total_docs bigint)
LANGUAGE plpgsql AS $fn$
DECLARE
    v_updated bigint;
    v_terms   bigint;
    v_docs    bigint;
BEGIN
    WITH updated AS (
        UPDATE dou.document
        SET body_word_count = cardinality(
            regexp_split_to_array(trim(body_plain), '\\s+')
        )
        WHERE body_word_count IS NULL
          AND body_plain IS NOT NULL
          AND body_plain <> ''
        RETURNING 1
    )
    SELECT count(*) INTO v_updated FROM updated;

    REFRESH MATERIALIZED VIEW CONCURRENTLY dou.bm25_term_stats;
    REFRESH MATERIALIZED VIEW dou.bm25_corpus_stats;

    SELECT count(*) INTO v_terms FROM dou.bm25_term_stats;
    SELECT cs.total_docs INTO v_docs FROM dou.bm25_corpus_stats cs;

    RETURN QUERY SELECT v_updated, v_terms, v_docs;
END;
$fn$
    """)

    # ----- v_bm25_stats view -----
    cur.execute("""
CREATE OR REPLACE VIEW dou.v_bm25_stats AS
SELECT cs.total_docs,
       cs.avg_doc_length,
       cs.refreshed_at,
       (SELECT count(*) FROM dou.bm25_term_stats)        AS vocabulary_size,
       (SELECT sum(total_freq) FROM dou.bm25_term_stats)  AS total_term_freq,
       (SELECT count(*) FROM dou.document
        WHERE body_word_count IS NULL)                     AS docs_missing_word_count
FROM dou.bm25_corpus_stats cs
    """)


# ---------------------------------------------------------------------------
# Word count population (batched for progress reporting)
# ---------------------------------------------------------------------------

_BATCH_SIZE = 10_000


def populate_word_counts(conn, batch_size: int = _BATCH_SIZE) -> int:
    """Populate body_word_count for all documents missing it. Returns count updated."""
    cur = conn.cursor()

    # Count how many need updating
    cur.execute("""
        SELECT count(*) FROM dou.document
        WHERE body_word_count IS NULL AND body_plain IS NOT NULL AND body_plain <> ''
    """)
    total = cur.fetchone()[0]
    if total == 0:
        _log("All documents already have word counts.")
        return 0

    _log(f"Populating word counts for {total:,} documents (batch={batch_size:,})...")
    updated = 0
    t0 = time.time()

    while True:
        cur.execute(f"""
            WITH batch AS (
                SELECT id FROM dou.document
                WHERE body_word_count IS NULL
                  AND body_plain IS NOT NULL
                  AND body_plain <> ''
                LIMIT {batch_size}
                FOR UPDATE SKIP LOCKED
            )
            UPDATE dou.document d
            SET body_word_count = cardinality(
                regexp_split_to_array(trim(d.body_plain), '\\s+')
            )
            FROM batch b
            WHERE d.id = b.id
        """)
        n = cur.rowcount
        if n == 0:
            break
        conn.commit()
        updated += n
        elapsed = time.time() - t0
        rate = updated / elapsed if elapsed > 0 else 0
        _log(f"  {updated:,}/{total:,} ({100 * updated / total:.1f}%) — {rate:.0f} docs/s")

    conn.commit()
    _log(f"✓ Word counts populated: {updated:,} docs in {time.time() - t0:.1f}s")
    return updated


# ---------------------------------------------------------------------------
# Refresh materialized views
# ---------------------------------------------------------------------------


def refresh_matviews(conn) -> dict[str, Any]:
    """Refresh bm25_term_stats and bm25_corpus_stats. Returns stats."""
    cur = conn.cursor()

    _log("Refreshing bm25_term_stats (scanning all tsvectors)...")
    t0 = time.time()
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY dou.bm25_term_stats")
    conn.commit()
    dt_terms = time.time() - t0
    _log(f"  ✓ term_stats refreshed in {dt_terms:.1f}s")

    _log("Refreshing bm25_corpus_stats...")
    t0 = time.time()
    cur.execute("REFRESH MATERIALIZED VIEW dou.bm25_corpus_stats")
    conn.commit()
    dt_corpus = time.time() - t0
    _log(f"  ✓ corpus_stats refreshed in {dt_corpus:.1f}s")

    # Get stats
    cur.execute("SELECT * FROM dou.v_bm25_stats")
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    stats = dict(zip(cols, row)) if row else {}
    cur.close()
    return stats


# ---------------------------------------------------------------------------
# Full build
# ---------------------------------------------------------------------------


def cmd_build(args) -> None:
    """Full build: DDL → word counts → materialized views."""
    conn = _connect(args.dsn)
    t0 = time.time()

    try:
        # Step 1: Apply DDL
        apply_ddl(conn)

        # Step 2: Populate word counts
        populate_word_counts(conn, batch_size=args.batch_size)

        # Step 3: Refresh materialized views
        stats = refresh_matviews(conn)

        elapsed = time.time() - t0
        print()
        print("=" * 60)
        print("BM25 INDEX BUILD COMPLETE")
        print("=" * 60)
        for k, v in stats.items():
            print(f"  {k:30s}: {v}")
        print(f"  {'total_build_time':30s}: {elapsed:.1f}s")
        print("=" * 60)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Refresh (incremental)
# ---------------------------------------------------------------------------


def cmd_refresh(args) -> None:
    """Incremental refresh: update new word counts + refresh matviews."""
    conn = _connect(args.dsn)
    t0 = time.time()

    try:
        n = populate_word_counts(conn, batch_size=args.batch_size)
        stats = refresh_matviews(conn)

        elapsed = time.time() - t0
        print()
        print("=" * 60)
        print("BM25 REFRESH COMPLETE")
        print("=" * 60)
        print(f"  {'new_word_counts':30s}: {n:,}")
        for k, v in stats.items():
            print(f"  {k:30s}: {v}")
        print(f"  {'refresh_time':30s}: {elapsed:.1f}s")
        print("=" * 60)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def cmd_search(args) -> None:
    """Run a BM25 search and display results."""
    conn = _connect(args.dsn)
    cur = conn.cursor()

    query = args.query
    limit = args.limit

    _log(f"BM25 search: '{query}' (top {limit})")
    t0 = time.time()

    try:
        if args.date_from or args.date_to or args.section or args.art_type:
            cur.execute(
                """
                SELECT doc_id, score, identifica, ementa, art_type,
                       pub_date, edition_section, snippet
                FROM dou.bm25_search_filtered(%s, %s, %s, %s, %s, %s)
            """,
                (query, limit, args.date_from, args.date_to, args.section, args.art_type),
            )
        else:
            cur.execute(
                """
                SELECT doc_id, score, identifica, ementa, art_type,
                       pub_date, edition_section, snippet
                FROM dou.bm25_search(%s, %s)
            """,
                (query, limit),
            )

        rows = cur.fetchall()
        elapsed = time.time() - t0

        if not rows:
            print(f"\nNo results for '{query}' ({elapsed:.3f}s)")
            return

        print(f"\n{'=' * 80}")
        print(f"BM25 RESULTS: '{query}'  ({len(rows)} hits, {elapsed:.3f}s)")
        print(f"{'=' * 80}")

        for i, row in enumerate(rows, 1):
            doc_id, score, identifica, ementa, art_type, pub_date, section, snippet = row
            print(f"\n--- #{i}  score={score:.4f}  [{art_type}]  {section}  {pub_date} ---")
            if identifica:
                # Truncate long identifica
                ident = identifica[:120] + "..." if len(identifica) > 120 else identifica
                print(f"  {ident}")
            if ementa:
                em = ementa[:200] + "..." if len(ementa) > 200 else ementa
                print(f"  Ementa: {em}")
            if snippet:
                # Format snippet (replace >>> <<< markers)
                snip = snippet.replace(">>>", "\033[1;33m").replace("<<<", "\033[0m")
                print(f"  ...{snip}...")
            print(f"  ID: {doc_id}")

        print(f"\n{'=' * 80}")

    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def cmd_stats(args) -> None:
    """Show BM25 index statistics."""
    conn = _connect(args.dsn)
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM dou.v_bm25_stats")
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()

        if not row:
            print("No BM25 stats available. Run 'build' first.")
            return

        stats = dict(zip(cols, row))

        print()
        print("=" * 60)
        print("BM25 INDEX STATISTICS")
        print("=" * 60)
        for k, v in stats.items():
            if isinstance(v, float):
                print(f"  {k:30s}: {v:,.1f}")
            elif isinstance(v, int):
                print(f"  {k:30s}: {v:,}")
            else:
                print(f"  {k:30s}: {v}")
        print("=" * 60)

        # Top-20 most frequent terms
        cur.execute("""
            SELECT lexeme, doc_freq, total_freq
            FROM dou.bm25_term_stats
            ORDER BY doc_freq DESC
            LIMIT 20
        """)
        print("\nTop-20 terms by document frequency:")
        print(f"  {'lexeme':30s} {'doc_freq':>12s} {'total_freq':>12s}")
        print(f"  {'-' * 30} {'-' * 12} {'-' * 12}")
        for lex, df, tf in cur.fetchall():
            print(f"  {lex:30s} {df:>12,} {tf:>12,}")

    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="BM25 index builder and search for DOU documents")
    p.add_argument("--dsn", default=DEFAULT_DSN, help="PostgreSQL DSN")

    sub = p.add_subparsers(dest="command", required=True)

    # build
    bp = sub.add_parser("build", help="Full BM25 index build (DDL + word counts + matviews)")
    bp.add_argument(
        "--batch-size", type=int, default=_BATCH_SIZE, help=f"Word count update batch size (default: {_BATCH_SIZE})"
    )
    bp.set_defaults(func=cmd_build)

    # refresh
    rp = sub.add_parser("refresh", help="Incremental refresh (new docs + matview refresh)")
    rp.add_argument(
        "--batch-size", type=int, default=_BATCH_SIZE, help=f"Word count update batch size (default: {_BATCH_SIZE})"
    )
    rp.set_defaults(func=cmd_refresh)

    # search
    sp = sub.add_parser("search", help="Run a BM25 search query")
    sp.add_argument("query", help="Search query text")
    sp.add_argument("-n", "--limit", type=int, default=20, help="Max results (default: 20)")
    sp.add_argument("--date-from", default=None, help="Filter: start date (YYYY-MM-DD)")
    sp.add_argument("--date-to", default=None, help="Filter: end date (YYYY-MM-DD)")
    sp.add_argument("--section", default=None, help="Filter: edition section (do1, do2, do3)")
    sp.add_argument("--art-type", default=None, help="Filter: art type (portaria, decreto...)")
    sp.set_defaults(func=cmd_search)

    # stats
    stp = sub.add_parser("stats", help="Show BM25 index statistics")
    stp.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
