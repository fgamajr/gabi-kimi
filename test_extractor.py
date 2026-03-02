"""Tests for harvest.extractor — deterministic structural extraction.

Phase 3 contract: extract(canonical_bytes) -> NormativeAct (single act).
Operates only on synthetic canonical fixtures. No network. No heuristics.
"""
from __future__ import annotations

from harvest.extractor import ExtractionError, extract


# --- Synthetic canonical HTML fixtures ---

SIMPLE_DECRETO = b"""
<html><body>
<p class="identifica">DECRETO N\xc2\xba 1.234, DE 1\xc2\xba DE JANEIRO DE 2020</p>
<p class="ementa">Regulamenta a Lei n\xc2\xba 9.999.</p>
<p class="dou-paragraph">Art. 1\xc2\xba Fica aprovado o regulamento.</p>
<p class="dou-paragraph">Art. 2\xc2\xba Este Decreto entra em vigor na data de sua publica\xc3\xa7\xc3\xa3o.</p>
</body></html>
"""

THREE_ARTICLES_PORTARIA = b"""
<html><body>
<p class="identifica">PORTARIA N\xc2\xba 42, DE 15 DE FEVEREIRO DE 2025</p>
<p class="ementa">Estabelece procedimentos para fiscaliza\xc3\xa7\xc3\xa3o.</p>
<p>Art. 1\xc2\xba Os procedimentos de fiscaliza\xc3\xa7\xc3\xa3o
obedecer\xc3\xa3o ao disposto nesta Portaria.</p>
<p>Art. 2\xc2\xba Revoga-se a Portaria n\xc2\xba 10, de 2020.</p>
<p>Art. 3\xc2\xba Esta Portaria entra em vigor na data de sua publica\xc3\xa7\xc3\xa3o.</p>
</body></html>
"""

SINGLE_ARTICLE_LEI = b"""
<html><body>
<p>LEI N\xc2\xba 14.500, DE 10 DE OUTUBRO DE 2023</p>
<p>Altera dispositivo da Lei.</p>
<p>Art. 1\xc2\xba O art. 5\xc2\xba da Lei passa a vigorar com a seguinte reda\xc3\xa7\xc3\xa3o.</p>
</body></html>
"""

RESOLUCAO = b"""
<html><body>
<p>RESOLU\xc3\x87\xc3\x83O N\xc2\xba 50, DE 20 DE MAR\xc3\x87O DE 2024</p>
<p>Disposi\xc3\xa7\xc3\xb5es sobre procedimento.</p>
<p>Art. 1\xc2\xba Aprova-se o procedimento.</p>
</body></html>
"""

NO_HEADER = b"""
<html><body>
<p>Texto qualquer sem ato normativo.</p>
</body></html>
"""

NO_ARTICLES = b"""
<html><body>
<p>DECRETO N\xc2\xba 999, DE 5 DE MAIO DE 2024</p>
<p>Algum texto sem artigos definidos.</p>
</body></html>
"""

MULTIPLE_HEADERS = b"""
<html><body>
<p>DECRETO N\xc2\xba 100, DE 1\xc2\xba DE JANEIRO DE 2025</p>
<p>Primeiro decreto.</p>
<p>Art. 1\xc2\xba Primeiro artigo.</p>
<p>PORTARIA N\xc2\xba 5, DE 2 DE JANEIRO DE 2025</p>
<p>Portaria complementar.</p>
<p>Art. 1\xc2\xba Artigo da portaria.</p>
</body></html>
"""

NESTED_HTML = b"""
<html><body>
<div class="content">
  <span class="identifica"><strong>DECRETO N\xc2\xba 5.678, DE 20 DE JUNHO DE 2023</strong></span>
  <div class="ementa"><em>Regulamenta dispositivos.</em></div>
  <div class="dou-paragraph">
    <p>Art. 1\xc2\xba <strong>Fica regulamentado</strong> o disposto na Lei.</p>
  </div>
  <div class="dou-paragraph">
    <p>Art. 2\xc2\xba Esta norma entra em vigor.</p>
  </div>
</div>
</body></html>
"""

HTML_ENTITIES = b"""
<html><body>
<p>DECRETO N&ordm; 300, DE 1&ordm; DE ABRIL DE 2024</p>
<p>Regulamenta a Lei n&ordm; 8.000.</p>
<p>Art. 1&ordm; O disposto nesta norma &eacute; aplic&aacute;vel.</p>
<p>Art. 2&ordm; Entra em vigor.</p>
</body></html>
"""


# --- Tests ---

def test_simple_decreto():
    act = extract(SIMPLE_DECRETO)
    assert act.kind == "DECRETO"
    assert act.number == "1.234"
    assert "JANEIRO DE 2020" in act.date
    assert len(act.articles) == 2
    assert act.articles[0].number == "1"
    assert act.articles[1].number == "2"
    assert "aprovado" in act.articles[0].text
    assert "vigor" in act.articles[1].text


def test_portaria_three_articles():
    act = extract(THREE_ARTICLES_PORTARIA)
    assert act.kind == "PORTARIA"
    assert act.number == "42"
    assert len(act.articles) == 3
    assert act.articles[0].number == "1"
    assert act.articles[1].number == "2"
    assert act.articles[2].number == "3"


def test_single_article_lei():
    act = extract(SINGLE_ARTICLE_LEI)
    assert act.kind == "LEI"
    assert act.number == "14.500"
    assert len(act.articles) == 1
    assert act.articles[0].number == "1"


def test_resolucao():
    act = extract(RESOLUCAO)
    assert act.kind == "RESOLUÇÃO"
    assert act.number == "50"
    assert len(act.articles) == 1


def test_no_header_raises():
    try:
        extract(NO_HEADER)
        assert False, "should have raised ExtractionError"
    except ExtractionError as exc:
        assert "no normative act header" in str(exc)


def test_no_articles_raises():
    try:
        extract(NO_ARTICLES)
        assert False, "should have raised ExtractionError"
    except ExtractionError as exc:
        assert "no articles found" in str(exc)


def test_multiple_headers_raises():
    try:
        extract(MULTIPLE_HEADERS)
        assert False, "should have raised ExtractionError"
    except ExtractionError as exc:
        assert "multiple headers" in str(exc)


def test_nested_html():
    act = extract(NESTED_HTML)
    assert act.kind == "DECRETO"
    assert act.number == "5.678"
    assert len(act.articles) == 2
    assert "regulamentado" in act.articles[0].text.lower()


def test_html_entities():
    act = extract(HTML_ENTITIES)
    assert act.kind == "DECRETO"
    assert act.number == "300"
    assert len(act.articles) == 2


def test_ementa_extracted():
    act = extract(SIMPLE_DECRETO)
    assert act.ementa
    assert "9.999" in act.ementa


def test_empty_input_raises():
    try:
        extract(b"")
        assert False, "should have raised ExtractionError"
    except ExtractionError:
        pass


def test_deterministic():
    results = [extract(SIMPLE_DECRETO) for _ in range(100)]
    first = results[0]
    for r in results[1:]:
        assert r.kind == first.kind
        assert r.number == first.number
        assert r.date == first.date
        assert r.articles == first.articles


def test_text_preserved_not_rewritten():
    """Article text must preserve the original wording."""
    act = extract(THREE_ARTICLES_PORTARIA)
    art1_text = act.articles[0].text
    assert "fiscalização" in art1_text
    assert "Portaria" in art1_text


INLINE_TAGS_MID_WORD = b"""
<html><body>
<p><b>DECRETO</b> N\xc2\xba 777, DE 1\xc2\xba DE JANEIRO DE 2025</p>
<p>Regulamenta a <em>Lei</em>.</p>
<p>Art. 1\xc2\xba Fica <b>aprovado</b> o regulamento.</p>
</body></html>
"""


def test_inline_tags_do_not_split_words():
    """Inline tags like <b> must not break word boundaries."""
    act = extract(INLINE_TAGS_MID_WORD)
    assert act.kind == "DECRETO"
    assert act.number == "777"
    assert "aprovado" in act.articles[0].text


COMMENTED_HEADER = b"""
<html><body>
<!-- DECRETO N\xc2\xba 999, DE 1\xc2\xba DE JANEIRO DE 2020 -->
<p>DECRETO N\xc2\xba 500, DE 5 DE MAIO DE 2024</p>
<p>Regulamenta dispositivo.</p>
<p>Art. 1\xc2\xba Fica aprovado.</p>
</body></html>
"""


def test_html_comment_ignored():
    """HTML comments containing header-like text must not count as headers."""
    act = extract(COMMENTED_HEADER)
    assert act.kind == "DECRETO"
    assert act.number == "500"
    assert len(act.articles) == 1


NDOT_ORDINAL = b"""
<html><body>
<p>DECRETO N.\xc2\xba 800, DE 10 DE JUNHO DE 2024</p>
<p>Regulamenta procedimentos.</p>
<p>Art. 1\xc2\xba. Fica aprovado o regulamento.</p>
<p>Art. 2\xc2\xba. Este Decreto entra em vigor.</p>
</body></html>
"""


def test_ndot_ordinal_header():
    """N.º variation in header must be accepted."""
    act = extract(NDOT_ORDINAL)
    assert act.kind == "DECRETO"
    assert act.number == "800"
    assert len(act.articles) == 2


def test_article_trailing_period():
    """Art. 1º. with trailing period must be accepted."""
    act = extract(NDOT_ORDINAL)
    assert act.articles[0].number == "1"
    assert act.articles[1].number == "2"


def test_invalid_utf8_raises():
    """Invalid UTF-8 bytes must raise ExtractionError, not silently corrupt."""
    try:
        extract(b"\xff\xfe DECRETO")
        assert False, "should have raised ExtractionError"
    except ExtractionError as exc:
        assert "invalid utf-8" in str(exc)


if __name__ == "__main__":
    import sys
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ERROR {t.__name__}: {exc}")
            failed += 1
    print(f"\n{len(tests)} tests, {failed} failed")
    sys.exit(1 if failed else 0)
