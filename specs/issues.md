# GABI RAG Rebuild — Issues

<META>
version: 1.0
date: 2026-04-02
source: specs/SPEC.md
format: Each issue has ID, sprint, type, title, description, acceptance criteria, dependencies, and estimated complexity.
Complexity: S (< 2h), M (2-8h), L (8-24h), XL (> 24h)
</META>

---

## Sprint 1 — Raw Archive (MongoDB → Postgres)

<ISSUE id="S1-01" sprint="1" type="infra" complexity="M">
<TITLE>Add Postgres 16 + pgvector to docker-compose.prod.yml</TITLE>
<DESCRIPTION>
Add pgvector/pgvector:pg16 service to production compose file.
Volume: ${GABI_HOST_DATA_ROOT}/postgres_data → /var/lib/postgresql/data.
Network: internal only (not edge). Expose 5432 to internal network.
Env vars: POSTGRES_DB=gabi, POSTGRES_USER, POSTGRES_PASSWORD from .env.
</DESCRIPTION>
<ACCEPTANCE>
- Service starts with `docker compose -f docker-compose.prod.yml up -d postgres`
- pgvector extension available: `CREATE EXTENSION vector` succeeds
- Volume persists across restarts
- Not reachable from edge network
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

<ISSUE id="S1-02" sprint="1" type="infra" complexity="S">
<TITLE>Add Postgres env vars to .env.example and backend config</TITLE>
<DESCRIPTION>
Add POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_URL to .env.example.
Add to src/backend/core/config.py Settings class:
POSTGRES_URL: str = "postgresql://gabi:gabi@postgres:5432/gabi"
Add asyncpg/psycopg dependency to requirements.
</DESCRIPTION>
<ACCEPTANCE>
- Settings class loads POSTGRES_URL from env
- Backend container can import psycopg and connect to postgres
</ACCEPTANCE>
<DEPENDS>S1-01</DEPENDS>
</ISSUE>

<ISSUE id="S1-03" sprint="1" type="backend" complexity="M">
<TITLE>Create raw schema DDL migration</TITLE>
<DESCRIPTION>
SQL migration file creating schema `raw` with tables:
- raw.dou_documents (id TEXT PK, pub_date DATE, section TEXT, source_zip TEXT,
  art_type TEXT, content_html TEXT, raw_html_hash TEXT NOT NULL, all_fields JSONB NOT NULL,
  migrated_at TIMESTAMPTZ DEFAULT now())
- raw.tcu_acordaos (id TEXT PK, tipo TEXT, has_relatorio BOOLEAN, has_voto BOOLEAN,
  data_sessao DATE, colegiado TEXT, raw_text_hash TEXT NOT NULL, all_fields JSONB NOT NULL,
  migrated_at TIMESTAMPTZ DEFAULT now())
- raw.migration_log (id SERIAL PK, collection TEXT, count_mongo BIGINT,
  count_postgres BIGINT, hash_errors INT DEFAULT 0, duration_s FLOAT, ran_at TIMESTAMPTZ)

Indexes: pub_date, art_type, raw_html_hash for DOU; tipo, data_sessao for TCU.
</DESCRIPTION>
<ACCEPTANCE>
- Migration runs idempotently (IF NOT EXISTS)
- All tables created with correct types
- Indexes exist and are used by EXPLAIN
</ACCEPTANCE>
<DEPENDS>S1-01</DEPENDS>
</ISSUE>

<ISSUE id="S1-04" sprint="1" type="backend" complexity="L">
<TITLE>ETL script: MongoDB DOU → raw.dou_documents</TITLE>
<DESCRIPTION>
Script ops/etl_mongo_to_postgres.py that:
1. Cursor-iterates MongoDB `documents` collection in batches of 1000
2. For each doc: compute raw_html_hash = SHA256(NFC(strip(html_unescape(content_html))))
   per dev-converge decision DC2
3. INSERT into raw.dou_documents with ON CONFLICT DO NOTHING (idempotent)
4. Store ALL fields in all_fields JSONB verbatim (json_util serialization for dates/ObjectIds)
5. Log progress every 10K docs
6. Write migration_log entry on completion

Canonicalization for hash (per DC1):
- unicodedata.normalize('NFC', text)
- html.unescape()
- strip whitespace
- DO NOT use the existing content_hash field (it's a different transformation)
</DESCRIPTION>
<ACCEPTANCE>
- Runs against production MongoDB (~16M docs)
- Idempotent: re-running does not duplicate
- raw_html_hash is deterministic and reproducible
- Progress logged every 10K
- migration_log entry written with count and duration
- Memory stable (no OOM on 16M docs)
</ACCEPTANCE>
<DEPENDS>S1-03</DEPENDS>
</ISSUE>

<ISSUE id="S1-05" sprint="1" type="backend" complexity="M">
<TITLE>ETL script: MongoDB TCU → raw.tcu_acordaos</TITLE>
<DESCRIPTION>
Extend ops/etl_mongo_to_postgres.py (or separate function) for `tcu_acordaos` collection:
1. Cursor-iterate in batches of 1000
2. Compute raw_text_hash = SHA256(NFC(strip(acordao_texto)))
3. INSERT into raw.tcu_acordaos with ON CONFLICT DO NOTHING
4. Store all fields in all_fields JSONB
5. Write migration_log entry
</DESCRIPTION>
<ACCEPTANCE>
- Migrates ~520K TCU docs
- Idempotent, memory stable
- Hash deterministic
</ACCEPTANCE>
<DEPENDS>S1-03</DEPENDS>
</ISSUE>

<ISSUE id="S1-06" sprint="1" type="backend" complexity="M">
<TITLE>Stratified validation script</TITLE>
<DESCRIPTION>
Script ops/validate_migration.py that validates raw schema integrity:
1. COUNT(*) parity: compare MongoDB count vs Postgres count per collection
2. Stratified hash check (per DC1):
   - Sample 200 docs per art_type cluster (not random — stratified)
   - Re-compute hash from MongoDB doc, compare with Postgres raw_html_hash
   - Report mismatches with doc IDs
3. Quarantine: INSERT mismatched IDs into raw.migration_quarantine table
4. Output: JSON report with pass/fail per collection + mismatch details
</DESCRIPTION>
<ACCEPTANCE>
- COUNT parity check exact (0 difference)
- Stratified sampling covers all 6 DOU clusters + 2 TCU types
- 0 hash mismatches = PASS
- Quarantine table populated on failures
- JSON report generated
</ACCEPTANCE>
<DEPENDS>S1-04, S1-05</DEPENDS>
</ISSUE>

<ISSUE id="S1-07" sprint="1" type="infra" complexity="S">
<TITLE>Add raw.migration_quarantine table to DDL</TITLE>
<DESCRIPTION>
Per dev-converge decision DC1, add quarantine table:
raw.migration_quarantine (doc_id TEXT PK, collection TEXT, error_type TEXT,
  details TEXT, quarantined_at TIMESTAMPTZ DEFAULT now())
</DESCRIPTION>
<ACCEPTANCE>
- Table exists after migration
- Validation script can insert quarantined docs
</ACCEPTANCE>
<DEPENDS>S1-03</DEPENDS>
</ISSUE>

<ISSUE id="S1-08" sprint="1" type="ops" complexity="S">
<TITLE>MongoDB destruction gate checklist</TITLE>
<DESCRIPTION>
Document the gate as an executable checklist script ops/mongo_destruction_gate.py:
1. Check COUNT parity (query Postgres vs MongoDB)
2. Check validation report (0 hash errors, 0 quarantine entries)
3. Check sync_dou is stopped (no writes in last 1h)
4. Print PASS/FAIL and instructions for next steps:
   - Set MongoDB to read-only
   - Stop MongoDB service
   - Archive volume (keep 30 days)
</DESCRIPTION>
<ACCEPTANCE>
- Script exits 0 on all gates passed, 1 otherwise
- Clear human-readable output
</ACCEPTANCE>
<DEPENDS>S1-06</DEPENDS>
</ISSUE>

---

## Sprint 2 — Source-Dependent Parsers

<ISSUE id="S2-01" sprint="2" type="research" complexity="M">
<TITLE>Inspect tcu_normas, tcu_publicacoes, tcu_btcu collections</TITLE>
<DESCRIPTION>
SSH to production and inspect field structure of three TCU collections:
- tcu_normas: find_one(), count, sample 3 docs
- tcu_publicacoes: find_one(), count, sample 3 docs
- tcu_btcu: find_one(), count, sample 3 docs
Document field names, types, and sample values. Determine if they need
dedicated parsers or can use existing TCU parser patterns.
</DESCRIPTION>
<ACCEPTANCE>
- Field list for each collection documented
- Decision: which collections need parsers, which are skipped
- Update ROADMAP.md with findings
</ACCEPTANCE>
<DEPENDS>S1-04 (Postgres with raw data available)</DEPENDS>
</ISSUE>

<ISSUE id="S2-02" sprint="2" type="research" complexity="M">
<TITLE>Sample real MongoDB DOU documents per cluster for parser validation</TITLE>
<DESCRIPTION>
For each DOU cluster (extrato, normativo, licitacao, resultado, retificacao, outros):
fetch 5 real content_html samples from MongoDB/Postgres.
Manually validate regex patterns proposed in SPEC.md.
Document: which patterns work, which need adjustment, false positive rate.

This is CRITICAL — parser regex was designed from code reading, not from live data.
</DESCRIPTION>
<ACCEPTANCE>
- 5 samples per cluster (30 total) reviewed
- Regex patterns validated or corrected
- False positive/negative estimate per pattern
- Document in specs/PARSER_VALIDATION.md
</ACCEPTANCE>
<DEPENDS>S1-04</DEPENDS>
</ISSUE>

<ISSUE id="S2-03" sprint="2" type="backend" complexity="S">
<TITLE>Parser interface: Protocol + dataclasses</TITLE>
<DESCRIPTION>
Create src/backend/parsers/base.py with:
- Chunk dataclass: text, chunk_type, section_tag, char_start, char_end, order
- ParsedDocument dataclass: source_id, parser_name, parser_version, body_clean,
  chunks (list[Chunk]), section_structure (dict), metadata (dict)
- RawParser Protocol: source (str), version (str), parse(raw_fields: dict) → ParsedDocument

All parsers will implement this interface. Chunk is the unit of embedding.
</DESCRIPTION>
<ACCEPTANCE>
- Importable from src.backend.parsers.base
- Protocol enforced by type checker
- Dataclasses are frozen/slots for immutability
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

<ISSUE id="S2-04" sprint="2" type="backend" complexity="L">
<TITLE>TcuAcordaoCompletoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/tcu_acordao_completo.py:
Parser for TCU complete acórdãos (tipo=="ACÓRDÃO", has_relatorio==True).

Input: raw_fields dict from raw.tcu_acordaos.all_fields
Output: ParsedDocument with body_clean containing:
  <EMENTA>{sumario}</EMENTA>
  <ASSUNTO>{assunto}</ASSUNTO>
  <RELATORIO>{relatorio}</RELATORIO>
  <VOTO>{voto}</VOTO>
  <ACORDAO>{acordao_texto}</ACORDAO>
  <QUORUM>{quorum}</QUORUM>

Each section = one Chunk. Long sections (relatorio >600 tokens) split at
paragraph boundaries into sub-chunks preserving tag context.

Handle null fields gracefully (relação type won't have relatorio/voto).
</DESCRIPTION>
<ACCEPTANCE>
- Parses all ~350K completo acórdãos without error
- Chunks are well-formed (no empty text, correct order)
- Long relatorio split into ≤600-token sub-chunks
- section_structure dict lists available sections
- 100% test coverage on parser logic
</ACCEPTANCE>
<DEPENDS>S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-05" sprint="2" type="backend" complexity="M">
<TITLE>TcuAcordaoRelacaoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/tcu_acordao_relacao.py:
Parser for TCU relação acórdãos (tipo=="ACÓRDÃO DE RELAÇÃO").

Output body_clean:
  <EMENTA>{sumario or assunto}</EMENTA>
  <ACORDAO>{acordao_texto}</ACORDAO>

Simpler than completo — 2 sections, no splitting needed.
</DESCRIPTION>
<ACCEPTANCE>
- Parses all ~170K relação acórdãos
- Gracefully handles null sumario (falls back to assunto)
- Tests cover null field scenarios
</ACCEPTANCE>
<DEPENDS>S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-06" sprint="2" type="backend" complexity="XL">
<TITLE>DouExtratoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dou_extrato.py:
Parser for DOU contract extracts (~4.7M docs).

Input: raw_fields dict → content_html from raw.dou_documents
Must EXTRACT from HTML using regex:
- PARTES: regex for "CONTRATANTE:", "CONTRATADA:", "PARTES:", entity names
- OBJETO: regex for "OBJETO:", capture until next label or double newline
- VALOR: regex for "VALOR:", "R$" + currency patterns (R$ X.XXX,XX)
- VIGENCIA: regex for "VIGÊNCIA:", "PRAZO:", date range patterns
- FUNDAMENTO: regex for "FUNDAMENTO LEGAL:", "Lei nº", statute references

Output body_clean:
  <PARTES>{extracted}</PARTES>
  <OBJETO>{extracted}</OBJETO>
  <VALOR>{extracted}</VALOR>
  <VIGENCIA>{extracted}</VIGENCIA>
  <FUNDAMENTO>{extracted}</FUNDAMENTO>

Sections with failed extraction → omit tag (don't output empty tags).
Log extraction failures for quality monitoring.
</DESCRIPTION>
<ACCEPTANCE>
- Validated against 30 real samples from S2-02
- Extraction rate per field: PARTES >90%, OBJETO >90%, VALOR >85%, VIGENCIA >70%, FUNDAMENTO >80%
- No empty tags in output
- Extraction failure logging
- Tests with real content_html samples
</ACCEPTANCE>
<DEPENDS>S2-02, S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-07" sprint="2" type="backend" complexity="XL">
<TITLE>DouNormativoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dou_normativo.py:
Parser for DOU portarias, resoluções, atos, etc. (~3.9M docs).

Extraction from content_html:
- EMENTA: use existing ementa field, or extract first paragraph after identifica
- CONSIDERANDOS: find "CONSIDERANDO" blocks, collect as ordered list
- ARTIGOS: split at "Art. 1º", "Art. 2º" etc. boundaries

Output body_clean:
  <EMENTA>{text}</EMENTA>
  <CONSIDERANDOS>{text}</CONSIDERANDOS>
  <ARTIGOS>{text}</ARTIGOS>

Challenge: structure varies enormously. Some portarias have CONSIDERANDO,
some don't. Some have numbered articles, some are free-form.
Fallback: if CONSIDERANDOS and ARTIGOS both fail, output <CORPO> with full body.
</DESCRIPTION>
<ACCEPTANCE>
- Validated against real samples
- EMENTA extraction >95% (has field fallback)
- CONSIDERANDOS >60% (only present in some docs)
- ARTIGOS >70% (when articles exist)
- Fallback to <CORPO> works
- Tests cover all fallback scenarios
</ACCEPTANCE>
<DEPENDS>S2-02, S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-08" sprint="2" type="backend" complexity="L">
<TITLE>DouLicitacaoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dou_licitacao.py:
Parser for DOU bidding notices (~2.3M docs).

Extraction from content_html:
- OBJETO: "OBJETO:" label until next section
- MODALIDADE: detect from art_type_normalized or "MODALIDADE:" label
- ORGAO: UASG code + issuing_organ field
- DATAS: "DATA DE ABERTURA:", "ENTREGA DAS PROPOSTAS:" date patterns
- CONDICOES: remaining body after structured extraction

UASG format is highly standardized — expect high extraction rates.
</DESCRIPTION>
<ACCEPTANCE>
- OBJETO extraction >95%
- MODALIDADE >95% (can use art_type field as fallback)
- ORGAO >90% (UASG pattern or issuing_organ)
- DATAS >80%
- Tests with real samples
</ACCEPTANCE>
<DEPENDS>S2-02, S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-09" sprint="2" type="backend" complexity="M">
<TITLE>DouResultadoParser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dou_resultado.py:
Parser for DOU judgment results (~0.7M docs).

Extraction from content_html:
- REFERENCIA: "PREGÃO Nº", "EDITAL Nº", auction/bid identifiers
- VENCEDOR: "VENCEDOR:", "ADJUDICATÁRIO:", company name patterns
- VALOR: "VALOR:", "R$" currency patterns

Less standardized than licitação. Check real samples first.
</DESCRIPTION>
<ACCEPTANCE>
- REFERENCIA extraction >70%
- VENCEDOR >65%
- VALOR >80%
- Fallback to <CORPO> for low-confidence docs
</ACCEPTANCE>
<DEPENDS>S2-02, S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-10" sprint="2" type="backend" complexity="M">
<TITLE>DouGenericoParser (fallback)</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dou_generico.py:
Fallback parser for retificações, avisos, and all unclassified DOU docs (~0.8M).

Output body_clean:
  <EMENTA>{identifica}</EMENTA>
  <CORPO>{cleaned body_plain}</CORPO>

Minimal extraction. identifica always exists. body_plain = strip_html(content_html).
This is the safety net — every DOU doc MUST have a parser.
</DESCRIPTION>
<ACCEPTANCE>
- Handles ANY DOU document without error
- Never outputs empty body_clean
- Tests with edge cases (empty content_html, malformed HTML)
</ACCEPTANCE>
<DEPENDS>S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-11" sprint="2" type="backend" complexity="M">
<TITLE>Parser dispatcher: route documents to correct parser</TITLE>
<DESCRIPTION>
Create src/backend/parsers/dispatcher.py:
Function dispatch_parser(raw_fields: dict) → RawParser that:
1. Reads art_type_normalized from raw_fields
2. Maps to correct parser class based on cluster rules in SPEC.md
3. Returns instantiated parser

Cluster mapping:
- extrato* → DouExtratoParser
- portaria|resolução|ato|despacho|decisão|comunicado → DouNormativoParser
- aviso de licitação*|pregão|edital|concorrência|tomada → DouLicitacaoParser
- resultado*|homologação* → DouResultadoParser
- everything else → DouGenericoParser
- TCU: tipo=="ACÓRDÃO" + has_relatorio → TcuAcordaoCompletoParser
- TCU: tipo=="ACÓRDÃO DE RELAÇÃO" → TcuAcordaoRelacaoParser
</DESCRIPTION>
<ACCEPTANCE>
- Correct dispatch for all art_type_normalized values in ES aggregation
- 100% coverage — no doc type falls through without a parser
- Tests with representative art_type values per cluster
</ACCEPTANCE>
<DEPENDS>S2-04 through S2-10</DEPENDS>
</ISSUE>

<ISSUE id="S2-12" sprint="2" type="backend" complexity="L">
<TITLE>Batch parser runner: raw → parsed schema</TITLE>
<DESCRIPTION>
Script ops/run_parsers.py that:
1. Reads from raw.dou_documents (or raw.tcu_acordaos)
2. Dispatches each to correct parser
3. Writes ParsedDocument to parsed.dou_documents (or parsed.tcu_acordaos)
4. Handles errors: log and skip, don't fail batch
5. Supports --collection (dou|tcu), --batch-size, --limit for testing
6. Only processes docs WHERE parser_version != current (incremental)

Parser versioning: bump version → only re-parse changed docs.
</DESCRIPTION>
<ACCEPTANCE>
- Processes 16M DOU + 520K TCU without OOM
- Idempotent (ON CONFLICT UPDATE parser_version, body_clean, chunks)
- --limit=1000 works for testing
- Error docs logged but don't stop batch
- migration_log entry written
</ACCEPTANCE>
<DEPENDS>S2-11, S1-04, S1-05</DEPENDS>
</ISSUE>

<ISSUE id="S2-13" sprint="2" type="backend" complexity="M">
<TITLE>Create parsed schema DDL</TITLE>
<DESCRIPTION>
SQL migration for schema `parsed`:
- parsed.dou_documents (id TEXT PK REFERENCES raw.dou_documents(id),
  parser_name TEXT, parser_version TEXT, body_clean TEXT, chunks JSONB,
  section_structure JSONB, parsed_at TIMESTAMPTZ DEFAULT now())
- parsed.tcu_acordaos (id TEXT PK REFERENCES raw.tcu_acordaos(id),
  parser_name TEXT, parser_version TEXT, body_clean TEXT, chunks JSONB,
  section_structure JSONB, parsed_at TIMESTAMPTZ DEFAULT now())
</DESCRIPTION>
<ACCEPTANCE>
- Tables reference raw schema via FK
- Migration idempotent
</ACCEPTANCE>
<DEPENDS>S1-03</DEPENDS>
</ISSUE>

<ISSUE id="S2-14" sprint="2" type="frontend" complexity="M">
<TITLE>DocumentBody component — collapsible sections</TITLE>
<DESCRIPTION>
Create src/frontend/app/src/components/DocumentBody.tsx:
Renders body_clean text with XML-like tags as collapsible sections.

Props: body_clean (string), sections (SectionDef[]), highlight_query (string)

Behavior:
- Parse tags from body_clean → render each as collapsible block with header
- Sections >2000 chars start collapsed
- EMENTA and ACÓRDÃO default open
- Highlight search terms within each section
- TCU RELATÓRIO (up to 48K chars): lazy render, collapsed by default
- Smooth expand/collapse animation
</DESCRIPTION>
<ACCEPTANCE>
- All tag types render correctly (EMENTA, RELATORIO, ARTIGOS, PARTES, etc.)
- Collapse/expand works
- Highlighting works within sections
- Large sections don't block render (lazy for >10K chars)
- Accessible: proper aria attributes
</ACCEPTANCE>
<DEPENDS>S2-04 (needs parser output format defined)</DEPENDS>
</ISSUE>

<ISSUE id="S2-15" sprint="2" type="frontend" complexity="S">
<TITLE>ResultCard matched_section badge</TITLE>
<DESCRIPTION>
Modify src/frontend/app/src/components/ResultCard.tsx:
Add optional matched_section prop (string | null).
When present, show a small pill badge below the snippet:
"encontrado em {matched_section}" (e.g., "encontrado em RELATÓRIO")

Style: light gray background, small text, subtle.
</DESCRIPTION>
<ACCEPTANCE>
- Badge appears when matched_section is non-null
- Badge hidden when null
- Renders correctly on mobile
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

<ISSUE id="S2-16" sprint="2" type="backend" complexity="M">
<TITLE>API: return parsed sections in document endpoint</TITLE>
<DESCRIPTION>
Modify GET /api/document/{id} response to include:
- body_clean: string (tagged text from parsed schema)
- sections: array of {tag, label, default_open} for frontend rendering
- parser_name: string
- parser_version: string

Fallback: if doc not yet parsed, return existing body_plain as <CORPO>.
</DESCRIPTION>
<ACCEPTANCE>
- Parsed docs return structured sections
- Unparsed docs return fallback (no 500 error)
- Response includes parser metadata
</ACCEPTANCE>
<DEPENDS>S2-12</DEPENDS>
</ISSUE>

---

## Sprint 3 — LLM Enrichment

<ISSUE id="S3-01" sprint="3" type="backend" complexity="M">
<TITLE>Create enriched schema DDL</TITLE>
<DESCRIPTION>
SQL migration for schema `enriched`:
- enriched.llm_summaries (doc_id TEXT, corpus TEXT, llm_model TEXT,
  llm_model_version TEXT, resumo TEXT, generated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (doc_id, llm_model_version))
</DESCRIPTION>
<ACCEPTANCE>
- Table created
- PK allows re-generation with new model versions
</ACCEPTANCE>
<DEPENDS>S1-03</DEPENDS>
</ISSUE>

<ISSUE id="S3-02" sprint="3" type="backend" complexity="M">
<TITLE>Eligibility tiering logic</TITLE>
<DESCRIPTION>
Create src/backend/enrichment/tiering.py:
Function get_enrichment_tier(raw_fields: dict, parsed: ParsedDocument) → Tier

Tiers:
- HIGH (always generate RESUMO): TCU completo, portarias, resoluções, editais
- MEDIUM (optional): extratos >500 chars, avisos complexos
- LOW (never): atos de pessoal curtos, retificações simples, <200 chars body

Returns enum: Tier.HIGH, Tier.MEDIUM, Tier.LOW
</DESCRIPTION>
<ACCEPTANCE>
- TCU completo → HIGH
- Short retificação → LOW
- Tests cover all tier boundaries
</ACCEPTANCE>
<DEPENDS>S2-03</DEPENDS>
</ISSUE>

<ISSUE id="S3-03" sprint="3" type="backend" complexity="L">
<TITLE>LLM summary generator script</TITLE>
<DESCRIPTION>
Script ops/generate_summaries.py:
1. Query parsed docs WHERE tier IN (HIGH, MEDIUM) AND no existing summary
2. Build prompt with body_clean (tagged text)
3. Call LLM (Gemini Flash or Qwen — open decision)
4. Store in enriched.llm_summaries
5. Batch processing with rate limiting
6. Supports --limit, --corpus (dou|tcu), --tier (high|medium)

Prompt template should instruct LLM to produce concise Portuguese summary
of 2-3 sentences focused on: what the document does, who it affects, key dates.
</DESCRIPTION>
<ACCEPTANCE>
- Generates summaries for eligible docs
- Rate limiting prevents API quota exhaustion
- Idempotent (skips docs with existing summary for same model version)
- Prompt produces useful 2-3 sentence summaries
</ACCEPTANCE>
<DEPENDS>S3-01, S3-02, S2-12</DEPENDS>
</ISSUE>

<ISSUE id="S3-04" sprint="3" type="frontend" complexity="M">
<TITLE>LlmSummaryCard component</TITLE>
<DESCRIPTION>
Create src/frontend/app/src/components/LlmSummaryCard.tsx:
Displays AI-generated summary above document body.

Props: resumo (string), llm_model (string), generated_at (string)

Visual:
- ✨ sparkle icon + summary text
- Fixed disclaimer: "Gerado por IA — verifique a fonte original"
- Light background card with border
- generated_at as relative date ("há 2 dias")
</DESCRIPTION>
<ACCEPTANCE>
- Renders summary with disclaimer
- Disclaimer always visible (not collapsible)
- Renders nothing when resumo is null/undefined
- Accessible
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

<ISSUE id="S3-05" sprint="3" type="backend" complexity="S">
<TITLE>API: return LLM summary in document endpoint</TITLE>
<DESCRIPTION>
Extend GET /api/document/{id} response to include:
- llm_summary: { resumo, llm_model, generated_at } | null

Query enriched.llm_summaries for latest version.
Null when no summary exists (don't block response).
</DESCRIPTION>
<ACCEPTANCE>
- Enriched docs return summary
- Non-enriched docs return null (no error)
</ACCEPTANCE>
<DEPENDS>S3-03</DEPENDS>
</ISSUE>

---

## Sprint 4 — Embeddings + pgvector + ES v4 + Query v2

<ISSUE id="S4-01" sprint="4" type="backend" complexity="M">
<TITLE>Create embeddings schema DDL</TITLE>
<DESCRIPTION>
SQL migration for schema `embeddings`:
- embeddings.chunks (id BIGSERIAL PK, doc_id TEXT, corpus TEXT, chunk_order INT,
  chunk_type TEXT, text TEXT, embedding vector(3072), model_version TEXT,
  embedded_at TIMESTAMPTZ DEFAULT now())
- CREATE INDEX USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200)

Enable pgvector extension: CREATE EXTENSION IF NOT EXISTS vector.
</DESCRIPTION>
<ACCEPTANCE>
- Table created with vector column
- IVFFlat index builds (requires data for training — may need to defer index until after data load)
</ACCEPTANCE>
<DEPENDS>S1-01</DEPENDS>
</ISSUE>

<ISSUE id="S4-02" sprint="4" type="backend" complexity="XL">
<TITLE>Embedding indexer: chunks → pgvector</TITLE>
<DESCRIPTION>
Script ops/embed_indexer_v2.py:
1. Read from parsed.*.chunks + enriched.llm_summaries
2. Call Gemini gemini-embedding-2-preview (dims=3072, batch 100 texts)
3. Write to embeddings.chunks
4. Retry logic on 429/5xx with exponential backoff
5. Supports --corpus, --limit, --batch-size
6. Resume capability (skip already-embedded chunks by model_version)

Cost estimate: ~$29.25 per 1M docs (from PoC).
Total: ~16.5M docs × multiple chunks = significant. Plan batching carefully.
</DESCRIPTION>
<ACCEPTANCE>
- Embeds all parsed chunks
- Retry logic handles API errors
- Resume after interruption without re-embedding
- Cost tracking (log tokens consumed)
</ACCEPTANCE>
<DEPENDS>S4-01, S2-12, S3-03</DEPENDS>
</ISSUE>

<ISSUE id="S4-03" sprint="4" type="backend" complexity="L">
<TITLE>ES index v4 mapping (BM25-only)</TITLE>
<DESCRIPTION>
Create src/backend/search/es_index_v4.json:
Copy v3 mapping but REMOVE:
- embedding field (dense_vector)
- embedding_status, embedding_model fields

Add:
- parser_name: keyword
- parser_version: keyword
- body_clean: text (pt_br_folded) — parsed tagged text as additional search field

Keep all existing BM25 fields unchanged (identifica, ementa, body_plain, search_all, etc.)
</DESCRIPTION>
<ACCEPTANCE>
- No vector fields in v4
- body_clean field added with correct analyzer
- All v3 BM25 fields preserved
- Mapping validates with ES PUT _mappings
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

<ISSUE id="S4-04" sprint="4" type="backend" complexity="L">
<TITLE>ES indexer v4: parsed → gabi_documents_v4</TITLE>
<DESCRIPTION>
Modify or create indexer that reads from parsed.* tables and writes to
gabi_documents_v4 ES index. Include body_clean and parser metadata.
Alias swap: gabi_documents → v4 (after validation).

Should reindex all documents, not just parsed ones — unparsed docs
use body_plain as fallback.
</DESCRIPTION>
<ACCEPTANCE>
- All ~16.5M docs indexed in v4
- body_clean populated for parsed docs
- Alias swap from v3→v4 works
- Search still returns results after swap
</ACCEPTANCE>
<DEPENDS>S4-03, S2-12</DEPENDS>
</ISSUE>

<ISSUE id="S4-05" sprint="4" type="backend" complexity="XL">
<TITLE>Query v2: RRF(ES BM25, pgvector kNN)</TITLE>
<DESCRIPTION>
Create src/backend/search/hybrid_v2.py:
New search function that combines:
1. ES BM25 search (existing) → ranked list
2. pgvector kNN search (embed query → cosine similarity) → ranked list
3. RRF fusion: score = Σ 1/(k + rank_i) with k=60

Feature flag: QUERY_V2_ENABLED (default false).
When false, use existing v1 search.
When true, use RRF hybrid.

Query embedding: call Gemini API to embed search query, then query pgvector.
</DESCRIPTION>
<ACCEPTANCE>
- Feature flag works (false = v1, true = v2)
- RRF produces merged ranked results
- latency < 500ms p95
- Tests with mock embedding
</ACCEPTANCE>
<DEPENDS>S4-02, S4-04</DEPENDS>
</ISSUE>

<ISSUE id="S4-06" sprint="4" type="backend" complexity="M">
<TITLE>Shadow mode: log v1 vs v2 results</TITLE>
<DESCRIPTION>
When QUERY_V2_SHADOW=true, run BOTH v1 and v2 for every search query.
Return v1 results to user, but log both result sets for offline comparison.

Log format: { query, timestamp, v1_ids (top 20), v2_ids (top 20), overlap_count }
Store in a file or table for analysis.
</DESCRIPTION>
<ACCEPTANCE>
- Both queries run in parallel
- User sees only v1 results (no latency impact from v2 on user response)
- Comparison log written
- Log doesn't grow unbounded (rotation or TTL)
</ACCEPTANCE>
<DEPENDS>S4-05</DEPENDS>
</ISSUE>

<ISSUE id="S4-07" sprint="4" type="frontend" complexity="S">
<TITLE>SearchModeIndicator component</TITLE>
<DESCRIPTION>
Create src/frontend/app/src/components/SearchModeIndicator.tsx:
Pill badge at top of search results indicating active mode.

Props: mode ('bm25' | 'hybrid'), is_shadow (boolean)

Visual:
- mode='bm25': "Busca textual" (gray pill)
- mode='hybrid': "Busca híbrida" (blue pill)
- is_shadow=true: "⚡ Testando novo ranking" (amber pill)
</DESCRIPTION>
<ACCEPTANCE>
- Three visual states render correctly
- Only shown when mode prop is provided
</ACCEPTANCE>
<DEPENDS>none</DEPENDS>
</ISSUE>

---

## Sprint 5 — Cutover + Cleanup

<ISSUE id="S5-01" sprint="5" type="ops" complexity="M">
<TITLE>Shadow mode analysis script</TITLE>
<DESCRIPTION>
Script ops/analyze_shadow.py:
Read shadow comparison logs and compute:
- Overlap@10, Overlap@20 between v1 and v2
- Mean reciprocal rank delta
- Queries where v1 and v2 diverge most
- Recommendation: PASS/FAIL for cutover

Define threshold before running (open question from SPEC).
</DESCRIPTION>
<ACCEPTANCE>
- Produces quantitative report
- Clear PASS/FAIL recommendation
- Lists top-divergent queries for human review
</ACCEPTANCE>
<DEPENDS>S4-06</DEPENDS>
</ISSUE>

<ISSUE id="S5-02" sprint="5" type="ops" complexity="S">
<TITLE>Cutover: flip QUERY_V2_ENABLED=true</TITLE>
<DESCRIPTION>
Flip feature flags in production:
- QUERY_V2_ENABLED=true
- QUERY_V2_SHADOW=false (stop logging)
- Update .env on Hetzner

Rollback plan: flip back to false, revert .env. v1 stays frozen 2 weeks.
</DESCRIPTION>
<ACCEPTANCE>
- Search uses RRF hybrid after flip
- Rollback tested and documented
- Monitoring confirmed (latency, error rate)
</ACCEPTANCE>
<DEPENDS>S5-01</DEPENDS>
</ISSUE>

<ISSUE id="S5-03" sprint="5" type="ops" complexity="M">
<TITLE>Cleanup deprecated artifacts</TITLE>
<DESCRIPTION>
After 2 weeks of stable v2 operation, remove:
- ES indexes v1/v2/v3 (keep only v4)
- ops/embed_indexer.py (old ES-targeting embedder)
- Qwen MLX embedding server (if not used as fallback)
- Dense_vector references in search code
- MongoDB volume (if destruction gate passed 30+ days ago)

Create checklist and verify each item before deletion.
</DESCRIPTION>
<ACCEPTANCE>
- All deprecated artifacts listed
- Each removal verified independently
- No broken imports or references
- Search still works after cleanup
</ACCEPTANCE>
<DEPENDS>S5-02</DEPENDS>
</ISSUE>

---

## Summary

<SUMMARY>
Total: 35 issues across 5 sprints

| Sprint | Issues | Types                          |
|--------|--------|--------------------------------|
| 1      | 8      | 3 infra, 3 backend, 1 ops, 1 S |
| 2      | 16     | 2 research, 10 backend, 2 frontend, 1 backend, 1 DDL |
| 3      | 5      | 2 backend, 1 frontend, 1 DDL, 1 API |
| 4      | 7      | 4 backend, 1 frontend, 1 DDL, 1 ops |
| 5      | 3      | 2 ops, 1 cleanup               |

Critical path: S1-01 → S1-03 → S1-04 → S2-02 → S2-06/07/08 → S2-12 → S4-02 → S4-05 → S5-01

Dependencies that block most work:
- S1-01 (Postgres infra) blocks everything
- S2-02 (real data sampling) blocks all DOU parsers
- S2-03 (parser interface) blocks all parser implementations
</SUMMARY>