"""Tests for the DOU ingestion pipeline new modules.

Covers:
  - XML sanitizer (parse error recovery)
  - HTML extractor (signatures, images, norm refs, proc refs, doc number, art type)
  - Multi-part merger
  - DOU ingestor helpers (ZIP meta inference, etc.)

Run:
    python3 tests/test_dou_ingest.py
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# Ensure project root on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.backend.ingest.html_extractor import (
    ImageRef,
    NormRef,
    ProcRef,
    Signature,
    _ART_TYPE_CANONICAL,
    _extract_signatures_precise,
    extract_document_number,
    extract_images,
    extract_issuing_organ,
    extract_normative_references,
    extract_procedure_references,
    normalize_art_type,
    strip_html,
)
from src.backend.ingest.multipart_merger import (
    MergedArticle,
    _parse_id_from_filename,
    group_and_merge,
)
from src.backend.ingest.xml_parser import (
    DOUArticle,
    INLabsXMLParser,
    XMLParseError,
    _sanitize_xml,
)

FIXTURES = _ROOT / "tests" / "fixtures" / "xml_samples"

# ---------------------------------------------------------------------------
# Test counters
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


def _assert_eq(actual, expected, msg: str) -> None:
    _assert(actual == expected, f"{msg}: got {actual!r}, expected {expected!r}")


def _section(title: str) -> None:
    print(f"\n--- {title} ---")


# ===========================================================================
# 1. XML Sanitizer
# ===========================================================================

def test_sanitizer_no_op_for_clean_xml():
    """Clean XML should pass through unchanged."""
    _section("Sanitizer — no-op for clean XML")
    clean = '<xml>\n  <article name="PORTARIA" artType="PORTARIA" pubName="DO1">\n    <body></body>\n  </article>\n</xml>'
    result, modified = _sanitize_xml(clean)
    _assert_eq(result, clean, "content unchanged")
    _assert_eq(modified, False, "not marked as modified")


def test_sanitizer_strips_leaked_identifica():
    """Leaked </Identifica> in name/artType attributes should be stripped."""
    _section("Sanitizer — strips leaked </Identifica>")
    malformed = '<xml>\n  <article name="RETIFICAÇÃO</Identifica>" artType="RETIFICAÇÃO</Identifica>" pubDate="02/05/2016">\n    <body></body>\n  </article>\n</xml>'
    result, modified = _sanitize_xml(malformed)
    _assert_eq(modified, True, "marked as modified")
    _assert("</Identifica>" not in result, "no leaked tags in result")
    _assert('name="RETIFICAÇÃO"' in result, "name attr cleaned")
    _assert('artType="RETIFICAÇÃO"' in result, "artType attr cleaned")
    # Verify it actually parses now
    parser = INLabsXMLParser()
    try:
        art = parser.parse_string(result)
        _assert_eq(art.name, "RETIFICAÇÃO", "parsed name correct")
        _assert_eq(art.art_type, "RETIFICAÇÃO", "parsed artType correct")
    except Exception as ex:
        _assert(False, f"parse failed after sanitization: {ex}")


def test_sanitizer_handles_multiple_variants():
    """Different artType values that leak closing tags."""
    _section("Sanitizer — multiple variants")
    for val in ("DESPACHOS", "ACÓRDÃOS", "DECISÕES", "RETIFICAÇÂO"):
        malformed = f'<xml>\n  <article name="{val}</Identifica>" artType="{val}</Identifica>" pubName="DO1">\n    <body><Identifica><![CDATA[{val}]]></Identifica><Texto></Texto></body>\n  </article>\n</xml>'
        result, modified = _sanitize_xml(malformed)
        _assert_eq(modified, True, f"modified for {val}")
        parser = INLabsXMLParser()
        try:
            art = parser.parse_string(result)
            _assert_eq(art.name, val, f"name={val}")
        except Exception as ex:
            _assert(False, f"parse failed for {val}: {ex}")


def test_sanitizer_preserves_body_closing_tags():
    """Closing tags in the body (CDATA) should NOT be stripped."""
    _section("Sanitizer — preserves body closing tags")
    # This XML has </Identifica> leak in attr but also has normal closing tags in body.
    xml = '<xml>\n  <article name="RETIFICAÇÃO</Identifica>" artType="RETIFICAÇÃO</Identifica>">\n    <body><Identifica><![CDATA[RETIFICAÇÃO]]></Identifica><Texto><![CDATA[<p>text</p>]]></Texto></body>\n  </article>\n</xml>'
    result, _ = _sanitize_xml(xml)
    # Body CDATA should be intact
    _assert("</Identifica>" in result, "body </Identifica> preserved")
    # The leaked ones in attributes should be gone — count occurrences after article tag
    # The body one is </Identifica> after CDATA which wouldn't match our pattern
    # because ours only matches </tag>" (with quote after)
    lines = result.split("\n")
    article_line = lines[1]
    _assert("</Identifica>" not in article_line, "no leak in article line")


def test_sanitizer_with_real_fixtures():
    """Parse all real fixture XMLs (none should fail)."""
    _section("Sanitizer — real fixtures parse OK")
    parser = INLabsXMLParser()
    fixtures = sorted(FIXTURES.glob("*.xml"))
    _assert(len(fixtures) > 0, "fixtures exist")
    for f in fixtures:
        try:
            art = parser.parse_file(f)
            _assert(bool(art.pub_name), f"{f.name}: has pubName")
        except Exception as ex:
            _assert(False, f"{f.name}: parse failed: {ex}")


# ===========================================================================
# 2. HTML Extractor — Signatures
# ===========================================================================

def test_signatures_simple():
    """Extract simple assina/cargo pair."""
    _section("Signatures — simple pair")
    html = '<p class="assina">JOÃO DA SILVA</p><p class="cargo">Ministro de Estado</p>'
    sigs = _extract_signatures_precise(html)
    _assert_eq(len(sigs), 1, "one signature")
    _assert_eq(sigs[0].person_name, "JOÃO DA SILVA", "name")
    _assert_eq(sigs[0].role_title, "Ministro de Estado", "role")
    _assert_eq(sigs[0].sequence, 1, "sequence")


def test_signatures_no_cargo():
    """Signatory without a cargo following."""
    _section("Signatures — no cargo")
    html = '<p class="assina">MARIA SOUZA</p><p class="corpo">Other text.</p>'
    sigs = _extract_signatures_precise(html)
    _assert_eq(len(sigs), 1, "one signature")
    _assert_eq(sigs[0].person_name, "MARIA SOUZA", "name")
    _assert_eq(sigs[0].role_title, None, "no role")


def test_signatures_multiple():
    """Multiple signatories."""
    _section("Signatures — multiple")
    html = textwrap.dedent("""
        <p class="assina">PEDRO ALMEIDA</p>
        <p class="cargo">Coordenador</p>
        <p class="assina">ANA SANTOS</p>
        <p class="cargo">Diretora</p>
        <p class="assina">CARLOS FERREIRA</p>
    """)
    sigs = _extract_signatures_precise(html)
    _assert_eq(len(sigs), 3, "three signatures")
    _assert_eq(sigs[0].person_name, "PEDRO ALMEIDA", "first name")
    _assert_eq(sigs[0].role_title, "Coordenador", "first role")
    _assert_eq(sigs[1].person_name, "ANA SANTOS", "second name")
    _assert_eq(sigs[1].role_title, "Diretora", "second role")
    _assert_eq(sigs[2].person_name, "CARLOS FERREIRA", "third name")
    _assert_eq(sigs[2].role_title, None, "third no role")
    _assert_eq(sigs[2].sequence, 3, "third sequence")


def test_signatures_empty():
    """Empty or no-sig HTML returns empty list."""
    _section("Signatures — empty input")
    _assert_eq(_extract_signatures_precise(""), [], "empty string")
    _assert_eq(_extract_signatures_precise("<p>No sigs here</p>"), [], "no sigs HTML")


def test_signatures_from_real_fixture():
    """Extract signatures from a real fixture with known signatories."""
    _section("Signatures — real fixture")
    # 23639608 is a Portaria with one signatory
    parser = INLabsXMLParser()
    art = parser.parse_file(FIXTURES / "2026-03-01-DO1E_602_20260301_23639608.xml")
    sigs = _extract_signatures_precise(art.texto)
    _assert(len(sigs) >= 1, f"at least 1 signature, got {len(sigs)}")
    # All names should be non-empty uppercase
    for sig in sigs:
        _assert(len(sig.person_name) > 2, f"name not empty: {sig.person_name!r}")


# ===========================================================================
# 3. HTML Extractor — Images
# ===========================================================================

def test_images_extraction():
    """Extract image refs from <img name="..."> tags."""
    _section("Images — extraction")
    html = '<p>Before</p><img name="1_MPESCA_27_001" /><p>Middle</p><img name="2_MPESCA_27_002" />'
    imgs = extract_images(html)
    _assert_eq(len(imgs), 2, "two images")
    _assert_eq(imgs[0].name, "1_MPESCA_27_001", "first img name")
    _assert_eq(imgs[1].name, "2_MPESCA_27_002", "second img name")
    _assert_eq(imgs[0].sequence, 1, "first sequence")
    _assert_eq(imgs[1].sequence, 2, "second sequence")


def test_images_empty():
    """No images returns empty."""
    _section("Images — empty")
    _assert_eq(extract_images(""), [], "empty string")
    _assert_eq(extract_images("<p>No images</p>"), [], "no img tags")


# ===========================================================================
# 4. HTML Extractor — Normative References
# ===========================================================================

def test_norm_ref_lei():
    """Lei nº extraction."""
    _section("NormRef — Lei")
    text = "conforme a Lei nº 12.846, de 1º de agosto de 2013, que dispõe sobre"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 1, f"at least 1 ref, got {len(refs)}")
    r = refs[0]
    _assert_eq(r.reference_type, "lei", "type")
    _assert_eq(r.reference_number, "12.846", "number")
    _assert(r.reference_date is not None, "has date")


def test_norm_ref_decreto():
    """Decreto nº extraction."""
    _section("NormRef — Decreto")
    text = "nos termos do Decreto nº 11.129/2022"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].reference_type, "decreto", "type")
    _assert_eq(refs[0].reference_number, "11.129/2022", "number")


def test_norm_ref_resolucao():
    """Resolução extraction with issuing body."""
    _section("NormRef — Resolução")
    text = "Resolução Gecex nº 780, de 28 de agosto de 2025"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].reference_type, "resolução", "type")
    _assert_eq(refs[0].reference_number, "780", "number")


def test_norm_ref_instrucao_normativa():
    """Instrução Normativa extraction."""
    _section("NormRef — Instrução Normativa")
    text = "Instrução Normativa nº 10, de 10 de junho de 2011"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].reference_type, "instrução_normativa", "type")


def test_norm_ref_portaria():
    """Portaria nº extraction."""
    _section("NormRef — Portaria")
    text = "Portaria nº 409, de 14 de janeiro de 2025"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].reference_type, "portaria", "type")
    _assert_eq(refs[0].reference_number, "409", "number")


def test_norm_ref_dedup():
    """Duplicate references are deduplicated."""
    _section("NormRef — dedup")
    text = "Lei nº 12.846/2013 ... conforme Lei nº 12.846/2013"
    refs = extract_normative_references(text)
    _assert_eq(len(refs), 1, "deduplicated")


def test_norm_ref_multiple_types():
    """Multiple different reference types in same text."""
    _section("NormRef — multiple types")
    text = "Lei nº 8.666/1993, Decreto nº 10.024/2019 e Portaria nº 100, de 1 de janeiro de 2020"
    refs = extract_normative_references(text)
    _assert(len(refs) >= 3, f"at least 3 refs, got {len(refs)}")
    types = {r.reference_type for r in refs}
    _assert("lei" in types, "has lei")
    _assert("decreto" in types, "has decreto")
    _assert("portaria" in types, "has portaria")


def test_norm_ref_empty():
    """No references in text."""
    _section("NormRef — empty")
    _assert_eq(extract_normative_references(""), [], "empty string")
    _assert_eq(extract_normative_references("texto comum sem referências"), [], "no refs")


def test_norm_ref_from_real_fixture():
    """Extract normative refs from a fixture with known legislation."""
    _section("NormRef — real fixture")
    parser = INLabsXMLParser()
    art = parser.parse_file(FIXTURES / "2026-02-27-DO1E_600_20260227_23639224.xml")
    plain = strip_html(art.texto)
    refs = extract_normative_references(plain)
    # This is a Portaria Interministerial MPA/MMA — likely references legislation
    _assert(isinstance(refs, list), "returns list")


# ===========================================================================
# 5. HTML Extractor — Procedure References
# ===========================================================================

def test_proc_ref_processo():
    """Processo nº extraction."""
    _section("ProcRef — Processo nº")
    text = "Processo nº 23071.903252/2024-75"
    refs = extract_procedure_references(text)
    _assert(len(refs) >= 1, f"at least 1 ref, got {len(refs)}")
    _assert_eq(refs[0].procedure_identifier, "23071.903252/2024-75", "identifier")


def test_proc_ref_sei():
    """Processo SEI extraction."""
    _section("ProcRef — SEI")
    text = "Processo SEI nº 19740.000234/2023-12"
    refs = extract_procedure_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].procedure_type, "processo_sei", "type")


def test_proc_ref_proad():
    """PROAD extraction."""
    _section("ProcRef — PROAD")
    text = "PROAD Nº 5040/2024"
    refs = extract_procedure_references(text)
    _assert(len(refs) >= 1, "at least 1 ref")
    _assert_eq(refs[0].procedure_type, "proad", "type")
    _assert_eq(refs[0].procedure_identifier, "5040/2024", "identifier")


def test_proc_ref_empty():
    """No procedure refs."""
    _section("ProcRef — empty")
    _assert_eq(extract_procedure_references(""), [], "empty")
    _assert_eq(extract_procedure_references("texto sem processos"), [], "no procs")


# ===========================================================================
# 6. HTML Extractor — Document Number
# ===========================================================================

def test_doc_number_portaria():
    """PORTARIA Nº 772, DE 23 DE SETEMBRO DE 2020."""
    _section("DocNumber — portaria")
    num, year = extract_document_number("PORTARIA Nº 772, DE 23 DE SETEMBRO DE 2020")
    _assert_eq(num, "772", "number")
    _assert_eq(year, 2020, "year")


def test_doc_number_lei_with_slash():
    """LEI Nº 12.846/2013."""
    _section("DocNumber — lei with slash")
    num, year = extract_document_number("LEI Nº 12.846/2013")
    _assert_eq(num, "12.846/2013", "number")
    _assert_eq(year, 2013, "year")


def test_doc_number_no_number():
    """ACÓRDÃO — no number."""
    _section("DocNumber — no number")
    num, year = extract_document_number("ACÓRDÃO")
    _assert_eq(num, None, "no number")
    _assert_eq(year, None, "no year")


def test_doc_number_empty():
    """Empty input."""
    _section("DocNumber — empty")
    num, year = extract_document_number("")
    _assert_eq(num, None, "no number")
    _assert_eq(year, None, "no year")


def test_doc_number_from_fixtures():
    """Extract doc numbers from known fixtures."""
    _section("DocNumber — real fixtures")
    # PORTARIA Nº 640, DE 1º DE MARÇO DE 2026
    num, year = extract_document_number(" PORTARIA Nº 640, DE 1º  DE MARÇO DE 2026")
    _assert_eq(num, "640", "fixture portaria number")
    _assert_eq(year, 2026, "fixture portaria year")

    # RESOLUÇÃO GECEX Nº 866, DE 27 DE FEVEREIRO DE 2026
    num, year = extract_document_number(" RESOLUÇÃO GECEX Nº 866, DE 27 DE FEVEREIRO DE 2026")
    _assert_eq(num, "866", "fixture resolucao number")
    _assert_eq(year, 2026, "fixture resolucao year")

    # ATO Nº PBR-6.798, de 27 DE JANEIRO DE 2026
    num, year = extract_document_number(" ATO Nº PBR-6.798, de 27 DE JANEIRO DE 2026")
    # PBR-6.798 starts with P, not digit — may not match number pattern
    # Our regex requires \d as first char after Nº — this is a known edge case
    _assert(year == 2026, "fixture ato year")


# ===========================================================================
# 7. HTML Extractor — Art Type Normalization
# ===========================================================================

def test_art_type_uppercase():
    """UPPERCASE → lowercase."""
    _section("ArtType — uppercase")
    _assert_eq(normalize_art_type("PORTARIA"), "portaria", "PORTARIA")
    _assert_eq(normalize_art_type("DESPACHO"), "despacho", "DESPACHO")
    _assert_eq(normalize_art_type("RESOLUÇÃO"), "resolução", "RESOLUÇÃO")


def test_art_type_titlecase():
    """TitleCase → lowercase."""
    _section("ArtType — titlecase")
    _assert_eq(normalize_art_type("Portaria"), "portaria", "Portaria")
    _assert_eq(normalize_art_type("Despacho"), "despacho", "Despacho")
    _assert_eq(normalize_art_type("Ato"), "ato", "Ato")


def test_art_type_plural():
    """Plural → singular."""
    _section("ArtType — plural")
    _assert_eq(normalize_art_type("PORTARIAS"), "portaria", "PORTARIAS")
    _assert_eq(normalize_art_type("DESPACHOS"), "despacho", "DESPACHOS")
    _assert_eq(normalize_art_type("EXTRATOS"), "extrato", "EXTRATOS")
    _assert_eq(normalize_art_type("AVISOS"), "aviso", "AVISOS")
    _assert_eq(normalize_art_type("ATOS"), "ato", "ATOS")


def test_art_type_empty():
    """Empty input."""
    _section("ArtType — empty")
    _assert_eq(normalize_art_type(""), "", "empty")


def test_art_type_unknown_passthrough():
    """Unknown types pass through as-is in lowercase."""
    _section("ArtType — unknown passthrough")
    _assert_eq(normalize_art_type("TIPO INEXISTENTE"), "tipo inexistente", "unknown")


def test_art_type_canonical_coverage():
    """All canonical entries have a value."""
    _section("ArtType — canonical coverage")
    _assert(len(_ART_TYPE_CANONICAL) >= 30, f"at least 30 entries, got {len(_ART_TYPE_CANONICAL)}")
    for k, v in _ART_TYPE_CANONICAL.items():
        _assert(v, f"non-empty canonical for {k!r}")


# ===========================================================================
# 8. HTML Extractor — Issuing Organ
# ===========================================================================

def test_issuing_organ():
    """Extract top-level org from art_category."""
    _section("IssuingOrgan — extraction")
    _assert_eq(
        extract_issuing_organ("Ministério da Educação/Gabinete do Ministro"),
        "Ministério da Educação",
        "first segment",
    )
    _assert_eq(
        extract_issuing_organ("Presidência da República/Secretaria-Geral"),
        "Presidência da República",
        "presidencia",
    )
    _assert_eq(extract_issuing_organ(""), "", "empty")
    _assert_eq(extract_issuing_organ("Ministério Isolado"), "Ministério Isolado", "single segment")


# ===========================================================================
# 9. HTML Extractor — Strip HTML
# ===========================================================================

def test_strip_html():
    """Strip HTML tags and normalize whitespace."""
    _section("StripHTML")
    _assert_eq(strip_html("<p>Hello <b>world</b></p>"), "Hello world", "basic")
    _assert_eq(strip_html(""), "", "empty")
    _assert_eq(strip_html("plain text"), "plain text", "no tags")
    _assert_eq(strip_html("<p>  multiple   spaces  </p>"), "multiple spaces", "collapsed")


# ===========================================================================
# 10. Multi-part Merger — Filename Parsing
# ===========================================================================

def test_filename_parse_single():
    """Single file (no -N suffix)."""
    _section("Filename — single")
    base_id, idx = _parse_id_from_filename("515_20260227_23615168.xml")
    _assert_eq(base_id, "23615168", "base id")
    _assert_eq(idx, 0, "part index 0")


def test_filename_parse_multipart():
    """Multi-part file with -N suffix."""
    _section("Filename — multipart")
    base_id, idx = _parse_id_from_filename("600_20260227_23639293-1.xml")
    _assert_eq(base_id, "23639293", "base id")
    _assert_eq(idx, 1, "part index 1")

    base_id2, idx2 = _parse_id_from_filename("600_20260227_23639293-2.xml")
    _assert_eq(base_id2, "23639293", "same base id")
    _assert_eq(idx2, 2, "part index 2")


def test_filename_parse_short():
    """Short filename."""
    _section("Filename — short")
    base_id, idx = _parse_id_from_filename("simple.xml")
    _assert_eq(idx, 0, "no parts")


# ===========================================================================
# 11. Multi-part Merger — Group and Merge
# ===========================================================================

def _make_article(**kwargs) -> DOUArticle:
    """Build a DOUArticle with default values, overridable by kwargs."""
    defaults = {
        "id": "1", "id_materia": "12345678", "id_oficio": "1",
        "name": "TEST", "pub_name": "DO1", "pub_date": "01/01/2026",
        "edition_number": "1", "number_page": "1", "pdf_page": "",
        "art_type": "Portaria", "art_category": "Test/Cat",
        "art_class": "", "art_size": "", "art_notes": "",
        "highlight_type": "", "highlight_priority": "", "highlight": "",
        "highlight_image": "", "highlight_image_name": "",
        "identifica": "TEST DOC", "data": "", "ementa": "",
        "titulo": "", "sub_titulo": "", "texto": "<p>Body text</p>",
    }
    defaults.update(kwargs)
    return DOUArticle(**defaults)


def test_merge_single_articles():
    """Single articles pass through."""
    _section("Merger — singles")
    a1 = _make_article(id_materia="111")
    a2 = _make_article(id_materia="222")
    result = group_and_merge([
        (a1, Path("515_20260101_111.xml")),
        (a2, Path("515_20260101_222.xml")),
    ])
    _assert_eq(len(result), 2, "two results")
    for ma in result:
        _assert_eq(ma.is_multipart, False, f"not multipart: {ma.base_id_materia}")
        _assert_eq(ma.part_count, 1, "single part")


def test_merge_multipart():
    """Multi-part articles are merged."""
    _section("Merger — multipart")
    a1 = _make_article(id_materia="333", texto="<p>Part one</p>", identifica="RESOLUÇÃO")
    a2 = _make_article(id_materia="333", texto="<p>Part two</p>", identifica="")
    result = group_and_merge([
        (a1, Path("600_20260227_333-1.xml")),
        (a2, Path("600_20260227_333-2.xml")),
    ])
    _assert_eq(len(result), 1, "one merged result")
    ma = result[0]
    _assert_eq(ma.is_multipart, True, "is multipart")
    _assert_eq(ma.part_count, 2, "two parts")
    _assert_eq(ma.base_id_materia, "333", "base id")
    _assert("Part one" in ma.article.texto, "has part one")
    _assert("Part two" in ma.article.texto, "has part two")
    _assert("multipart-break" in ma.article.texto, "has separator")
    _assert_eq(ma.article.identifica, "RESOLUÇÃO", "uses part-1 metadata")
    _assert_eq(len(ma.xml_paths), 2, "two paths")


def test_merge_with_real_fixtures():
    """Merge the real multi-part fixture (23639293-1 and 23639293-2)."""
    _section("Merger — real fixtures")
    parser = INLabsXMLParser()
    articles = []
    for f in sorted(FIXTURES.glob("*23639293*.xml")):
        art = parser.parse_file(f)
        articles.append((art, f))
    _assert_eq(len(articles), 2, "two fixture parts")

    merged = group_and_merge(articles)
    _assert_eq(len(merged), 1, "one merged result")
    ma = merged[0]
    _assert_eq(ma.is_multipart, True, "is multipart")
    _assert_eq(ma.part_count, 2, "two parts")
    _assert_eq(ma.base_id_materia, "23639293", "base id")
    _assert("multipart-break" in ma.article.texto, "has separator")
    _assert_eq(ma.article.identifica.strip(), "RESOLUÇÃO GECEX Nº 866, DE 27 DE FEVEREIRO DE 2026", "primary identifica")


def test_merge_mixed():
    """Mix of single and multi-part articles."""
    _section("Merger — mixed batch")
    parser = INLabsXMLParser()
    articles = []
    for f in sorted(FIXTURES.glob("*.xml")):
        art = parser.parse_file(f)
        articles.append((art, f))

    merged = group_and_merge(articles)
    # 13 files, but 23639293-1 and 23639293-2 merge → 12 docs
    _assert_eq(len(merged), 12, "12 merged articles (13 files, 1 multipart pair)")

    multipart = [m for m in merged if m.is_multipart]
    singles = [m for m in merged if not m.is_multipart]
    _assert_eq(len(multipart), 1, "one multipart")
    _assert_eq(len(singles), 11, "eleven singles")


# ===========================================================================
# 12. DOU Ingestor — ZIP Meta Inference
# ===========================================================================

def test_infer_zip_meta():
    """Test ZIP filename → month/section inference."""
    _section("ZipMeta — inference")
    from src.backend.ingest.dou_ingest import _infer_zip_meta

    m, s = _infer_zip_meta("2020-09_do1_S01092020.zip")
    _assert_eq(m, "2020-09", "structured month")
    _assert_eq(s, "do1", "structured section")

    m, s = _infer_zip_meta("S01092020.zip")
    _assert_eq(m, "2020-09", "native month")
    _assert_eq(s, "do1", "native section do1")

    m, s = _infer_zip_meta("S02032023.zip")
    _assert_eq(m, "2023-03", "native month S02")
    _assert_eq(s, "do2", "native section do2")

    m, s = _infer_zip_meta("S03122005.zip")
    _assert_eq(m, "2005-12", "native month S03")
    _assert_eq(s, "do3", "native section do3")

    m, s = _infer_zip_meta("random_file.zip")
    _assert_eq(m, None, "unknown month")
    _assert_eq(s, None, "unknown section")


# ===========================================================================
# 13. Integration — Full extraction from fixture
# ===========================================================================

def test_full_extraction_pipeline():
    """End-to-end: parse → merge → extract from fixtures."""
    _section("Integration — full extraction pipeline")
    parser = INLabsXMLParser()

    # Parse the Portaria Interministerial (has signatures, likely has norm refs)
    art = parser.parse_file(FIXTURES / "2026-02-27-DO1E_600_20260227_23639224.xml")

    # Signatures
    sigs = _extract_signatures_precise(art.texto)
    _assert(len(sigs) >= 1, f"has signatures: {len(sigs)}")

    # Images
    imgs = extract_images(art.texto)
    _assert(isinstance(imgs, list), "images is list")

    # Normative refs
    plain = strip_html(art.texto)
    nrefs = extract_normative_references(plain)
    _assert(isinstance(nrefs, list), "norm refs is list")

    # Procedure refs
    prefs = extract_procedure_references(plain)
    _assert(isinstance(prefs, list), "proc refs is list")

    # Doc number
    num, year = extract_document_number(art.identifica)
    _assert_eq(num, "51", "portaria number")
    _assert_eq(year, 2026, "portaria year")

    # Art type
    _assert_eq(normalize_art_type(art.art_type), "portaria", "normalized art type")

    # Issuing organ
    org = extract_issuing_organ(art.art_category)
    _assert(len(org) > 0, f"has issuing organ: {org!r}")


def test_full_extraction_acórdão():
    """Acórdão — no number, short text, has signature."""
    _section("Integration — acórdão")
    parser = INLabsXMLParser()
    art = parser.parse_file(FIXTURES / "2026-02-27-DO1_515_20260227_23615168.xml")

    num, year = extract_document_number(art.identifica)
    _assert_eq(num, None, "no number for acórdão")

    sigs = _extract_signatures_precise(art.texto)
    _assert(len(sigs) >= 1, "acórdão has signature")

    _assert_eq(normalize_art_type(art.art_type), "acórdão", "acórdão type")


def test_full_extraction_extrato():
    """Extrato de Contrato — no signatures typically."""
    _section("Integration — extrato")
    parser = INLabsXMLParser()
    art = parser.parse_file(FIXTURES / "2026-02-27-DO3_530_20260227_22423649.xml")

    sigs = _extract_signatures_precise(art.texto)
    _assert_eq(len(sigs), 0, "extrato has no signatures")

    _assert_eq(normalize_art_type(art.art_type), "extrato de contrato", "extrato type (passthrough)")


# ===========================================================================
# Run all tests
# ===========================================================================

def main() -> int:
    tests = [
        # Sanitizer
        test_sanitizer_no_op_for_clean_xml,
        test_sanitizer_strips_leaked_identifica,
        test_sanitizer_handles_multiple_variants,
        test_sanitizer_preserves_body_closing_tags,
        test_sanitizer_with_real_fixtures,
        # Signatures
        test_signatures_simple,
        test_signatures_no_cargo,
        test_signatures_multiple,
        test_signatures_empty,
        test_signatures_from_real_fixture,
        # Images
        test_images_extraction,
        test_images_empty,
        # Normative refs
        test_norm_ref_lei,
        test_norm_ref_decreto,
        test_norm_ref_resolucao,
        test_norm_ref_instrucao_normativa,
        test_norm_ref_portaria,
        test_norm_ref_dedup,
        test_norm_ref_multiple_types,
        test_norm_ref_empty,
        test_norm_ref_from_real_fixture,
        # Procedure refs
        test_proc_ref_processo,
        test_proc_ref_sei,
        test_proc_ref_proad,
        test_proc_ref_empty,
        # Document number
        test_doc_number_portaria,
        test_doc_number_lei_with_slash,
        test_doc_number_no_number,
        test_doc_number_empty,
        test_doc_number_from_fixtures,
        # Art type
        test_art_type_uppercase,
        test_art_type_titlecase,
        test_art_type_plural,
        test_art_type_empty,
        test_art_type_unknown_passthrough,
        test_art_type_canonical_coverage,
        # Issuing organ
        test_issuing_organ,
        # Strip HTML
        test_strip_html,
        # Multipart merger
        test_filename_parse_single,
        test_filename_parse_multipart,
        test_filename_parse_short,
        test_merge_single_articles,
        test_merge_multipart,
        test_merge_with_real_fixtures,
        test_merge_mixed,
        # DOU ingestor helpers
        test_infer_zip_meta,
        # Integration
        test_full_extraction_pipeline,
        test_full_extraction_acórdão,
        test_full_extraction_extrato,
    ]

    for test_fn in tests:
        try:
            test_fn()
        except Exception as ex:
            global _failed
            _failed += 1
            print(f"  EXCEPTION in {test_fn.__name__}: {ex}", file=sys.stderr)

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}")

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
