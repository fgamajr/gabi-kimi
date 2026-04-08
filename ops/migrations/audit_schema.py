from __future__ import annotations

import argparse
import os

import psycopg

from src.backend.core.config import settings


def _pg_url() -> str:
    return os.getenv("POSTGRES_URL", settings.POSTGRES_URL)


DDL = """
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS audit.round (
    round_id TEXT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    seed BIGINT NOT NULL,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    git_sha TEXT,
    triggered_by TEXT
);

CREATE TABLE IF NOT EXISTS audit.population_snapshot (
    snapshot_id BIGSERIAL PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES audit.round(round_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    as_of_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count BIGINT NOT NULL,
    eligibility_sql TEXT NOT NULL,
    seed BIGINT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_audit_population_snapshot_round_source
  ON audit.population_snapshot (round_id, source_type);

CREATE TABLE IF NOT EXISTS audit.benchmark_registry (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT,
    origin_round_id TEXT,
    UNIQUE (source_type, raw_id)
);

CREATE INDEX IF NOT EXISTS ix_audit_benchmark_registry_source
  ON audit.benchmark_registry (source_type, raw_id);

CREATE TABLE IF NOT EXISTS audit.cohort (
    cohort_id BIGSERIAL PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES audit.round(round_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    cohort_type TEXT NOT NULL CHECK (cohort_type IN ('benchmark', 'rotating', 'canary')),
    snapshot_id BIGINT REFERENCES audit.population_snapshot(snapshot_id) ON DELETE CASCADE,
    selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    selection_seed BIGINT NOT NULL,
    UNIQUE (round_id, source_type, raw_id, cohort_type)
);

CREATE INDEX IF NOT EXISTS ix_audit_cohort_round_source
  ON audit.cohort (round_id, source_type, cohort_type);

CREATE TABLE IF NOT EXISTS audit.process_cache (
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    h2_version TEXT NOT NULL,
    h3_version TEXT NOT NULL,
    h3_prompt_version TEXT NOT NULL,
    h1_status TEXT,
    h2_status TEXT,
    h3_status TEXT,
    materialized_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_type, raw_id, content_hash, parser_version, h2_version, h3_version, h3_prompt_version)
);

CREATE INDEX IF NOT EXISTS ix_audit_process_cache_source_raw
  ON audit.process_cache (source_type, raw_id, materialized_at DESC);

CREATE TABLE IF NOT EXISTS audit.approval_cache (
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    h2_version TEXT NOT NULL,
    h3_version TEXT NOT NULL,
    h3_prompt_version TEXT NOT NULL,
    judge_version TEXT NOT NULL,
    final_verdict TEXT NOT NULL CHECK (final_verdict IN ('approved', 'rejected', 'needs_review')),
    approved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by TEXT,
    origin_round_id TEXT,
    notes TEXT,
    PRIMARY KEY (
        source_type, raw_id, content_hash, parser_version,
        h2_version, h3_version, h3_prompt_version, judge_version
    )
);

CREATE INDEX IF NOT EXISTS ix_audit_approval_cache_source_raw
  ON audit.approval_cache (source_type, raw_id, approved_at DESC);

CREATE TABLE IF NOT EXISTS audit.expert_opinion_cache (
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    h2_version TEXT NOT NULL,
    h3_version TEXT NOT NULL,
    h3_prompt_version TEXT NOT NULL,
    judge_contract_version TEXT NOT NULL,
    expert_model_id TEXT NOT NULL,
    final_verdict TEXT NOT NULL CHECK (final_verdict IN ('approved', 'rejected', 'needs_review')),
    confidence DOUBLE PRECISION,
    dimensions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    issues_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale TEXT,
    raw_response_json JSONB,
    responded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        source_type, raw_id, content_hash, parser_version,
        h2_version, h3_version, h3_prompt_version,
        judge_contract_version, expert_model_id
    )
);

CREATE INDEX IF NOT EXISTS ix_audit_expert_opinion_cache_source_raw
  ON audit.expert_opinion_cache (source_type, raw_id, responded_at DESC);

CREATE TABLE IF NOT EXISTS audit.judge_status (
    round_id TEXT NOT NULL REFERENCES audit.round(round_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    judge_contract_version TEXT NOT NULL,
    judge_mode TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending_judge', 'judged', 'judge_failed_retryable', 'judge_failed_terminal')),
    attempts INTEGER NOT NULL DEFAULT 0,
    final_verdict TEXT,
    quorum_ok BOOLEAN NOT NULL DEFAULT FALSE,
    experts_used INTEGER NOT NULL DEFAULT 0,
    jurors_used INTEGER NOT NULL DEFAULT 0,
    panel_models JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_error TEXT,
    last_summary_json JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (round_id, source_type, raw_id)
);

CREATE INDEX IF NOT EXISTS ix_audit_judge_status_round_source
  ON audit.judge_status (round_id, source_type, status);

CREATE TABLE IF NOT EXISTS audit.judge_verdict (
    id BIGSERIAL PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES audit.round(round_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    cohort_type TEXT NOT NULL CHECK (cohort_type IN ('benchmark', 'rotating', 'canary')),
    judge_version TEXT NOT NULL,
    judge_model TEXT NOT NULL,
    judge_prompt_version TEXT NOT NULL,
    judge_method TEXT NOT NULL DEFAULT 'single_model',
    role TEXT NOT NULL DEFAULT 'judge' CHECK (role IN ('expert', 'jury', 'aggregate')),
    final_verdict TEXT,
    dimension TEXT NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    rationale TEXT,
    confidence DOUBLE PRECISION,
    error TEXT,
    latency_ms DOUBLE PRECISION,
    raw_response_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_judge_verdict_round_source
  ON audit.judge_verdict (round_id, source_type, raw_id);

CREATE TABLE IF NOT EXISTS audit.human_review (
    id BIGSERIAL PRIMARY KEY,
    round_id TEXT NOT NULL REFERENCES audit.round(round_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    raw_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    final_verdict TEXT NOT NULL CHECK (final_verdict IN ('approved', 'rejected', 'needs_review')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS judge_method TEXT NOT NULL DEFAULT 'single_model';
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'judge';
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS final_verdict TEXT;
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS error TEXT;
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS latency_ms DOUBLE PRECISION;
ALTER TABLE audit.judge_verdict
  ADD COLUMN IF NOT EXISTS raw_response_json JSONB;
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Create audit.* schema for H1/H2/H3 round auditing")
    parser.add_argument("--postgres-url", default=_pg_url())
    parser.add_argument("--apply", action="store_true", help="Apply DDL in database")
    args = parser.parse_args()

    if not args.apply:
        print(DDL)
        return

    statements = [stmt.strip() for stmt in DDL.split(";") if stmt.strip()]
    with psycopg.connect(args.postgres_url) as conn:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
    print("audit schema applied")


if __name__ == "__main__":
    main()
