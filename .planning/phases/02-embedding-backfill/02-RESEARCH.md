# Phase 2: Embedding Backfill Pipeline — Detailed Plan

## Overview

Build `src/backend/ingest/embed_indexer.py` — a resumable, cursor-based pipeline that:
1. Reads documents from MongoDB that need embedding
2. Constructs embedding input text from document fields with calibrated character-based truncation
3. Calls Cohere embed-multilingual-v3.0 API in batches
4. Writes embeddings to Elasticsearch, then updates MongoDB status
5. Tracks per-document status for resumability with crash-safe state transitions

## Dependencies (Step -1)

Add to `requirements.txt`:
```
cohere>=5.11,<6.0
```

No HuggingFace tokenizers dependency. No Rust toolchain required on ARM/aarch64.

## Plan 02-00: Tokenizer Calibration (MUST run before 02-01)

**This is a blocking prerequisite.** The pipeline cannot be built on unvalidated assumptions about Cohere's tokenizer.

### Calibration Script: `scripts/calibrate_tokenizer.py`

1. Sample 1,000 documents from MongoDB (stratified: 333 from first third of `_id` space, 334 from middle, 333 from last third).
2. Build embedding text for each using `clean_text()` + field concatenation (identifica + ementa + texto).
3. For each text, call `co.tokenize(text=text, model="embed-multilingual-v3.0")` to get the authoritative token count.
4. Compute:
   - **chars_per_token ratio**: median, p5, p25, p75, p95 across Portuguese legal text
   - **token count distribution**: histogram of document token counts
   - **% of documents exceeding 512 tokens** (before truncation)
   - **% of documents with HTML markup**
5. Output a `config/tokenizer_calibration.json`:

```json
{
    "calibrated_at": "2025-01-15T10:00:00Z",
    "sample_size": 1000,
    "chars_per_token_p5": 2.1,
    "chars_per_token_median": 2.8,
    "chars_per_token_p95": 3.5,
    "safe_chars_per_token": 2.1,
    "char_truncation_limit": 1075,
    "pct_docs_over_512_tokens": 42.3,
    "pct_docs_with_html": 12.5,
    "token_count_p50": 380,
    "token_count_p95": 512,
    "cohere_api_calls_used": 1000,
    "cost_usd": 0.04
}
```

**Key output**: `char_truncation_limit` = `512 * safe_chars_per_token` (using p5 ratio — the most conservative). This becomes the hard character ceiling for truncation. No local tokenizer, no XLM-R dependency, no unvalidated proxy.

**Cost**: 1,000 tokenize API calls ≈ $0.04. Negligible.

**Go/no-go**: If `safe_chars_per_token` < 1.5 (meaning Portuguese legal text is extraordinarily token-dense), escalate for manual review before proceeding.

## Plan 02-01: Build embed_indexer.py

### Pre-flight Checks (Step 0)

Before any backfill run, the pipeline executes these checks and aborts on failure:

1. **Calibration file exists**: Load `config/tokenizer_calibration.json`. Abort if missing: "Run `python3 scripts/calibrate_tokenizer.py` first."

2. **ID mapping validation**: Sample **1,000** MongoDB documents (stratified across `_id` space: 333 early, 334 middle, 333 late), verify `str(doc["_id"])` resolves to an existing ES document in `gabi_documents_v2`. Additionally, verify the `str()` conversion matches the format used by `es_indexer.py` (inspect its source to confirm). Abort if any mismatch — the entire dual-write strategy depends on this.

3. **ES vector field compatibility**: Call Cohere embed with a single test string, get a real 1024-dim float32 vector, index it into ES `embedding` field (int8_hnsw). Verify ES accepts float32 and quantizes on ingest. Verify `len(embedding) == 1024`. If ES rejects it, switch Cohere call to `embedding_types=["int8"]`. Document the verified behavior in a config constant.

4. **Cohere API key and tier validation**: Parse the rate limit tier from the test embed call's behavior. If on trial/free tier (10M tokens/month), abort with message: "Production tier required — 6.5B tokens needed, free tier allows 10M/month (would take ~54 years)."

5. **MongoDB index verification**: Confirm compound index `{embedding_status: 1, _id: 1}` exists. Create it if missing.

6. **Upfront migration check**: Verify that `embedding_status` and `embedding_attempts` fields have been initialized on all documents (see Migration section). Abort if >1% of documents lack either field.

7. **Token budget validation**: Take 10 documents from the calibration sample that are near the character truncation limit. Truncate them, call `co.embed()`, verify none return 400/token-limit errors. If any fail, reduce `char_truncation_limit` by 10% and re-test. This validates the entire truncation pipeline end-to-end before processing 16.3M docs.

8. **ARM/aarch64 compatibility**: Verify `cohere` and `numpy` import successfully on the ARM VM.

### One-Time Upfront Migration (Step 0.5)

**Run once before the first backfill.** Sets `embedding_status: "pending"` and `embedding_attempts: 0` on all documents that lack either field:

```python
result = db.documents.update_many(
    {"$or": [
        {"embedding_status": {"$exists": False}},
        {"embedding_attempts": {"$exists": False}}
    ]},
    {"$set": {"embedding_status": "pending", "embedding_attempts": 0}}
)
logger.info(f"Initialized {result.modified_count} documents to 'pending' with attempts=0")
```

**Why upfront migration is required:** Without it, querying for documents missing the field requires `$exists: False`, which cannot use the compound index `{embedding_status: 1, _id: 1}`. The migration takes 3-5 minutes and makes every subsequent cursor query an efficient index scan. Initializing `embedding_attempts` ensures the `$not: {$gte: MAX_ATTEMPTS}` query predicate behaves deterministically.

The CLI exposes this as:
```bash
python3 -m src.backend.ingest.embed_indexer init-status
```

### Truncation Strategy

**The core problem:** Cohere embed-multilingual-v3.0 has a 512-token input limit. Cohere's tokenizer is proprietary and not available locally.

**Solution: Calibrated character-based truncation.**

Plan 02-00 measures the actual chars-per-token ratio on Portuguese legal text using Cohere's own `co.tokenize()` endpoint. We use the p5 ratio (most conservative — the ratio at which 95% of text is *more* chars-per-token) to derive a hard character ceiling.

```python
import json

# Loaded once at startup from calibration output
with open("config/tokenizer_calibration.json") as f:
    _calibration = json.load(f)

# Hard character ceiling — calibrated in 02-00
# Example: if p5 chars_per_token = 2.1, then 512 * 2.1 = 1075 chars
CHAR_TRUNCATION_LIMIT: int = _calibration["char_truncation_limit"]

def truncate_to_limit(text: str, max_chars: int) -> str:
    """Truncate text at sentence boundary within character limit.

    Prefers clean sentence breaks for better embedding quality.
    Falls back to hard cut if no sentence boundary found in last 20% of text.
    """
    if len(text) <= max_chars:
        return text

    # Try to find sentence boundary in the last 20% of allowed chars
    search_start = int(max_chars * 0.8)
    candidate = text[:max_chars]

    # Look for sentence-ending punctuation (Portuguese legal text patterns)
    for sep in (". ", ".\n", "; ", ".\t"):
        last_break = candidate.rfind(sep, search_start)
        if last_break > 0:
            return candidate[:last_break + 1].strip()

    # No clean break — hard truncate at char limit
    return candidate.strip()
```

**Why not a local tokenizer proxy (XLM-R, etc.):** Cohere embed-multilingual-v3.0 uses a proprietary tokenizer. XLM-R (SentencePiece) and Cohere's BPE tokenizer diverge significantly on Portuguese legal abbreviations (Art., §, CNPJ, Lei nº). A 5% safety margin is insufficient — calibration data from 02-00 will quantify actual divergence, but we avoid the dependency entirely. Character-based truncation with calibrated ratios is simpler, has zero external dependencies, and eliminates the Rust toolchain requirement on ARM/aarch64.

**Safety net**: If Cohere returns a 400 for token limit exceeded during backfill, the batch bisection logic isolates the offending document. The pipeline logs a CRITICAL and automatically reduces `CHAR_TRUNCATION_LIMIT` by 5% for subsequent batches. If this happens more than 10 times in a run, the pipeline aborts for manual review of calibration data.

### Text Construction Strategy

For each document, construct embedding input from MongoDB fields `identifica`, `ementa`, `texto`.

```python
SEPARATOR = "\n"

def build_embedding_text(doc: dict) -> str | None:
    """Build embedding input, truncating to fit character limit.

    Priority: identifica (title) > ementa (summary) > texto (body).
    identifica and ementa are always included in full (they are short).
    texto fills the remaining character budget.
    Returns None if no usable text (caller marks doc as 'skipped').
    """
    parts = []
    chars_used = 0

    for field in ["identifica", "ementa", "texto"]:
        raw = doc.get(field) or ""
        value = clean_text(raw)
        if not value:
            continue

        sep_chars = len(SEPARATOR) if parts else 0
        available = CHAR_TRUNCATION_LIMIT - chars_used - sep_chars

        if available <= 20:
            break

        if len(value) <= available:
            parts.append(value)
            chars_used += sep_chars + len(value)
        else:
            truncated = truncate_to_limit(value, available)
            if truncated and len(truncated) >= 20:
                parts.append(truncated)
            break

    text = SEPARATOR.join(parts).strip()
    if len(text) < 10:
        return None
    return text
```

**Edge cases handled:**
- `identifica`, `ementa`, or `texto` is None/empty/whitespace → skip that field
- All three fields empty → return None, mark document as `"skipped"` with reason `"no_text_content"`
- Text contains null bytes → stripped in `clean_text()`
- Text contains HTML/XML markup → stripped conditionally in `clean_text()` (see below)
- `identifica` + `ementa` alone exceed budget → truncate `ementa`, omit `texto`
- Sentence-boundary truncation preserves complete legal clauses where possible

**Long document handling:** If `len(doc.get("texto", "")) > 50_000` (50KB), skip the tokenizer-intensive path — the document will certainly be truncated. Apply `clean_text()` to only the first `CHAR_TRUNCATION_LIMIT * 2` characters of `texto` to avoid processing 100-page documents through HTML stripping. This caps per-document memory at ~2KB of cleaned text regardless of source document size.

### Input Validation and Cleaning

```python
import re
from html import unescape

# Compiled once at module level
_HTML_TAG_RE = re.compile(r'<(?:/?(?:p|br|div|table|tr|td|th|span|a|b|i|em|strong|ul|ol|li|h[1-6])\b)[^>]*>', re.IGNORECASE)
_WHITESPACE_RE = re.compile(r'\s+')

# Whether to strip HTML — set from calibration data
STRIP_HTML: bool = True  # Updated from calibration: if pct_docs_with_html < 5%, set False

def clean_text(raw: str) -> str | None:
    """Clean and validate text for embedding input.

    Returns cleaned text or None if unusable.
    """
    if raw is None:
        return None

    if not isinstance(raw, str):
        # PyMongo returns str, not bytes. Log and skip if unexpected type.
        logger.warning(f"Unexpected type {type(raw)} for field value, skipping")
        return None

    text = raw

    # Strip null bytes
    text = text.replace("\x00", "")

    # Strip HTML/XML tags (common in DOU regulatory texts with embedded tables)
    # Uses allowlist of known HTML tags — preserves angle brackets in legal
    # citations like "Art. <número>" and mathematical expressions
    if STRIP_HTML:
        text = unescape(text)  # Convert HTML entities first
        # Preserve paragraph boundaries before stripping
        text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
        text = _HTML_TAG_RE.sub(' ', text)

    # Normalize whitespace
    text = _WHITESPACE_RE.sub(' ', text)

    text = text.strip()
    if len(text) < 10:
        return None
    return text
```

**HTML stripping rationale:** Brazilian DOU documents frequently contain embedded HTML markup, especially tables in regulatory texts. The regex uses an allowlist of known HTML tag names rather than a greedy `<[^>]+>` pattern, which would destroy legitimate angle brackets in legal citations. Plan 02-00 calibration measures the % of documents with HTML; if <5%, `STRIP_HTML` is set to `False` for performance. If >20%, consider switching to BeautifulSoup (add as dependency only if needed).

### MongoDB Schema Design

**Fields added to existing `documents` collection:**

```python
{
    "embedding_status": "pending" | "processing" | "done" | "failed" | "skipped",
    "embedding_model": "embed-multilingual-v3.0",
    "embedding_updated_at": ISODate,
    "embedding_queued_at": ISODate,     # Set when status → "processing"
    "embedding_error": "error message",  # Set on failed/skipped
    "embedding_attempts": 0,            # Incremented on each attempt
    "embedding_text_hash": "a1b2c3d4"   # xxhash32 of constructed text (4 bytes)
}
```

`embedding_text_hash` enables: (1) detecting documents whose source text changed since last embedding (incremental re-embedding), (2) deduplication — if two documents produce identical embedding text, the embedding vector can be reused in a future optimization pass.

**Required indexes (created in pre-flight, idempotent):**

```python
db.documents.create_index(
    [("embedding_status", 1), ("_id", 1)],
    name="idx_embedding_status_id"
)

db.documents.create_index(
    [("embedding_updated_at", 1)],
    name="idx_embedding_updated_at"
)
```

### Cursor Design

```python
from pymongo import ReturnDocument

MAX_ATTEMPTS = 3

def fetch_and_claim_batch(
    collection,
    batch_size: int = 96,
    shard_filter: dict | None = None
) -> list[dict]:
    """Atomically fetch and claim documents using findOneAndUpdate.

    Each document is individually claimed via findOneAndUpdate — no race
    condition between fetch and claim. Uses _id cursor internally for
    efficient pagination within a single batch fetch.
    """
    base_query = {
        "embedding_status": {"$in": ["pending", "processing"]},
        "embedding_attempts": {"$not": {"$gte": MAX_ATTEMPTS}}
    }

    if shard_filter:
        base_query.update(shard_filter)

    docs = []
    last_claimed_id = None

    for _ in range(batch_size):
        query = {**base_query}
        if last_claimed_id is not None:
            query["_id"] = {"$gt": last_claimed_id}

        doc = collection.find_one_and_update(
            query,
            {
                "$set": {
                    "embedding_status": "processing",
                    "embedding_queued_at": datetime.utcnow(),
                },
                "$inc": {"embedding_attempts": 1}
            },
            sort=[("_id", 1)],
            return_document=ReturnDocument.AFTER
        )

        if doc is None:
            break

        docs.append(doc)
        last_claimed_id = doc["_id"]

    return docs
```

**Why `findOneAndUpdate` instead of find+bulk_write:** The original design had a race condition — `find()` and `bulk_write()` are separate operations. Between them, another instance could fetch the same documents. `findOneAndUpdate` is atomic: each document is claimed in a single roundtrip. The cost is 96 roundtrips instead of 2, but at ~0.5ms each on localhost that's ~48ms total — negligible compared to the ~2s Cohere API call.

**State machine (per document):**

```
"pending" ──→ "processing" ──→ "done"
                   │
                   ├──→ "failed" (after MAX_ATTEMPTS=3)
                   │
                   └──→ "skipped" (empty text)
```

**Crash safety:**
- `findOneAndUpdate` atomically marks each doc as `"processing"` and increments `embedding_attempts`
- On startup: a mandatory recovery sweep resets stale `"processing"` documents (see Startup Recovery below)
- `embedding_attempts` check prevents infinite re-processing of poison-pill documents
- A crashed batch costs at most 96 duplicate API calls (~$0.005) — acceptable

### Startup Recovery Sweep

**Mandatory on every pipeline start**, before entering the main loop:

```python
STALE_PROCESSING_THRESHOLD_MINUTES = 120  # 2 hours

def recover_stale_processing(collection) -> int:
    """Reset stale 'processing' docs from crashed runs back to 'pending'.

    This prevents the cursor-advancing-past-orphans problem: since the
    cursor only moves forward by _id, any 'processing' doc behind the
    cursor from a previous crash would never be re-visited. This sweep
    ensures they are reset before we start.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_THRESHOLD_MINUTES)
    result = collection.update_many(
        {
            "embedding_status": "processing",
            "embedding_queued_at": {"$lt": cutoff},
            "embedding_attempts": {"$not": {"$gte": MAX_ATTEMPTS}}
        },
        {"$set": {"embedding_status": "pending"}}
    )
    if result.modified_count > 0:
        logger.warning(
            f"Recovery sweep: reset {result.modified_count} stale 'processing' "
            f"docs (queued before {cutoff.isoformat()}) back to 'pending'"
        )
    return result.modified_count
```

**Why this is mandatory, not optional:** The `_id` cursor only moves forward. If a previous run crashed after claiming documents (set to `"processing"`) but before completing them, and those documents have `_id` values earlier than where the new run's cursor starts, they become permanent orphans. This sweep eliminates that class of bug entirely.

### Concurrency Guard (Advisory Lock)

```python
from pymongo.errors import DuplicateKeyError

LOCK_TTL_MINUTES = 30
LOCK_REFRESH_MINUTES = 10
LOCK_ACQUIRE_RETRIES = 3

def acquire_lock(db, holder_id: str) -> bool:
    """Acquire advisory lock using atomic upsert. Returns True if acquired."""
    # Ensure TTL index exists (idempotent)
    # expireAfterSeconds on the expires_at field: MongoDB deletes docs
    # when expires_at + expireAfterSeconds <= now. With 0, it deletes
    # when expires_at <= now. This is valid — MongoDB 3.0+ supports 0.
    db.locks.create_index("expires_at", expireAfterSeconds=0, name="ttl_locks")

    now = datetime.utcnow()

    for attempt in range(LOCK_ACQUIRE_RETRIES):
        # Atomic: either insert new lock OR steal expired lock
        result = db.locks.find_one_and_update(
            {
                "_id": "embed_backfill",
                "$or": [
                    {"expires_at": {"$lt": now}},  # Expired
                    {"holder": holder_id}           # We already hold it (re-acquire)
                ]
            },
            {
                "$set": {
                    "holder": holder_id,
                    "acquired_at": now,
                    "expires_at": now + timedelta(minutes=LOCK_TTL_MINUTES)
                }
            },
            upsert=False,
            return_document=ReturnDocument.AFTER
        )

        if result is not None:
            logger.info(f"Acquired lock (attempt {attempt + 1})")
            return True

        # Lock doc may not exist yet — try insert
        try:
            db.locks.insert_one({
                "_id": "embed_backfill",
                "holder": holder_id,
                "acquired_at": now,
                "expires_at": now + timedelta(minutes=LOCK_TTL_MINUTES)
            })
            logger.info("Acquired lock (new)")
            return True
        except DuplicateKeyError:
            # Another instance holds a non-expired lock
            if attempt < LOCK_ACQUIRE_RETRIES - 1:
                time.sleep(2)
                continue

            existing = db.locks.find_one({"_id": "embed_backfill"})
            if existing:
                logger.error(
                    f"Lock held by {existing['holder']} "
                    f"until {existing['expires_at']}"
                )
            return False

    return False

def refresh_lock(db, holder_id: str):
    """Refresh lock TTL. Called by daemon background thread."""
    result = db.locks.update_one(
        {"_id": "embed_backfill", "holder": holder_id},
        {"$set": {"expires_at": datetime.utcnow() + timedelta(minutes=LOCK_TTL_MINUTES)}}
    )
    if result.modified_count == 0:
        raise RuntimeError("Lost advisory lock — another instance may have stolen it")

def release_lock(db, holder_id: str):
    """Release lock on clean shutdown."""
    db.locks.delete_one({"_id": "embed_backfill", "holder": holder_id})
```

Lock refresh runs on a daemon background thread (see Graceful Shutdown). The `find_one_and_update` with `$or` condition is fully atomic — only one instance can succeed in stealing an expired lock.

### Cohere API Integration

```python
import cohere

co = cohere.ClientV2(
    api_key=os.getenv("COHERE_API_KEY"),
    timeout=60.0,
)

EXPECTED_DIMS = 1024

def call_cohere_embed(texts: list[str]) -> list[list[float]]:
    """Call Cohere embed API. Caller handles retry/bisect."""
    response = co.embed(
        texts=texts,
        model="embed-multilingual-v3.0",
        input_type="search_document",
        embedding_types=["float"],
    )
    embeddings = response.embeddings.float_

    # Validate dimensions — catch model/config mismatch before ES write
    if embeddings and len(embeddings[0]) != EXPECTED_DIMS:
        raise ValueError(
            f"Expected {EXPECTED_DIMS} dims, got {len(embeddings[0])}. "
            f"Model or API config mismatch."
        )

    return embeddings
```

**ES int8_hnsw behavior:** Elasticsearch's `int8_hnsw` index type accepts float32 vectors and performs scalar quantization on ingest. Verified in pre-flight check. We use `float` from Cohere to preserve maximum precision before ES quantizes, rather than double-quantizing by requesting `int8` from Cohere.

### Batching Strategy

```
fetch_and_claim_batch (96 docs — atomically claimed via findOneAndUpdate)
    → clean_text + build_embedding_text (filter empty → collect as "skipped")
    → Cohere embed API call (≤96 texts, each ≤CHAR_TRUNCATION_LIMIT chars)
    → ES bulk update (write embeddings, with retry_on_conflict=3)
    → MongoDB bulk_write (set "done" for successful, "failed" for ES failures)
    → Write checkpoint (atomic file rename)
```

- **MongoDB fetch + claim**: 96 `findOneAndUpdate` calls per batch (~48ms total)
- **Cohere API call**: 1 call per batch. Each text pre-validated to ≤CHAR_TRUNCATION_LIMIT chars
- **ES bulk update**: 96 docs per `_bulk` request
- **MongoDB status update**: 96 docs per `bulk_write`

**Batch filling after skips:** If some documents in a batch are skipped (empty text), the Cohere call proceeds with <96 texts. We do NOT fetch additional documents to fill the batch — the complexity isn't worth the marginal cost savings.

**Write ordering (critical for consistency):** ES write happens BEFORE MongoDB status update. Crash scenarios:
- After Cohere call but before ES write → MongoDB still says "processing" → recovery sweep resets to "pending" → batch retried on restart
- After ES write but before MongoDB update → MongoDB still says "processing" → recovery sweep resets → batch retried, ES gets duplicate update (idempotent), MongoDB then set to "done"
- After MongoDB update → fully consistent

**No threading for MongoDB fetch.** PyMongo cursors are not thread-safe. The Cohere API call (~1-3s) dominates batch time; MongoDB fetch (~48ms) is negligible. Sequential processing is correct and sufficient.

### Rate Limiting & Retry

**Error classification:**

| Error Type | HTTP Code | Action |
|---|---|---|
| Rate limit | 429 | Retry with backoff |
| Server error | 500, 502, 503 | Retry with backoff |
| Timeout / connection | N/A | Retry with backoff |
| Token limit exceeded | 400 (token_limit) | Reduce CHAR_TRUNCATION_LIMIT by 5%, bisect batch |
| Content policy violation | 400 (content_policy) | Mark individual doc as skipped, do NOT bisect |
| Other bad request | 400 | Bisect batch to isolate bad doc |
| Auth error | 401, 403 | Abort pipeline immediately |

**Retry with exponential backoff + jitter:**

```python
import random

MAX_RETRIES_PER_CALL = 5

def retry_delay(attempt: int) -> float:
    """Exponential backoff: 2s, 4s, 8s, 16s, 32s with ±50% jitter."""
    base = 2.0 * (2 ** attempt)
    return base * random.uniform(0.5, 1.5)
```

**Configurable inter-batch delay:**

```python
# Default: 0.5s between batches.
# At 96 docs/batch with 0.5s delay + ~2s API call: ~1440 batches/hour = ~115K docs/hour
parser.add_argument("--delay", type=float, default=0.5,
                    help="Seconds to sleep between batches (rate limit control)")
```

**Bisect-on-failure for non-retriable errors:**

```python
MAX_BISECT_DEPTH = 7  # log2(96) ≈ 6.6

@dataclass
class EmbedFailure:
    doc_id: str
    error: str

def embed_with_bisect(
    texts: list[str],
    doc_ids: list[str],
    depth: int = 0
) -> tuple[list[tuple[str, list[float]]], list[EmbedFailure]]:
    """Returns (successes, failures). Does NOT write to MongoDB.

    Successes: list of (doc_id, embedding) tuples.
    Failures: list of EmbedFailure for finalize_batch to handle.
    """
    try:
        embeddings = call_cohere_embed(texts)
        return list(zip(doc_ids, embeddings)), []
    except cohere.core.ApiError as e:
        status = getattr(e, 'status_code', None)

        # Retriable errors — bubble up for caller's retry loop
        if status in (429, 500, 502, 503) or status is None:
            raise

        # Content policy — mark individual docs without bisecting
        error_body = str(getattr(e, 'body', e))
        if "content_policy" in error_body.lower():
            return [], [
                EmbedFailure(did, f"content_policy_violation: {error_body}")
                for did in doc_ids
            ]

        # Token limit exceeded — reduce ceiling and bisect
        if "token" in error_body.lower() and "limit" in error_body.lower():
            global CHAR_TRUNCATION_LIMIT
            old_limit = CHAR_TRUNCATION_LIMIT
            CHAR_TRUNCATION_LIMIT = int(CHAR_TRUNCATION_LIMIT * 0.95)
            logger.critical(
                f"Token limit exceeded. Reducing CHAR_TRUNCATION_LIMIT: "
                f"{old_limit} → {CHAR_TRUNCATION_LIMIT}"
            )

        # Bisect to isolate bad document(s)
        if len(texts) == 1:
            return [], [EmbedFailure(doc_ids[0], str(e))]
        if depth >= MAX_BISECT_DEPTH:
            return [], [
                EmbedFailure(did, f"bisect_depth_exceeded: {e}")
                for did in doc_ids
            ]
        mid = len(texts) // 2
        left_ok, left_fail = embed_with_bisect(texts[:mid], doc_ids[:mid], depth + 1)
        right_ok, right_fail = embed_with_bisect(texts[mid:], doc_ids[mid:], depth + 1)
        return left_ok + right_ok, left_fail + right_fail
    except (TimeoutError, ConnectionError, OSError) as e:
        # Network errors — retriable
        raise
```

**Token limit auto-reduction circuit breaker:** If `CHAR_TRUNCATION_LIMIT` is reduced more than 10 times in a single run, abort pipeline: "Calibration data is stale — re-run `calibrate_tokenizer.py`."

**Circuit breaker for server errors:** If 10 consecutive batches fail with server errors (not 400s), pause for 60 seconds, then retry. If 50 consecutive failures, abort pipeline.

### ES Update

```python
from elasticsearch.helpers import bulk as es_bulk

def update