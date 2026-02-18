Implementation Plan
in 2 minutes

Review
Unified Fix Plan — Merging HANDOVER.md + HANDOVER_opus.md
Context
Two independent assessments of the GABI project exist:

Document	Origin	Approach
HANDOVER.md
Prior AI session	Focused on recent Docker fix, Zero Kelvin results, skills ecosystem
HANDOVER_opus.md
Current session (code inspection)	Line-by-line source code analysis of all 10 projects
Both identify the same 6 core gaps but differ on specifics. This plan reconciles them into a single ordered fix path.

Reconciliation — Where They Disagree
Topic	HANDOVER.md says	HANDOVER_opus.md says (verified by code)	Truth
Hangfire Dashboard	"Not exposed"	Exposed at /hangfire with HangfireDashboardAuthFilter	Exposed, just not well-documented
Serilog	"Missing everywhere"	Present in Gabi.Api (UseSerilog() + CompactJsonFormatter)	API has Serilog, Worker does not
Hangfire storage	"Redis-backed"	PostgreSQL via Hangfire.PostgreSql	PostgreSQL (Redis is in compose but not used by Hangfire)
Unit tests	"Zero tests, empty projects"	6 test projects with files (7+10+7+8+8+2 files)	Tests exist (content quality unknown)
Retry logic	"Default Hangfire 10 retries"	AutomaticRetry(Attempts=3) + Polly in discovery	3 Hangfire retries × Polly retries
Redis port	Not mentioned	Port 6380 on host (6379 inside Docker)	6380 externally
Fetch executor	"Not implemented"	Exists as stub — marks status, no download	Stub exists
Links endpoint	"Returns HTTP 500"	Implemented in API (GetLinksAsync)	May work now (post-fixes)
Unified Fix Path — 6 Sprints
Sprint 1: Foundation Fixes (Day 1) — 🔴 Blockers
Fix the things that make debugging everything else harder.

#	Task	Source	Effort	Files
1.1	Add Serilog to Worker	Both docs agree Worker has no structured logging. API already has it — copy the pattern.	1h	
src/Gabi.Worker/Program.cs
, 
Gabi.Worker.csproj
1.2	Consolidate retry strategy	opus finding: Hangfire 3 retries × Polly 3 retries = 12 attempts. Pick one.	1h	
GabiJobRunner.cs
, 
SourceDiscoveryJobExecutor.cs
1.3	Fix 0-links silent success	Both: web_crawl/api_pagination return 0 links, logged as success. Add warning log + flag.	1h	
SourceDiscoveryJobExecutor.cs
1.4	Validate all sources	HANDOVER.md Priority 1. Run discovery for all 13 sources, record actual counts.	2h	
zero-kelvin-test.sh
Verification: Run dotnet build → run Zero Kelvin → check Worker logs show Serilog JSON output. Verify tcu_acordaos produces 35 links.

Sprint 2: Dead Letter Queue + Error Handling (Day 2) — 🔴 Critical
Without this, failed jobs vanish silently.

#	Task	Source	Effort	Files
2.1	Create DlqEntry entity	Both docs agree DLQ is missing. HANDOVER.md has schema proposal.	2h	Gabi.Postgres/Entities/, migration
2.2	Hangfire failure filter	Move exhausted jobs to DLQ table instead of Hangfire "Failed" state	2h	Gabi.Worker/Jobs/, new DlqFilter.cs
2.3	DLQ API endpoints	GET /api/v1/dashboard/dlq (list), POST .../dlq/{id}/replay (retry)	2h	
Gabi.Api/Program.cs
Verification: Force a job to fail 3 times → verify it appears in DLQ table → replay via API → verify job re-executes.

Sprint 3: Real Fetch (Day 3-4) — 🔴 Core Pipeline
This is the biggest gap: discovered links go nowhere.

#	Task	Source	Effort	Files
3.1	HTTP streaming client	Both docs. HANDOVER.md has 300MB memory constraint note. Use HttpCompletionOption.ResponseHeadersRead.	4h	Gabi.Fetch/ or Gabi.Ingest/Fetcher/
3.2	ETag + Last-Modified	opus: change detection headers for skip-if-unchanged	2h	Same module
3.3	Wire into FetchJobExecutor	Replace stub with real download → store content in disk/DB	3h	
FetchJobExecutor.cs
3.4	Rate limiting per source	HANDOVER.md mentions robots.txt respect. Use Polly rate limiter.	2h	Fetch module config
Verification: Trigger fetch for tcu_sumulas (1 CSV, ~1MB) → verify file downloaded → verify DocumentEntity has real content. Then tcu_normas (587MB) to test streaming.

Sprint 4: Real Ingest (Day 5-6) — 🔴 Core Pipeline
Transform raw CSVs into searchable documents.

#	Task	Source	Effort	Files
4.1	CSV parser	opus: 
sources_v2.yaml
 has parse.fields config (column mappings) not wired	4h	Gabi.Ingest/Parser/
4.2	Content normalizer	opus: YAML defines transforms (strip_quotes, strip_html) — implement them	3h	Gabi.Ingest/
4.3	SHA-256 hasher + dedup	Both docs. Contracts ContentHasher / DeduplicationService exist but no implementation	3h	Gabi.Fetch/ or new Gabi.Hash/
4.4	Wire into IngestJobExecutor	Replace stub with real parsing → hashing → document creation	3h	
IngestJobExecutor.cs
4.5	Elasticsearch indexing	ES container exists but zero indexing code	4h	Gabi.Ingest/
Verification: Run full pipeline for tcu_sumulas → verify documents in documents table have real Content → verify ES index has matching docs. Verify second run detects duplicates via SHA-256.

Sprint 5: CI/CD + Testing (Day 7) — 🟡 Important
Both docs agree: zero CI/CD.

#	Task	Source	Effort	Files
5.1	GitHub Actions CI	Both docs. Build + test + Zero Kelvin on PR.	3h	.github/workflows/ci.yml
5.2	Deploy workflow	HANDOVER.md has staging/prod proposal. Fly.io files exist.	3h	.github/workflows/deploy.yml
5.3	Audit existing tests	opus: 6 test projects with 42+ files exist — verify and expand	4h	tests/
5.4	Expand Zero Kelvin	Both: currently only validates tcu_sumulas. Add all 13 sources.	2h	
zero-kelvin-test.sh
Verification: Push a PR → see GitHub Actions run → see build/test pass. Tag a release → see Fly.io deploy.

Sprint 6: Discovery Strategies + Observability (Day 8-9) — 🟡 Future Sources
Unlock the 3 sources that currently produce 0 links.

#	Task	Source	Effort	Files
6.1	WebCrawlStrategy	Both docs. For tcu_publicacoes + tcu_notas_tecnicas_ti (PDFs)	8h	
Gabi.Discover/DiscoveryEngine.cs
, new strategy class
6.2	ApiPaginationStrategy	Both docs. For camara_leis_ordinarias (REST API)	4h	Same
6.3	Prometheus metrics	opus: OBSERVABILITY.md plan exists, zero implementation	6h	All projects
6.4	OpenTelemetry tracing	Both docs. API → Hangfire → Worker span correlation	6h	All projects
6.5	Grafana dashboard	HANDOVER.md mentions monitoring. Add to docker-compose.	3h	
docker-compose.yml
Verification: Run discovery for tcu_publicacoes → get actual PDF links. Run discovery for camara_leis_ordinarias → get paginated results. Check Prometheus /metrics endpoint. Check Grafana dashboards.

Summary: Fix Priority Order
Day 1:   Sprint 1 — Serilog in Worker, retry consolidation, validate all sources
Day 2:   Sprint 2 — Dead letter queue + error handling
Day 3-4: Sprint 3 — Real fetch (HTTP streaming, ETag, rate limiting)
Day 5-6: Sprint 4 — Real ingest (CSV parsing, hashing, ES indexing)
Day 7:   Sprint 5 — CI/CD + test audit
Day 8-9: Sprint 6 — WebCrawl/ApiPagination strategies + observability stack
IMPORTANT

Sprint 1 first — without Serilog in Worker, debugging Sprints 2-4 will be painful. Sprints 3-4 are the core value — everything else is infra. Without real fetch+ingest, GABI is a URL discovery tool only.

Verification Plan
Sprint	Automated Test	Manual Check
1	dotnet build passes, Zero Kelvin 14/14, Worker logs JSON	Check tcu_acordaos = 35 links in DB
2	Force job failure → check DLQ table entry	Replay via API → job re-executes
3	tcu_sumulas fetch → document has content	tcu_normas (587MB) streams without OOM
4	tcu_sumulas ingest → ES index populated	Second run → 0 new docs (dedup works)
5	GH Actions runs on PR	Tag release → Fly.io deploy
6	tcu_publicacoes discovery → PDF links found	Prometheus /metrics responds    