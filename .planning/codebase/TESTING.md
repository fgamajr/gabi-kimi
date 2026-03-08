# Testing Patterns

**Analysis Date:** 2026-03-08

## Overview

The project has two completely separate testing approaches:

1. **Frontend (TypeScript):** Vitest + Testing Library — minimal, scaffold-level only
2. **Backend (Python):** Custom hand-rolled test harness — no pytest, no unittest framework

## Frontend Test Framework

**Runner:**
- Vitest 3.2.4
- Config: `src/frontend/web/vitest.config.ts`

**Assertion Library:**
- Vitest built-in (`expect`, `describe`, `it`)
- `@testing-library/jest-dom` for DOM matchers (imported in setup)

**Environment:**
- jsdom (configured in `vitest.config.ts`)
- `globals: true` — test functions available without import

**Setup File:**
- `src/frontend/web/src/test/setup.ts`
- Imports `@testing-library/jest-dom`
- Mocks `window.matchMedia` (required for responsive components)

**Run Commands:**
```bash
cd src/frontend/web
npm run test               # vitest run (single pass)
npm run test:watch         # vitest (watch mode)
```

## Frontend Test File Organization

**Location:**
- Co-located under `src/frontend/web/src/test/`
- Pattern: `src/**/*.{test,spec}.{ts,tsx}` (configured in vitest)

**Naming:**
- `example.test.ts` — the only test file that exists

**Current State:**
- Only one test file exists: `src/frontend/web/src/test/example.test.ts`
- It is a trivial placeholder (`expect(true).toBe(true)`)
- No component tests, no integration tests, no API mocking

**Structure:**
```typescript
// src/frontend/web/src/test/example.test.ts
import { describe, it, expect } from "vitest";

describe("example", () => {
  it("should pass", () => {
    expect(true).toBe(true);
  });
});
```

**Available but Unused Libraries:**
- `@testing-library/react` ^16.0.0 — installed but no tests use it
- `jsdom` ^20.0.3 — configured but only the placeholder test runs

## Backend Test Framework

**Runner:**
- Custom hand-rolled test harness — **no pytest, no unittest**
- Each test file is a standalone Python script with `if __name__ == "__main__"` entry point
- Tests are run directly: `python3 tests/test_bulk_pipeline.py`

**Assertion Pattern:**
- Global `_passed`/`_failed` counters (mutable global state)
- Custom `_assert(condition, msg)` function that increments counters
- Some files add `_assert_eq(actual, expected, msg)` for equality checks
- No exception on failure — just increments counter and prints to stderr

```python
# Pattern used in all backend test files
_passed = 0
_failed = 0

def _assert(condition: bool, msg: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}", file=sys.stderr)
```

**Run Commands:**
```bash
python3 tests/test_bulk_pipeline.py      # XML parsing, normalization, ZIP handling
python3 tests/test_commitment.py         # CRSS-1 serializer, Merkle tree, proofs
python3 tests/test_dou_ingest.py         # HTML extraction, signatures, norm refs
python3 tests/test_search_adapters.py    # Search adapter query translation
python3 tests/test_image_checker.py      # Image classification, fallback text
python3 tests/test_seal_roundtrip.py     # Integration: requires running PostgreSQL
```

## Backend Test File Organization

**Location:**
- All tests in top-level `tests/` directory
- Fixtures in `tests/fixtures/xml_samples/` (real DOU XML documents)

**Naming:**
- `test_<module_area>.py`

**Structure:**
```
tests/
├── __init__.py
├── fixtures/
│   └── xml_samples/
│       ├── 2026-02-27-DO1_515_20260227_23615168.xml
│       ├── 2026-02-27-DO1E_600_20260227_23639224.xml
│       ├── ... (13 XML fixture files)
│       └── 2026-03-01-DO1E_602_20260301_23639608.xml
├── test_bulk_pipeline.py
├── test_commitment.py
├── test_dou_ingest.py
├── test_image_checker.py
├── test_seal_roundtrip.py
└── test_search_adapters.py
```

## Backend Test Structure

**Suite Organization:**
- Functions named `test_<specific_behavior>()` — no class grouping
- Visual section dividers with `_section("Section Name")` that prints headers
- Tests grouped by category with comment block separators
- Manual test registration in `main()` function (list of function references)

```python
# Pattern from tests/test_dou_ingest.py
def test_sanitizer_no_op_for_clean_xml():
    """Clean XML should pass through unchanged."""
    _section("Sanitizer — no-op for clean XML")
    clean = '<xml>...</xml>'
    result, modified = _sanitize_xml(clean)
    _assert_eq(result, clean, "content unchanged")
    _assert_eq(modified, False, "not marked as modified")

def main() -> int:
    tests = [
        test_sanitizer_no_op_for_clean_xml,
        test_sanitizer_strips_leaked_identifica,
        # ... all test functions listed explicitly
    ]
    for test_fn in tests:
        try:
            test_fn()
        except Exception as ex:
            global _failed
            _failed += 1
            print(f"  EXCEPTION in {test_fn.__name__}: {ex}", file=sys.stderr)
    # ...
    return 0 if _failed == 0 else 1
```

**Exit Code Convention:**
- All test scripts return exit code 0 on success, 1 on any failure
- Entry point: `raise SystemExit(main())` or `sys.exit(1 if _failed else 0)`

## Mocking

**Backend Mocking Patterns:**

1. **Monkey-patching internal state** (for registry data):
```python
# tests/test_bulk_pipeline.py
def _inject_mock_registry():
    _zd._FOLDER_REGISTRY = {"2026-01": 685674076, ...}
    _zd._FILE_REGISTRY = {"2026-01": ["S01012026.zip", ...]}
```

2. **Method replacement on adapter instances** (for HTTP calls):
```python
# tests/test_search_adapters.py
adapter._request = fake_request  # type: ignore[attr-defined]
# or
adapter._lexical_candidates = lambda **kwargs: ([...], count)
adapter._vector_candidates = lambda **kwargs: [...]
```

3. **Fake client classes** (for async HTTP):
```python
# tests/test_image_checker.py
class FakeClient:
    def __init__(self, head_items, get_items=None):
        self.head_items = list(head_items)
        self.get_items = list(get_items or [])
    async def head(self, url, follow_redirects=False):
        item = self.head_items.pop(0)
        if isinstance(item, Exception): raise item
        return item
```

4. **Fabricated response objects** (for httpx):
```python
def _response(method, url, status_code, *, headers=None, content=b""):
    return httpx.Response(status_code, headers=headers, content=content,
                          request=httpx.Request(method, url))
```

**What to Mock:**
- External HTTP calls (Elasticsearch, remote image probes)
- Module-level registries and state (`_FOLDER_REGISTRY`, `_FILE_REGISTRY`)
- Adapter internal methods (`_request`, `_lexical_candidates`, `_vector_candidates`)
- Embedding model calls (`DummyEmbedder` with fixed vectors)

**What NOT to Mock:**
- Pure functions (serializers, parsers, normalizers) — test with real inputs
- XML parsing — use real fixture files from `tests/fixtures/xml_samples/`
- Hash computation — verify exact hex values

## Fixtures and Factories

**Test Data (Backend):**

1. **XML fixture files** — real DOU documents in `tests/fixtures/xml_samples/`:
```python
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "xml_samples"
articles = parse_directory(FIXTURES_DIR)
```

2. **Inline record dicts** for commitment tests:
```python
RECORD_A = {
    "event_type": "inserted",
    "natural_key_hash": "a" * 64,
    "strategy": "strict",
    "content_hash": "b" * 64,
    # ...
}
```

3. **Factory helper** for DOUArticle objects:
```python
def _make_article(**kwargs) -> DOUArticle:
    defaults = {
        "id": "1", "id_materia": "12345678", "pub_name": "DO1",
        "pub_date": "01/01/2026", "art_type": "Portaria", ...
    }
    defaults.update(kwargs)
    return DOUArticle(**defaults)
```

4. **Synthetic enriched JSON** for integration tests:
```python
def create_synthetic_enriched(out_dir: Path) -> None:
    docs = [{"file": "page1.html", "publication_issue": {...}, "documents": [...]}]
    for i, doc in enumerate(docs):
        fp = out_dir / f"enriched_{i:03d}.json"
        fp.write_text(json.dumps(doc, ensure_ascii=False))
```

## Async Testing

**Pattern (Backend only):**
```python
# tests/test_image_checker.py
async def test_available_status() -> None:
    client = FakeClient(head_items=[...], get_items=[...])
    out = await _probe_remote_image(client, "https://example.com/img.gif")
    _assert(out["status"] == "available", "...")

async def _run_async() -> None:
    await test_available_status()
    await test_missing_status()
    # ...

def main() -> int:
    asyncio.run(_run_async())
    # sync tests follow
    test_context_hint_and_fallback_text()
```

## Coverage

**Requirements:** None enforced — no coverage tooling configured

**Frontend:** No coverage configuration in `vitest.config.ts`

**Backend:** No coverage tooling (no pytest-cov, no coverage.py config)

## Test Types

**Unit Tests (Backend):**
- Pure function testing: serialization determinism, hash computation, NFC normalization
- XML parsing with real fixtures
- Field normalization (dates, sections, HTML stripping)
- Search query translation and filter inference
- Image classification and fallback logic
- All in `tests/test_bulk_pipeline.py`, `tests/test_commitment.py`, `tests/test_dou_ingest.py`, `tests/test_search_adapters.py`, `tests/test_image_checker.py`

**Integration Tests (Backend):**
- `tests/test_seal_roundtrip.py` — requires running PostgreSQL on port 5433
- Full pipeline: reset DB, create synthetic data, ingest, seal commitment, verify with hostile verifier
- Not runnable without infrastructure

**Unit Tests (Frontend):**
- Effectively none — only a trivial placeholder exists

**E2E Tests:**
- Not used — no Playwright, Cypress, or similar

## Path Setup Pattern

All backend test files manually add project root to `sys.path`:
```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```
This is required because tests are run as standalone scripts, not via pytest discovery.

## Common Anti-Patterns to Be Aware Of

1. **No test runner framework** — tests are standalone scripts with manual orchestration
2. **Global mutable state** for pass/fail counting — not thread-safe, not composable
3. **No test isolation** — mock registries injected at module level persist between tests
4. **Manual test registration** — new tests must be added to `main()` list or they won't run
5. **No CI integration detected** — tests must be run manually

## Guidance for Writing New Tests

**Backend:**
- Follow the existing custom harness pattern (use `_assert()` / `_assert_eq()` helpers)
- Add test function to the `main()` registration list
- Use `_section("Name")` for visual grouping in output
- For new modules, create `tests/test_<module>.py` following the same standalone script pattern
- Use real fixture XMLs from `tests/fixtures/xml_samples/` where possible
- Mock external calls by replacing instance methods (e.g., `adapter._request = fake_fn`)

**Frontend:**
- Use Vitest + Testing Library (already installed)
- Place tests as `src/frontend/web/src/**/*.test.tsx`
- Import from `vitest` and `@testing-library/react`
- The `matchMedia` mock is already configured in `src/frontend/web/src/test/setup.ts`

---

*Testing analysis: 2026-03-08*
