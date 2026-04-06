from __future__ import annotations

from src.backend.parsing.h2_llm import _extract_json_block


def test_extract_json_block_from_fenced_output() -> None:
    payload = """```json
{"summary_short":"ok","topics":["a"]}
```"""
    out = _extract_json_block(payload)
    assert out["summary_short"] == "ok"


def test_extract_json_block_from_wrapped_text() -> None:
    payload = 'Resposta:\\n{"summary_short":"ok","topics":["a"]}\\nFIM'
    out = _extract_json_block(payload)
    assert out["topics"] == ["a"]

