from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.backend.ingest.dou_processor import DouProcessor


FIXTURES = Path("ops/fixtures/reindex_v2_multipart")


def _build_fixture_zip() -> bytes:
    files = [
        FIXTURES / "2026-02-27-DO1E_600_20260227_23639293-1.xml",
        FIXTURES / "2026-02-27-DO1E_600_20260227_23639293-2.xml",
        FIXTURES / "2026-02-27-DO1E_600_20260227_23639224.xml",
    ]
    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                inner_name = path.name.split("_", 1)[1]
                archive.writestr(inner_name, path.read_bytes())
        return Path(tmp.name).read_bytes()


def main() -> None:
    processor = DouProcessor()
    docs = processor.process_zip(_build_fixture_zip(), "fixture_multipart.zip")

    assert len(docs) == 2, f"expected 2 logical docs, got {len(docs)}"

    docs_by_id = {doc.logical_doc_id: doc for doc in docs}
    assert "23639293" in docs_by_id, "missing merged multipart fixture"
    assert "23639224" in docs_by_id, "missing single-part fixture"

    merged = docs_by_id["23639293"]
    assert merged.is_multipart is True, "multipart fixture should merge"
    assert merged.part_count == 2, f"expected 2 parts, got {merged.part_count}"
    assert merged.merged_from_xml_paths == [
        "600_20260227_23639293-1.xml",
        "600_20260227_23639293-2.xml",
    ], merged.merged_from_xml_paths
    assert merged.content_html and "multipart-break" in merged.content_html, "missing multipart separator"
    assert merged.source_url and "data=27/02/2026" in merged.source_url, merged.source_url
    assert merged.source_url and "jornal=600" in merged.source_url, merged.source_url

    single = docs_by_id["23639224"]
    assert single.is_multipart is False, "single fixture should stay single"
    assert single.part_count == 1, f"expected 1 part, got {single.part_count}"

    print("ok: multipart fixture merged and source_url preserved")


if __name__ == "__main__":
    main()
