# Testing Patterns

**Analysis Date:** 2026-03-11

## Test Framework

**Runner:**
- unittest (Python standard library)
- No formal test framework configuration (no pytest.ini, conftest.py, etc.)

**Assertion Library:**
- unittest assertions: `assertEqual`, `assertIsNotNone`, `assertTrue`, `assertIn`

**Run Commands:**
```bash
python ops/test_mongo_connection.py    # Test MongoDB connection
python ops/test_extraction.py          # Test XML extraction
python .dev/mcp/test_system.py         # Test MCP system (self-test)
python .dev/bench/run_benchmark.py     # Run search benchmarks
```

## Test File Organization

**Location:**
- Ad-hoc tests: `ops/test_*.py` (co-located with operational scripts)
- Development tests: `.dev/mcp/test_system.py`, `.dev/bench/`

**Naming:**
- `test_<feature>.py` pattern
- Examples: `test_mongo_connection.py`, `test_extraction.py`

**Structure:**
```
ops/
  test_mongo_connection.py    # Connection test
  test_extraction.py          # XML processing test
  test_icloud_json.py         # iCloud JSON test

.dev/
  mcp/test_system.py          # MCP convergence engine self-test
  bench/
    run_benchmark.py          # Search benchmark runner
    cases.py                  # Benchmark test cases
    grader.py                 # Result grading
    judge.py                  # LLM-based judging
```

## Test Structure

**Suite Organization:**
```python
import unittest
from datetime import datetime

# Add src to path
sys.path.append(os.path.join(os.getcwd()))

from src.backend.ingest.dou_processor import DouProcessor

class TestDouProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = DouProcessor()
        self.mock_xml = """<?xml version="1.0" encoding="utf-8"?>
<xml>
<article pubName="DO1" pubDate="04/01/2002" artType="DECRETO">
    <body>
        <Identifica>DECRETO Nº 4.071</Identifica>
        <Ementa>Dispõe sobre...</Ementa>
        <Texto>...</Texto>
    </body>
</article>
</xml>
""".encode('utf-8')

    def test_extraction(self):
        doc = self.processor.process_xml(self.mock_xml, "test.xml", "test.zip")
        self.assertIsNotNone(doc)
        
        # Deterministic ID
        self.assertTrue(doc.id.startswith("2002-01-04_DO1_"))
        
        # Source Type
        self.assertEqual(doc.source_type, "liferay")
        
        # References
        targets = [ref.target for ref in doc.references]
        self.assertIn("Decreto 3.035", targets)

if __name__ == '__main__':
    unittest.main()
```

**Patterns:**
- `setUp()` for test fixtures
- Descriptive test method names: `test_extraction`, `test_mongo_connection`
- Print statements for debugging visibility
- Exit codes for CI/CD integration: `sys.exit(1)` on failure

## Mocking

**Framework:**
- No formal mocking framework (no unittest.mock patterns detected)
- Manual test doubles for complex scenarios

**Manual Mocking Pattern:**
```python
# From .dev/mcp/test_system.py
class FakeAdapter:
    def __init__(self, name: str) -> None:
        self.name = name

    def complete(self, messages, *, enable_thinking: bool, stream: bool):
        if "Return exactly one JSON object" in messages[-1]["content"]:
            if self.name == "claude":
                content = json.dumps({
                    "verdict": "REQUEST_CHANGES",
                    "objections": [...],
                })
            else:
                content = json.dumps({
                    "verdict": "APPROVE",
                    "objections": [],
                })
            return ProviderResponse(content=content, usage=UsageStats(total_tokens=12))
        return ProviderResponse(content="def total():\n    return 1\n", usage=UsageStats(total_tokens=7))

# Patch by replacing in globals
original_factory = engine._dispatch_reviews.__globals__["create_adapter"]
engine._dispatch_reviews.__globals__["create_adapter"] = lambda provider, agent: FakeAdapter(agent.name)
try:
    run = engine.run(...)
finally:
    engine._dispatch_reviews.__globals__["create_adapter"] = original_factory
```

**What to Mock:**
- External API calls (HTTP requests)
- Database connections (for unit tests)
- LLM provider responses

**What NOT to Mock:**
- Data transformation logic
- Parsing functions
- Business logic validation

## Fixtures and Factories

**Test Data:**
- Inline XML/JSON strings in test methods
- Hardcoded test data for specific scenarios

**Example:**
```python
self.mock_xml = """<?xml version="1.0" encoding="utf-8"?>
<xml>
<article pubName="DO1" pubDate="04/01/2002" artType="DECRETO" 
         artCategory="Atos do Poder Executivo/Presidência da República" numberPage="1">
    <body>
        <Identifica>DECRETO Nº 4.071</Identifica>
        <Ementa>Dispõe sobre...</Ementa>
        <Texto>
            &lt;p class='identifica'&gt;DECRETO Nº 4.071&lt;/p&gt;
            &lt;p&gt;O PRESIDENTE DA REPÚBLICA...&lt;/p&gt;
        </Texto>
    </body>
</article>
</xml>
""".encode('utf-8')
```

**Location:**
- Test data defined inline within test classes
- No separate fixture files

## Coverage

**Requirements:** None enforced

**Coverage Tools:** Not configured

**Manual Coverage:**
- Tests focus on critical paths
- Connection tests verify infrastructure
- Processing tests verify extraction logic

## Test Types

**Unit Tests:**
- Located in `ops/test_*.py`
- Test individual functions and classes
- Example: `test_extraction.py` tests `DouProcessor.process_xml()`

**Integration Tests:**
- `ops/test_mongo_connection.py` - database connectivity
- `.dev/bench/run_benchmark.py` - end-to-end search benchmarks

**E2E Tests:**
- `.dev/mcp/test_system.py` - full convergence engine workflow
- Benchmark runner with grading and LLM judging

**Performance/Benchmark Tests:**
```python
# From .dev/bench/run_benchmark.py
def main() -> None:
    cases = build_cases()
    adapters = {backend: _adapter_for_backend(base_cfg, backend) for backend in backends}
    
    for case in cases:
        for backend, adapter in adapters.items():
            response = adapter.search(query=query, page_size=args.page_size, page=1, ...)
            rows = hydrator.hydrate(response.get("results") or [])
            grade = grade_case(case, rows, top_k=args.top_k)
```

## Common Patterns

**Async Testing:**
```python
# MCP server uses async
@mcp.tool()
async def search_dou(query: str, limit: int = 5) -> List[SearchResult]:
    # Implementation
```

**Error Testing:**
```python
def test_mongo_connection():
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        print("Successfully connected to MongoDB server.")
    except ConnectionFailure:
        print("Server not available.")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)
```

**Assertion Patterns:**
```python
# Basic assertions
self.assertIsNotNone(doc)
self.assertEqual(doc.source_type, "liferay")
self.assertTrue(doc.id.startswith("2002-01-04_DO1_"))

# Collection assertions
self.assertIn("Decreto 3.035", targets)

# Debug output
print(f"References: {doc.references}")
print(f"Entities: {doc.affected_entities}")
```

## Benchmark Testing

**Framework:**
- Custom benchmark framework in `.dev/bench/`
- Grading based on precision/recall metrics

**Components:**
- `cases.py` - Test case definitions
- `grader.py` - Result grading with P@1, P@3, Hits@10, MRR
- `judge.py` - LLM-based result judging
- `reporting.py` - Markdown and JSON output

**Running Benchmarks:**
```bash
python .dev/bench/run_benchmark.py --backends hybrid,pg --limit 10
python .dev/bench/run_benchmark.py --category legal_reference
python .dev/bench/run_benchmark.py --llm-judge-agent claude --judge-sample 5
```

**Metrics:**
```python
aggregates = {
    "p_at_1": 0.85,
    "p_at_3": 0.72,
    "hits_at_10": 0.90,
    "mrr": 0.78
}
```

## Test Data Management

**Snapshot Testing:**
- Benchmark results written to `.dev/mcp/runs/<timestamp>/`
- JSON and Markdown summaries preserved

**Example Output:**
```
.dev/mcp/runs/
  20260309T132145Z-dou-autonomous-spec/
    round-1/
      reviews/
    round-2/
      reviews/
```

---

*Testing analysis: 2026-03-11*
