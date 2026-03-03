"""Tests for the bulk ingestion pipeline.

Covers:
  - XML parsing from fixtures
  - Field normalization (DOUArticle → ingest record)
  - ZIP extraction (using fixtures)
  - URL generation
  - Identity hash computation

Run:
    python tests/test_bulk_pipeline.py
"""
from __future__ import annotations

import sys
import tempfile
import zipfile
from datetime import date
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.date_selector import DateRange
from ingest.normalizer import (
    article_to_ingest_record,
    normalize_article,
    normalize_pub_date,
    normalize_section,
    strip_html,
    _compute_natural_key_hash,
    _extract_doc_number,
    _extract_issuing_organ,
)
from ingest.xml_parser import DOUArticle, INLabsXMLParser, parse_directory
from ingest.zip_downloader import (
    ALL_SECTIONS,
    ZIPTarget,
    build_targets,
    build_zip_url,
    extract_xml_from_zip,
    file_sha256,
)
import ingest.zip_downloader as _zd

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "xml_samples"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_passed = 0
_failed = 0


def _assert(condition: bool, msg: str) -> None:
    global _passed, _failed
    if condition:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}", file=sys.stderr)


def _section(name: str) -> None:
    print(f"\n--- {name} ---")


# ---------------------------------------------------------------------------
# XML Parser tests
# ---------------------------------------------------------------------------

def test_parse_fixtures():
    _section("XML Parser — fixture parsing")

    articles = parse_directory(FIXTURES_DIR)
    _assert(len(articles) > 0, f"expected >0 articles, got {len(articles)}")
    print(f"  parsed {len(articles)} articles from fixtures")

    # Check known fixture: DO1 article
    do1_arts = [a for a in articles if a.pub_name == "DO1"]
    _assert(len(do1_arts) >= 1, f"expected >=1 DO1 articles, got {len(do1_arts)}")

    # Check known fixture: DO1E extra edition
    do1e_arts = [a for a in articles if a.pub_name == "DO1E"]
    _assert(len(do1e_arts) >= 1, f"expected >=1 DO1E articles, got {len(do1e_arts)}")

    # Verify basic fields
    for art in articles:
        _assert(art.pub_name != "", f"pub_name empty for {art.id}")
        _assert(art.pub_date != "", f"pub_date empty for {art.id}")
        _assert(art.art_category != "", f"art_category empty for {art.id}")


def test_parse_string():
    _section("XML Parser — parse_string")

    xml = """<xml><article id="12345" idMateria="99887766" idOficio="111"
        name="Test" pubName="DO1" pubDate="27/02/2026" editionNumber="39"
        numberPage="5" pdfPage="" artType="Portaria" artCategory="Órgão/Sub"
        artClass="" artSize="12" artNotes="" highlightType="" highlightPriority=""
        highlight="" highlightimage="" highlightimagename="">
      <body>
        <Identifica><![CDATA[ PORTARIA Nº 123, DE 26 DE FEVEREIRO DE 2026 ]]></Identifica>
        <Data><![CDATA[]]></Data>
        <Ementa><![CDATA[ Ementa de teste ]]></Ementa>
        <Titulo />
        <SubTitulo />
        <Texto><![CDATA[<p>Corpo do ato.</p>]]></Texto>
      </body>
    </article></xml>"""

    parser = INLabsXMLParser()
    art = parser.parse_string(xml)

    _assert(art.id == "12345", f"id={art.id}")
    _assert(art.id_materia == "99887766", f"id_materia={art.id_materia}")
    _assert(art.pub_name == "DO1", f"pub_name={art.pub_name}")
    _assert(art.art_type == "Portaria", f"art_type={art.art_type}")
    _assert("PORTARIA" in art.identifica, f"identifica={art.identifica}")
    _assert("Corpo do ato" in art.texto, f"texto={art.texto[:50]}")


def test_extra_edition_detection():
    _section("XML Parser — extra edition detection")

    do1e_arts = [a for a in parse_directory(FIXTURES_DIR) if a.pub_name == "DO1E"]
    if do1e_arts:
        art = do1e_arts[0]
        _assert(art.pub_name == "DO1E", f"pub_name should be DO1E, got {art.pub_name}")
    else:
        print("  SKIP: no DO1E fixtures available")


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

def test_normalize_pub_date():
    _section("Normalizer — pub_date")

    _assert(normalize_pub_date("27/02/2026") == date(2026, 2, 27), "DD/MM/YYYY")
    _assert(normalize_pub_date("01/01/2020") == date(2020, 1, 1), "start of year")
    _assert(normalize_pub_date("") is None, "empty string")
    _assert(normalize_pub_date("invalid") is None, "invalid format")
    _assert(normalize_pub_date("2026-02-27") is None, "ISO format not accepted")


def test_normalize_section():
    _section("Normalizer — section")

    _assert(normalize_section("DO1") == "do1", "DO1")
    _assert(normalize_section("DO1E") == "do1e", "DO1E")
    _assert(normalize_section("DO2") == "do2", "DO2")
    _assert(normalize_section("DO3E") == "do3e", "DO3E")


def test_strip_html():
    _section("Normalizer — strip_html")

    _assert(strip_html("<p>Hello</p>") == "Hello", "simple tag")
    _assert(strip_html('<p class="x">A</p><p>B</p>') == "AB", "multiple tags")
    _assert(strip_html("") == "", "empty")
    _assert(strip_html("no tags") == "no tags", "no tags")


def test_extract_doc_number():
    _section("Normalizer — extract_doc_number")

    _assert(
        _extract_doc_number("PORTARIA Nº 123, DE 26 DE FEVEREIRO DE 2026", "Portaria") == "123",
        "standard Portaria",
    )
    _assert(
        _extract_doc_number("RESOLUÇÃO N° 456/2026", "Resolução") == "456/2026",
        "resolution with slash",
    )
    _assert(_extract_doc_number("ACÓRDÃO", "Acórdão") == "", "no number")
    _assert(_extract_doc_number("", "") == "", "empty")


def test_extract_issuing_organ():
    _section("Normalizer — extract_issuing_organ")

    _assert(
        _extract_issuing_organ("Entidades de Fiscalização/CONSELHO REGIONAL") == "CONSELHO REGIONAL",
        "category path",
    )
    _assert(_extract_issuing_organ("") == "", "empty")
    _assert(_extract_issuing_organ("SingleOrg") == "SingleOrg", "single element")


def test_article_to_ingest_record():
    _section("Normalizer — article_to_ingest_record")

    articles = parse_directory(FIXTURES_DIR)
    if not articles:
        print("  SKIP: no fixtures")
        return

    art = articles[0]
    rec = article_to_ingest_record(art, zip_sha256="abc123", source_file="test.xml")

    # All required fields must be present
    required_fields = [
        "occurrence_hash", "edition_id", "publication_date",
        "edition_number", "edition_section", "listing_sha256",
        "natural_key_hash", "strategy", "content_hash",
        "body_text_semantic", "page_number", "source_url", "source_file",
    ]
    for f in required_fields:
        _assert(f in rec, f"missing field: {f}")

    # Hashes must be 64-char hex strings (SHA-256)
    for hash_field in ["occurrence_hash", "edition_id", "natural_key_hash", "content_hash"]:
        val = rec[hash_field]
        _assert(len(val) == 64 and all(c in "0123456789abcdef" for c in val),
                f"{hash_field} should be sha256 hex, got {val[:20]}...")

    _assert(rec["source_file"] == "test.xml", f"source_file={rec['source_file']}")
    _assert(rec["listing_sha256"] == "abc123", f"listing_sha256={rec['listing_sha256']}")
    _assert(rec["strategy"] in ("strict", "medium", "weak", "fallback", "none"),
            f"strategy={rec['strategy']}")


def test_normalize_article():
    _section("Normalizer — normalize_article (legacy)")

    articles = parse_directory(FIXTURES_DIR)
    if not articles:
        print("  SKIP: no fixtures")
        return

    norm = normalize_article(articles[0])
    _assert("section" in norm, "has section")
    _assert("pub_date" in norm, "has pub_date")
    _assert("texto_plain" in norm, "has texto_plain")
    _assert("texto_html" in norm, "has texto_html")


# ---------------------------------------------------------------------------
# ZIP downloader tests
# ---------------------------------------------------------------------------

def _inject_mock_registry():
    """Inject a mock folderId + file registry for testing URL generation."""
    _zd._FOLDER_REGISTRY = {
        "2026-01": 685674076,
        "2026-02": 999999999,
        "2026-03": 999999998,
    }
    _zd._FILE_REGISTRY = {
        "2026-01": ["S01012026.zip", "S02012026.zip", "S03012026.zip"],
        "2026-02": ["S01022026.zip", "S02022026.zip", "S03022026.zip"],
        "2026-03": ["S01032026.zip", "S02032026.zip", "S03032026.zip"],
    }


def test_build_zip_url():
    _section("Downloader — build_zip_url")
    _inject_mock_registry()

    # Monthly archive: S{prefix}{MMYYYY}.zip
    t = build_zip_url("do1", date(2026, 1, 15))  # any day in Jan 2026
    _assert(t is not None, "build_zip_url returned None")
    _assert(t.url.endswith("S01012026.zip"), f"url={t.url}")
    _assert("/685674076/" in t.url, f"folderId in url: {t.url}")
    _assert(t.filename == "S01012026.zip", f"filename={t.filename}")
    _assert(t.local_filename == "2026-01_DO1.zip", f"local={t.local_filename}")
    _assert(t.section == "do1", f"section={t.section}")
    _assert(t.pub_date == date(2026, 1, 1), f"pub_date normalized to 1st: {t.pub_date}")

    # Extra edition
    t2 = build_zip_url("do1e", date(2026, 2, 27))
    _assert(t2 is not None, "extra edition returned None")
    _assert(t2.url.endswith("S01E022026.zip"), f"url={t2.url}")
    _assert(t2.local_filename == "2026-02_DO1E.zip", f"local={t2.local_filename}")

    # Section 2, March
    t3 = build_zip_url("do2", date(2026, 3, 1))
    _assert(t3 is not None, "march returned None")
    _assert(t3.url.endswith("S02032026.zip"), f"url={t3.url}")

    # Missing month → None
    t4 = build_zip_url("do1", date(2030, 6, 1))
    _assert(t4 is None, f"unknown month should return None, got {t4}")


def test_build_targets():
    _section("Downloader — build_targets (deduplicates by month)")
    _inject_mock_registry()

    # 3 days in same month → should deduplicate to 1 month × N sections
    dr = DateRange(date(2026, 2, 25), date(2026, 2, 27))
    targets = build_targets(dr, sections=["do1", "do2", "do3"], include_extras=False)

    _assert(len(targets) == 3, f"expected 3 targets (1 month × 3 sections), got {len(targets)}")
    dates = {t.pub_date for t in targets}
    _assert(len(dates) == 1, f"expected 1 unique month date, got {len(dates)}")
    _assert(dates == {date(2026, 2, 1)}, f"expected Feb 1, got {dates}")

    # Spanning 2 months → 2 months × 3 sections = 6
    dr2 = DateRange(date(2026, 1, 28), date(2026, 2, 5))
    targets2 = build_targets(dr2, sections=["do1", "do2", "do3"], include_extras=False)
    _assert(len(targets2) == 6, f"expected 6 targets (2 months × 3), got {len(targets2)}")


def test_all_sections_mapped():
    _section("Downloader — all sections mapped")
    _inject_mock_registry()

    for section in ALL_SECTIONS:
        try:
            t = build_zip_url(section, date(2026, 1, 1))
            _assert(t is not None and t.url != "", f"{section} should produce a URL")
        except ValueError:
            _assert(False, f"{section} raised ValueError")


def test_split_parte_files():
    _section("Downloader — split _Parte files in registry")

    # Simulate a month with S01 split into parts (like 2025-12)
    _zd._FOLDER_REGISTRY = {"2025-12": 679321324}
    _zd._FILE_REGISTRY = {
        "2025-12": [
            "S01122025_Parte1.zip", "S01122025_Parte2.zip", "S01122025_Parte3.zip",
            "S02122025.zip", "S03122025.zip",
        ],
    }

    dr = DateRange(date(2025, 12, 1), date(2025, 12, 31))
    targets = build_targets(dr, sections=["do1", "do2", "do3"], include_extras=False)

    # Should get 5 targets: 3 parts for do1 + 1 do2 + 1 do3
    _assert(len(targets) == 5, f"expected 5 targets (3 parts + 2 regular), got {len(targets)}")

    do1_targets = [t for t in targets if t.section == "do1"]
    _assert(len(do1_targets) == 3, f"expected 3 do1 targets (parts), got {len(do1_targets)}")
    _assert(all("_Parte" in t.filename for t in do1_targets), "all do1 targets should have _Parte in filename")
    _assert(all("_Parte" in t.local_filename for t in do1_targets), "local names should have _Parte")

    do2_targets = [t for t in targets if t.section == "do2"]
    _assert(len(do2_targets) == 1, f"expected 1 do2 target, got {len(do2_targets)}")
    _assert(do2_targets[0].filename == "S02122025.zip", f"do2 filename={do2_targets[0].filename}")

    # Restore mock registry
    _inject_mock_registry()


# ---------------------------------------------------------------------------
# ZIP extraction tests
# ---------------------------------------------------------------------------

def test_extract_xml_from_zip():
    _section("Downloader — extract_xml_from_zip")

    # Create a temporary ZIP with sample XML
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        zip_path = tmpdir / "test.zip"
        xml_content = b'<xml><article id="1" pubName="DO1" pubDate="01/01/2026"'
        xml_content += b' idMateria="12345678" idOficio="0" name="Test" artType="Portaria"'
        xml_content += b' artCategory="Org" artClass="" artSize="12" artNotes=""'
        xml_content += b' numberPage="1" pdfPage="" editionNumber="1"'
        xml_content += b' highlightType="" highlightPriority="" highlight=""'
        xml_content += b' highlightimage="" highlightimagename="">'
        xml_content += b'<body><Identifica>T</Identifica><Data/><Ementa/>'
        xml_content += b'<Titulo/><SubTitulo/><Texto>body</Texto></body></article></xml>'

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("article_001.xml", xml_content)
            zf.writestr("image_001.png", b"fake image data")
            zf.writestr("subdir/article_002.xml", xml_content)

        result = extract_xml_from_zip(zip_path, output_dir=tmpdir / "extracted")

        _assert(len(result.xml_files) == 2, f"expected 2 xml files, got {len(result.xml_files)}")
        _assert(len(result.image_files) == 1, f"expected 1 image file, got {len(result.image_files)}")
        _assert(len(result.errors) == 0, f"expected 0 errors, got {len(result.errors)}")

        # Verify XML is parseable
        parser = INLabsXMLParser()
        for xml_file in result.xml_files:
            art = parser.parse_file(xml_file)
            _assert(art.pub_name == "DO1", f"parsed pub_name={art.pub_name}")


def test_file_sha256():
    _section("Downloader — file_sha256")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
        f.write(b"test content")
        f.flush()
        path = Path(f.name)

    try:
        sha = file_sha256(path)
        _assert(len(sha) == 64, f"sha256 length={len(sha)}")
        _assert(sha == "6ae8a75555209fd6c44157c0aed8016e763ff435a19cf186f76863140143ff72",
                f"sha256 mismatch: {sha}")
    finally:
        path.unlink()


# ---------------------------------------------------------------------------
# Natural key hash determinism
# ---------------------------------------------------------------------------

def test_natural_key_determinism():
    _section("Normalizer — natural key hash determinism")

    articles = parse_directory(FIXTURES_DIR)
    if len(articles) < 2:
        print("  SKIP: need >=2 fixtures")
        return

    # Same article should produce same hash
    rec1 = article_to_ingest_record(articles[0])
    rec2 = article_to_ingest_record(articles[0])

    _assert(rec1["natural_key_hash"] == rec2["natural_key_hash"],
            "same article should produce same natural_key_hash")
    _assert(rec1["content_hash"] == rec2["content_hash"],
            "same article should produce same content_hash")
    _assert(rec1["occurrence_hash"] == rec2["occurrence_hash"],
            "same article should produce same occurrence_hash")

    # Different articles should produce different hashes (with very high probability)
    rec3 = article_to_ingest_record(articles[1])
    _assert(rec1["occurrence_hash"] != rec3["occurrence_hash"],
            "different articles should produce different occurrence_hash")


# ---------------------------------------------------------------------------
# Date selector integration
# ---------------------------------------------------------------------------

def test_date_range_integration():
    _section("DateRange — integration with build_targets")

    dr = DateRange(date(2026, 1, 1), date(2026, 1, 3))
    _assert(len(dr) == 3, f"expected 3 days, got {len(dr)}")
    _assert(len(dr.dates()) == 3, f"expected 3 dates, got {len(dr.dates())}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    global _passed, _failed

    print("=" * 60)
    print("BULK PIPELINE TESTS")
    print("=" * 60)

    test_parse_fixtures()
    test_parse_string()
    test_extra_edition_detection()
    test_normalize_pub_date()
    test_normalize_section()
    test_strip_html()
    test_extract_doc_number()
    test_extract_issuing_organ()
    test_article_to_ingest_record()
    test_normalize_article()
    test_build_zip_url()
    test_build_targets()
    test_all_sections_mapped()
    test_split_parte_files()
    test_extract_xml_from_zip()
    test_file_sha256()
    test_natural_key_determinism()
    test_date_range_integration()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}")

    return 1 if _failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
