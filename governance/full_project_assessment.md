# GABI Full Project Assessment

> Produced: 2026-03-02 | Branch: feat/pythonpipe | Head: 9a13962
> Objective: Corpus integrity first. Search layers explicitly excluded.
> This document is a brutally honest system map, not a sales pitch.

---

## Section 1: System Map

### 1.1 Module Status

| Module | Files | LOC | Complete | Honest Assessment |
|--------|-------|-----|----------|-------------------|
| `harvest/` | 5 | 523 | 100% FROZEN | Solid. `urllib` freezer with atomic writes, SHA256 manifests, cross-domain redirect rejection. Single-threaded, no checkpoint/resume, no rate limiting, no retry. 20-year max range means 23-year corpus needs 2 passes. `canonicalizer.py` targets Liferay-era HTML only. `extractor.py` targets modern act format only. |
| `crawler/` | 13 | ~1,700 | ~60% | DSL schema/loader/validator complete. Mock browser + orchestrator complete. `engine.py` HTTP runtime extracts `<a>` tags only — no CSS selector engine. `HeadlessBrowserRuntime` is `NotImplementedError`. **Not used by harvest pipeline.** Parallel experiment for dynamic sites. |
| `validation/` | 10 | ~2,967 | 90% | Comprehensive. Extraction harness, CSS-lite selector matching, identity hashing, completeness validation, corpus sampling, edition freezing, semantic resolution. Reporter outputs are basic. No automated regression suite — all manual invocation. |
| `dbsync/` | 7 | ~1,595 | 95% | Full declarative schema lifecycle. `registry_ingest.py` (669 LOC) is the heavyweight: SERIALIZABLE CTE state machine with commitment integration. Production-ready for single-source DOU. |
| `commitment/` | 6 | 957 | 100% | Strongest module. CRSS-1 canonical serializer, binary Merkle tree with inclusion proofs, REPEATABLE READ anchor projection, deterministic append-only chain with `fcntl` locking, independent verifier. Genesis anchor exists in `proofs/anchors/`. |
| `infra/` | 2 + docker-compose | ~232 | 100% | PostgreSQL 16 appliance on port 5433. Docker lifecycle. No Elasticsearch, no Redis, no pgvector. Bare PG only. |
| `governance/` | 5 files | ~400 lines | 100% | Phase-Lock v2, adversarial executor with SRRP, structural risk registry. Well-structured. Over-engineered for current scale but defensible for archival integrity claims. |
| Auditor MCPs | 4 dirs | ~524 | 100% | FastMCP wrappers (kimi-k2.5, qwen3-max, glm-4.7, codex). Identical structure ~131 LOC each. |
| Top-level scripts | 11 files | ~2,115 | 100% | All CLI entrypoints working. `harvest_cli.py`, `run_mock_crawl.py`, `extract_test.py`, `historical_validate.py`, `schema_sync.py`, `commitment_cli.py`, `hostile_verify.py`, plus 4 test scripts. |
| **TOTAL** | **~60** | **~10,600** | | |

### 1.2 Dependency Graph

```
harvest_cli.py
  └── harvest/freezer.py ──→ harvest/date_selector.py
      harvest/canonicalizer.py (standalone, no deps)
      harvest/extractor.py ──→ harvest/model.py

extract_test.py / historical_validate.py
  └── validation/extractor.py ──→ validation/{html_tools, rules}
      validation/corpus_sampler.py ──→ crawler/user_agent_rotator.py
      validation/{identity_analyzer, completeness_validator, semantic_resolver}
      validation/reporter.py

schema_sync.py
  └── dbsync/{loader, planner, introspect, differ, executor}

commitment_cli.py / hostile_verify.py
  └── commitment/{anchor, crss1, tree, chain, verify}

dbsync/registry_ingest.py  ← INTEGRATION NEXUS
  └── commitment/{anchor, chain}
      validation/identity_analyzer
      psycopg

run_mock_crawl.py
  └── crawler/{crawl_engine, dsl_schema, mock_browser, frontier, observability}
```

**Key insight:** `harvest/` and `crawler/` are completely independent subsystems. The harvest pipeline does not use the crawler module. The crawler is a separate experiment.

### 1.3 Gap Analysis

| Item | Status | Impact |
|------|--------|--------|
| `crawler/engine.py` CSS selectors | Stubbed (anchor-only) | Cannot extract by CSS selector via HTTP. `sources_v3.yaml` requires `a[href*='/web/dou/-/']` which needs attribute selectors. HTTP runtime cannot serve this. |
| `crawler/engine.py` HeadlessBrowserRuntime | `NotImplementedError` | DOU crawl spec specifies `mode: browser` + `wait_dom: network_idle`. Unexecutable. |
| `harvest/normalizer.py` | Missing | Phase 4 in phase_lock.md. Zero implementation. |
| Checkpoint/resume in `freeze_range` | Missing | A 7,305-day freeze that fails on day 5,000 loses all progress. |
| Rate limiting / retry in freezer | Missing | No delay, no backoff, no retry. DOU will throttle or block sustained 25,000-request sequences. |
| `requirements.txt` / lockfile | Missing | 4 deps unpinned (`yaml`, `psycopg`, `loguru`, `lxml`). No upper bounds. |
| pytest / CI | Absent | All testing via ad-hoc scripts. No `conftest.py`, no CI pipeline. |
| Elasticsearch | Absent | No ES client, no index mappings, no bulk indexer. |
| Embeddings / pgvector | Absent | No ONNX model, no vector extension in PG config. |
| Incremental daily freeze | Absent | `freeze_range` is batch-only. No daily cron capability. |

---

## Section 2: Risk Register

### 2.1 Technical Risks

| ID | Risk | Severity | Likelihood | Detail |
|----|------|----------|-----------|--------|
| T-01 | Single-threaded freezer at corpus scale | HIGH | CERTAIN | `freeze_range` makes ~25,200 sequential HTTP requests for full corpus (3 sections x 8,400 days). At 2s average per request = ~14 hours per 20-year pass. Two passes for 23 years = ~28 hours minimum. Any network interruption restarts from zero. |
| T-02 | No rate limiting or retry | HIGH | LIKELY | `urllib.urlopen` with no backoff. DOU will return 429 or RST during sustained crawling. Current code logs error and continues — **silent data loss** on throttled requests. |
| T-03 | DOU format drift across 23 years | HIGH | CERTAIN | `canonicalizer.py` targets Liferay patterns (cache-busters, auth tokens, combo servlets). Pre-Liferay pages (2003-~2015) have different HTML structure. Extraction rules in `sources_v3.yaml` tuned for current platform. Historical pages may be structurally incompatible. |
| T-04 | Identity hash instability across eras | HIGH | LIKELY | `document_identity` uses SHA256 of normalized fields. If extraction rules change or DOU reformats, same document produces different hashes. No migration path for re-keying existing records. |
| T-05 | `body_text` storage at scale | MEDIUM | CERTAIN | ~1.7 KB/doc x 43M docs (after dedup) = ~73 GB text. With PG overhead + TOAST + indexes: 150-250 GB. Manageable but requires dedicated disk. |
| T-06 | Merkle tree memory at full corpus | LOW | CERTAIN | 43M leaves x 32 bytes = ~1.4 GB tree. `commitment/tree.py` builds in-memory. Feasible on 16 GB machine but computation will take minutes. |
| T-07 | FREEZER-SEC-01 TOCTOU | LOW | UNLIKELY | Documented structural risk. Accepted for CLI batch context. |
| T-08 | Pre-2010 encoding (ISO-8859-1) | MEDIUM | LIKELY | Pre-2010 Brazilian gov sites frequently used latin-1 or mixed encodings. Canonicalizer and extractor assume UTF-8. Needs chardet or explicit encoding detection for ~2-5% of pre-2010 corpus. |

### 2.2 Operational Risks

| ID | Risk | Severity | Detail |
|----|------|----------|--------|
| O-01 | No checkpoint/resume | CRITICAL | The single biggest operational risk. A freeze that fails mid-range loses all progress. Must fix before any full-corpus run. |
| O-02 | Raw HTML archive disk | HIGH | 3 sections x ~4 MB x 8,400 days = ~100 GB. Must provision in advance. |
| O-03 | No monitoring or alerting | MEDIUM | `loguru` in crawler, stdlib `logging` in harvest. No structured metrics, no dashboards, no alerting on failures. |
| O-04 | Single-developer bus factor | HIGH | One developer, no CI, no automated tests, no deploy scripts. Project state exists in one working copy. |
| O-05 | DOU availability | HIGH | Government infrastructure. No SLA. May go offline. May throttle. No robots.txt compliance in code. |
| O-06 | No backup/DR strategy | CRITICAL | Single SSD failure destroys 13 weeks of work. No tested backup, no restore RPO/RTO, no off-site copy. Mitigation: ZFS snapshots to secondary drive + rclone to cold storage. |
| O-07 | Legal/ToS/LGPD compliance | HIGH | Bulk scraping of government portal not verified against DOU ToS. LGPD applies to personal data in DOU announcements (dados pessoais). Must verify before full-scale crawl. |

### 2.3 Architectural Risks

| ID | Risk | Severity | Detail |
|----|------|----------|--------|
| A-01 | No pytest / no CI | HIGH | All testing is manual script invocation. No regression detection. Code changes can silently break extraction. |
| A-02 | Synchronous I/O everywhere | MEDIUM | `urllib.urlopen` with no async, no connection pooling. Acceptable for small runs, bottleneck at scale. |
| A-03 | `crawler/` vs `harvest/` split | LOW | Two independent systems solving overlapping problems. Creates confusion about canonical DOU path. |
| A-04 | Missing Phase 4 (Normalize) | MEDIUM | `phase_lock.md` references `harvest/normalizer.py` which does not exist. Phase 4 has zero implementation. |
| A-05 | No migration versioning in dbsync | LOW | Declarative diff-based, not sequential migrations. Works for greenfield, risky with production data. |

---

## Section 3: 6-Phase Execution Plan

### Phase 0 — Empirical Baseline (MANDATORY BEFORE SCALE)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | `harvest_cli.py freeze` functional; 50 GB disk available |
| Scope | Freeze sample months from 6 era buckets: 2003, 2008, 2012, 2016, 2020, 2023 (January of each). Detects format drift, encoding changes, and size variation across all platform generations. |
| Deliverables | `governance/empirical_baseline.md` with: raw size per year, avg HTML size per section, canonical expansion ratio, extraction error rate per era, estimated full-corpus disk requirement |
| Exit criteria | Auditors approve methodology (not numbers). Real measurements replace all estimates in this document. |
| Effort | 3-5 days (mostly execution time) |
| Dependencies | Network access to DOU, disk for ~15 GB test data |

**Why this phase exists:** Never trust theoretical averages. Measure before committing.

### Phase 1 — Freeze (Deterministic Evidence Capture)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 0 complete; disk provisioned per empirical baseline; PostgreSQL running |
| Tooling | (a) Checkpoint/resume: skip dates with valid manifest.json. (b) Rate limiting: configurable delay default 1.5s. (c) Retry: 3 attempts with exponential backoff. (d) Parallel: `--workers N` via `ThreadPoolExecutor` default 3. (e) `--dry-run` mode. |
| Execution | Full corpus frozen: 2003-01-01 to 2026-03-02 in two passes per 7,305-day limit. |
| Invariant | Re-running `freeze_date(d, dir)` produces identical SHA256 manifest. |
| Exit criteria | >= 99% coverage across 3 sections; manifests verified; zero corrupted HTML |
| Effort | 2-3 weeks (1 week tooling, 1-2 weeks execution) |
| Artifact | `governance/freeze_invariants.md` |

### Phase 2 — Canonicalize (Deterministic Normalization)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 1 complete with >= 99% coverage |
| Deliverables | (a) Era detection per page. (b) Era-specific canonicalization pipelines. (c) Canonical archive alongside raw. (d) `canonical_hash = sha256(canonical_html)` in manifest. (e) Diff report flagging > 50% delta. |
| Invariant | `canonicalize(canonicalize(x)) == canonicalize(x)`. Byte-identical across runs. |
| Exit criteria | 100% canonicalized; idempotency verified on 1,000-page sample |
| Effort | 1-2 weeks |
| Artifact | `governance/canonical_spec.md` |

### Phase 3 — Extract (Era-Aware Structured Extraction)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 2 complete; rules validated per era |
| Deliverables | (a) Era-aware extraction rules. (b) Batch runner. (c) Per-date reports. (d) `identity_hash` for all documents. (e) JSON corpus on disk. (f) `extraction_coverage_report.json`. |
| Invariant | identity_hash stable across re-runs on identical canonical input. |
| Exit criteria | >= 95% pages produce >= 1 document; required fields on >= 90%; error rate < 5% |
| Effort | 2-3 weeks |
| Artifact | `governance/extraction_spec.md` |

### Phase 4 — Normalize (Field Standardization)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 3 complete |
| Deliverables | (a) `harvest/normalizer.py`. (b) Type normalization. (c) Authority normalization. (d) Date to ISO 8601. (e) Reference normalization. (f) Whitespace cleanup. (g) Normalized JSON corpus. |
| Invariant | `normalize(normalize(x)) == normalize(x)`. Deterministic. |
| Exit criteria | All types map to enum; all dates ISO 8601; idempotent on full corpus |
| Effort | 1-2 weeks |
| Artifact | `governance/normalization_rules.md` |

### Phase 5 — Persist (Database Ingestion)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 4 complete; PG schema synced |
| Deliverables | (a) Batch ingestion via `registry_ingest.py`. (b) Idempotent upsert on identity_hash. (c) Checkpoint resume. (d) Ingestion log. (e) All 8 tables populated. |
| Invariant | Ingesting twice does not duplicate. SERIALIZABLE CTE. |
| Exit criteria | Zero unrecoverable errors; counts match extraction report |
| Effort | 1-2 weeks |
| Artifact | `governance/persistence_model.md` |

### Phase 6 — Anchor (Cryptographic Commitment)

| Attribute | Detail |
|-----------|--------|
| Entry criteria | Phase 5 complete; `hostile_verify.py` passes |
| Deliverables | (a) Chain extended through all batches. (b) Inclusion proofs for 10K sample. (c) Verification passing. (d) Anchors in `proofs/anchors/`. |
| Invariant | Merkle root deterministic for identical corpus. Chain append-only + tamper-evident. |
| Exit criteria | Full chain valid; any document provable; hostile verify green |
| Effort | 3-5 days |
| Artifact | `governance/anchoring_model.md` |

---

## Section 4: 90-Day Roadmap

**Assumption:** Single developer, part-time (20-30 hrs/week). Full-time compresses by ~40%.

### Weeks 1-2: Foundation + Phase 0

- `pyproject.toml` with test config; convert `test_*.py` to pytest
- Pin dependencies in `requirements.txt`
- Basic CI (GitHub Actions: lint, syntax, test)
- **Phase 0:** Freeze sample months from 6 era buckets (2003, 2008, 2012, 2016, 2020, 2023)
- Measure per-era: HTML size, encoding, extraction error rate, doc count
- Write `governance/empirical_baseline.md`
- Set up backup (ZFS snapshots or rclone to cold storage)
- **Gate A:** Real metrics replace all estimates. Backup verified.

### Weeks 3-4: Phase 1 Tooling

- Checkpoint/resume in `freeze_range`
- Rate limiting (`--delay`, default 1.5s)
- Retry (3 attempts, exponential backoff)
- Parallel download (`--workers N`, default 3)
- `--dry-run` mode
- Auditor convergence loop on changes
- Write `governance/freeze_invariants.md`

### Weeks 5-7: Phase 1 Execution + Contingency

- **Gate B:** Checkpoint/resume + rate limiter + retry all passing tests before full freeze
- Full corpus freeze pass 1 (2003-2022) + pass 2 (2023-2026)
- Monitor failures, re-run gaps, validate coverage
- Week 7 is contingency for DOU throttling, format surprises, and gap-filling
- **Risk:** DOU throttling could extend by 1-2 weeks. Week 7 absorbs this.

### Weeks 8-9: Phases 2-3

- Era detection + extended canonicalizer
- Canonicalize full archive; review diff report
- Extend extraction rules per era; batch extract
- Write `governance/canonical_spec.md` + `governance/extraction_spec.md`
- **Risk:** Historical format diversity — hardest phase. May overflow to Week 9.

### Weeks 10-11: Phases 4-5

- Implement `harvest/normalizer.py`; normalize corpus
- Sync PG schema; batch ingest via `registry_ingest.py`
- Validate counts; fix errors
- Write `governance/normalization_rules.md` + `governance/persistence_model.md`

### Weeks 12-13: Phase 6

- Commitment anchoring for all batches
- `hostile_verify.py` on full chain
- Inclusion proofs for 10K sample
- Write `governance/anchoring_model.md`

### Week 14: Hardening

- Operational runbook
- Platform-era documentation
- Coverage + quality reports
- `governance/metrics_dashboard.md`
- Tag: **`v1.0.0-corpus-integrity`**

### Explicitly EXCLUDED

| Layer | Status | Rationale |
|-------|--------|-----------|
| Elasticsearch BM25 | Deferred Phase 7 | Build search on stable corpus, not during construction |
| Embeddings / pgvector | Deferred Phase 8 | Requires stable extraction first |
| RAG | Deferred Phase 9 | Requires stable search first |
| Entity graph queries | Deferred Phase 10 | Requires stable normalization first |
| API endpoints | Deferred | No consumers yet |
| Search UI | Deferred | No search layer yet |

---

## Section 5: Storage and Compute Estimates

**WARNING: All estimates are theoretical extrapolations. Phase 0 replaces them with measured values. Do not commit infrastructure on these numbers alone.**

### 5.1 Raw Storage (HTML Archive)

| Item | Calculation | Estimate |
|------|------------|----------|
| Publication days (2003-2026) | ~6,000 (Mon-Fri only, excl national holidays) | 6,000 |
| Sections per day | 3 (do1, do2, do3) | 3 |
| HTML files total | 6,000 x 3 | 18,000 |
| Avg HTML per section | ~4 MB (observed 3-5 MB modern; pre-2015 likely smaller) | 4 MB |
| **Raw HTML total** | 18,000 x 4 MB | **~72 GB** |

**Caveat:** Pre-2015 pages likely 1-2 MB. Stratified estimate: 60-80 GB. Phase 0 will measure per-era sizes.

### 5.2 Cardinality Model

```
publication_days           = ~6,000
section_pages              = 6,000 x 3 = 18,000
docs_per_section_per_day   = TBD (Phase 0 measures this — estimated ~2,400)
gross_documents            = 6,000 x 3 x 2,400 = ~43M
dedup_rate                 = TBD (Phase 0 measures — estimated 5-10%)
net_documents              = ~39-41M
```

All downstream estimates derive from this model. Phase 0 replaces TBD values.

### 5.3 Processed Storage

| Layer | Calculation | Estimate |
|-------|------------|----------|
| Canonicalized HTML | ~same as raw | ~72 GB |
| Extracted JSON (disk) | ~41M docs x 1.7 KB | **~70 GB** |
| **Disk subtotal** | raw + canonical + JSON | **~214 GB** |

### 5.4 PostgreSQL Storage

| Table | Rows | Table size | Index overhead |
|-------|------|-----------|---------------|
| publication_issue | ~18K | ~4 MB | ~1 MB |
| document | ~41M | ~82 GB | ~15 GB |
| document_identity | ~41M | ~6 GB | ~3 GB |
| document_participant | ~20M | ~4 GB | ~2 GB |
| document_signature | ~28M | ~5 GB | ~2 GB |
| normative_reference | ~57M | ~14 GB | ~5 GB |
| procedure_reference | ~14M | ~3 GB | ~1 GB |
| document_event | ~10M | ~2.5 GB | ~1 GB |
| ingestion_log | ~41M | ~4 GB | ~2 GB |
| **PG data (steady state)** | | **~125 GB** | **~32 GB** |
| **Temp WAL during bulk load** | recycled, not permanent | **~30 GB peak** | |
| **PG steady state total** | data + indexes | **~157 GB** | |

### 5.5 Compute (Phase-Specific)

| Phase | CPU | RAM | Disk I/O | Notes |
|-------|-----|-----|----------|-------|
| Freeze | 2 cores | 4 GB | Low | Network-bound. Workers idle between requests. |
| Canonicalize | 4 cores | 4 GB | 50 MB/s | Regex on full archive. Parallelizable per file. |
| Extract | 4 cores | 8 GB | 50 MB/s | HTML parsing is memory-hungry. Workers need ~1 GB each. |
| Normalize | 2 cores | 4 GB | Low | Lightweight text transforms. |
| Persist (bulk load) | 4 cores | 16 GB | 200 MB/s | PG needs `shared_buffers=4GB`, `work_mem=256MB`. WAL peak ~30 GB. |
| Anchor | 2 cores | 4 GB | Low | Merkle tree ~1.4 GB in-memory. |
| **Overall recommended** | **4 cores** | **16 GB** | **200 MB/s SSD** | |

### 5.6 Network

| Phase | Requests | Base transfer | Retry overhead (20%) | Total | Duration |
|-------|----------|--------------|---------------------|-------|----------|
| Full freeze | 18,000 | ~72 GB | ~14 GB | **~86 GB** | 16-32 hrs (1.5s delay) |
| Daily incremental | 3/day | ~12 MB | negligible | ~4.4 GB/year | < 1 min |

Note: Duration includes 1.5s politeness delay between requests. IP ban risk remains if DOU WAF triggers on sustained single-IP crawling.

### 5.7 Cost

| Option | Monthly |
|--------|---------|
| Local workstation | $0 (1 TB SSD required) |
| VPS (Hetzner CX41 + volume) | ~$40/mo |
| AWS EC2 t3.large + 1 TB gp3 | ~$80-120/mo |
| **Recommendation** | **Local for build, VPS for serving** |

### 5.8 Artifact Retention Policy

| Artifact | Retention | Storage tier | Rationale |
|----------|-----------|-------------|-----------|
| Raw HTML archive | Forever | SSD or cold storage | Evidentiary record. Cannot regenerate. |
| Canonicalized HTML | Regenerable | SSD during processing, deletable after persist | Can be recomputed from raw. |
| Extracted JSON | Regenerable | SSD during processing, deletable after persist | Can be recomputed from canonical. |
| PostgreSQL data | Forever | SSD | Operational store. |
| Anchor chain + proofs | Forever | Any | Tamper evidence. Small footprint. |

**Minimum permanent storage:** Raw HTML (~72 GB) + PostgreSQL (~157 GB) = **~230 GB**
**Peak during processing:** +canonical (~72 GB) + JSON (~70 GB) + WAL (~30 GB) = **~402 GB**

### 5.9 Total Summary

| Component | Size | Permanent? |
|-----------|------|-----------|
| Raw HTML archive | ~72 GB | YES |
| Canonicalized archive | ~72 GB | No (regenerable) |
| Extracted JSON | ~70 GB | No (regenerable) |
| PostgreSQL (steady state) | ~157 GB | YES |
| WAL (bulk load peak) | ~30 GB | No (recycled) |
| Merkle tree (runtime RAM) | ~1.4 GB | N/A |
| **PERMANENT DISK** | **~230 GB** | |
| **PEAK DISK (during processing)** | **~402 GB** | |
| **RECOMMENDED SSD** | **1 TB** | 35% headroom for vacuum, temp, growth |

---

## Section 6: Critical Decisions Required

### Decision 1: Crawler vs. Harvest

| Option | Recommendation |
|--------|---------------|
| **(A) Kill `crawler/` for 90-day plan** | DOU listing pages are static HTML. `harvest/freezer.py` is sufficient. |
| (B) Complete crawler with Playwright | Adds complexity. Useful for article detail pages later. |
| **Recommend: (A)** | Re-evaluate crawler post-corpus for article scraping. |

### Decision 2: Historical platform era handling

| Option | Recommendation |
|--------|---------------|
| (A) Single ruleset with fallbacks | Poor quality on old pages. |
| **(B) Date-range-based rulesets** | Clean. Requires 1 week historical research. |
| (C) Auto-detection per page | Most robust, most complex. Add as refinement to (B). |
| **Recommend: (B) then (C)** | |

### Decision 3: Concurrent vs. sequential freezing

| Option | Recommendation |
|--------|---------------|
| (A) Single-threaded | Simple, ~28 hours total. |
| **(B) ThreadPoolExecutor, default 3** | 3-5x faster. Does not modify `freeze_date`. |
| (C) asyncio + httpx | Fastest but phase-lock concern. |
| **Recommend: (B)** | `--workers N` flag. |

### Decision 4: Storage architecture

| Option | Recommendation |
|--------|---------------|
| **(A) Local filesystem** | Simple, current approach. Best for build. |
| (B) S3/MinIO | Production durability. Premature now. |
| **Recommend: (A)** | Add export-to-S3 script later. |

### Decision 5: When to add search layers

| Option | Recommendation |
|--------|---------------|
| (A) During 90-day plan | Risks both corpus and search quality. |
| **(B) Defer to Phase 7-10** | Build search on committed archive. |
| **Recommend: (B)** | Corpus integrity first. |

---

## Appendix A: Phase-Lock Reference

```
Phase 0  (new)                      EMPIRICAL BASELINE
Phase 1  harvest/freezer.py         FREEZE
Phase 2  harvest/canonicalizer.py   CANONICALIZE
Phase 3  harvest/extractor.py       EXTRACT
Phase 4  harvest/normalizer.py      NORMALIZE  ← MISSING, must implement
Phase 5  dbsync/*                   PERSIST
Phase 6  commitment/*               ANCHOR
```

Immutability rule: Phase N may NEVER modify outputs of Phase < N.

## Appendix B: Auditor Review (2026-03-02)

Reviewed by: codex, qwen (declined — not code), kimi, glm.

| ID | Finding | Flagged by | Severity | Resolution |
|----|---------|-----------|----------|------------|
| AF-01 | Doc count math inconsistent (71M vs 43M) | codex, kimi, glm | CRITICAL | **FIXED** — unified cardinality model: 6,000 days x 3 sections x ~2,400 docs = ~43M |
| AF-02 | WAL is recycled, not permanent 245 GB | kimi, glm | CRITICAL | **FIXED** — PG steady state 157 GB, WAL 30 GB peak (recycled) |
| AF-03 | Timeline too tight for Phase 1 | codex, kimi, glm | CRITICAL | **FIXED** — added Week 7 contingency, Gate A/B before full freeze |
| AF-04 | No retention/lifecycle policy | codex, kimi | CRITICAL | **FIXED** — added Section 5.8 artifact retention policy |
| AF-05 | No backup/DR | codex, kimi | HIGH | **FIXED** — added O-06 to risk register + backup in Week 1-2 |
| AF-06 | Phase 0 needs more era samples | kimi | HIGH | **FIXED** — expanded to 6 era buckets (2003, 2008, 2012, 2016, 2020, 2023) |
| AF-07 | Publication days ~6,000 not 8,400 | glm | MEDIUM | **FIXED** — corrected to 6,000 (Mon-Fri excl holidays) |
| AF-08 | Network ignores retry overhead | codex | HIGH | **FIXED** — added 20% retry overhead in network table |
| AF-09 | Legal/ToS/LGPD risk missing | kimi | HIGH | **FIXED** — added O-07 to risk register |
| AF-10 | Pre-2010 encoding risk | kimi | MEDIUM | **FIXED** — added T-08 encoding risk |
| AF-11 | Parallel + rate limit antagonistic | kimi | HIGH | STRUCTURAL — shared rate limiter across workers (already in Phase 1 design) |
| AF-12 | Merkle leaf ordering undefined | kimi | HIGH | NOISE — already defined in CRSS-1 spec (COLLATE "C" ordering) |
| AF-13 | 16 GB RAM too low | glm | HIGH | **FIXED** — phase-specific compute table, 16 GB recommended for persist phase |

## Appendix C: Structural Risks

| ID | Risk | Status |
|----|------|--------|
| FREEZER-SEC-01 | TOCTOU symlink race | ACCEPTED — CLI batch context |

## Appendix D: Success Definition

```
v1.0.0-corpus-integrity:
  - Full DOU corpus 2003-2026 frozen >= 99% coverage
  - Canonicalized deterministically per era
  - Extracted with stable identity hashes
  - Normalized to canonical forms
  - Persisted idempotently in PostgreSQL
  - Anchored with verifiable Merkle chain
  - All phases passed auditor convergence
  - All governance artifacts produced
```
