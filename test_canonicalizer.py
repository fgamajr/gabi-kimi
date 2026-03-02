"""Tests for harvest.canonicalizer — determinism, idempotency, preservation."""
from __future__ import annotations

from harvest.canonicalizer import canonicalize


def _assert_idempotent(raw: bytes) -> bytes:
    """Assert canonicalize is idempotent and return result."""
    first = canonicalize(raw)
    second = canonicalize(first)
    assert first == second, "canonicalize is not idempotent"
    return first


# --- Cache-buster timestamps ---

def test_cache_buster_query_t():
    raw = b'<link href="/css/main.css?t=1709312456" rel="stylesheet">'
    out = _assert_idempotent(raw)
    assert b"?t=0" in out
    assert b"1709312456" not in out


def test_cache_buster_amp_t():
    raw = b'<script src="/js/app.js?p=1&amp;t=1709312456789"></script>'
    out = _assert_idempotent(raw)
    assert b"&amp;t=0" in out
    assert b"1709312456789" not in out


def test_cache_buster_bare_amp_t():
    raw = b'<script src="/js/app.js?p=1&t=1709312456"></script>'
    out = _assert_idempotent(raw)
    assert b"&t=0" in out
    assert b"1709312456" not in out


# --- Liferay authToken ---

def test_auth_token():
    raw = b"Liferay.authToken = 'abc123xyz'"
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"abc123xyz" not in out


def test_auth_token_no_spaces():
    raw = b"Liferay.authToken='tokenvalue'"
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"tokenvalue" not in out


def test_auth_token_double_quotes():
    raw = b'Liferay.authToken = "abc123xyz"'
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"abc123xyz" not in out


# --- Today date value ---

def test_today_value():
    raw = b'<input name="today" type="hidden" value="01/03/2026">'
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"01/03/2026" not in out


def test_today_value_reversed_attrs():
    raw = b'<input type="hidden" value="01/03/2026" name="today">'
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"01/03/2026" not in out


# --- Today href ---

def test_today_href():
    raw = b'<a href="/leiturajornal?data=01-03-2026&secao=do1">'
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"01-03-2026" not in out


def test_today_href_amp():
    raw = b'<a href="/leiturajornal?data=15-02-2026&amp;secao=do2">'
    out = _assert_idempotent(raw)
    assert b"REDACTED" in out
    assert b"15-02-2026" not in out


# --- Combo servlet IDs ---

def test_combo_id():
    raw = b'<link href="/combo?a=1&b=2" id="a1b2c3d4e5" rel="stylesheet">'
    out = _assert_idempotent(raw)
    assert b'id="REDACTED"' in out
    assert b"a1b2c3d4e5" not in out


def test_combo_id_uppercase():
    raw = b'<link href="/combo?a=1&b=2" id="A1B2C3D4E5" rel="stylesheet">'
    out = _assert_idempotent(raw)
    assert b'id="REDACTED"' in out
    assert b"A1B2C3D4E5" not in out


# --- Preservation ---

def test_preserves_content():
    raw = (
        b"<html><body>"
        b"<h1>DECRETO N\xc2\xba 1.234</h1>"
        b"<p>Art. 1\xc2\xba Fica aprovado...</p>"
        b"</body></html>"
    )
    out = _assert_idempotent(raw)
    assert out == raw  # no patterns matched, content unchanged


def test_empty_input():
    out = _assert_idempotent(b"")
    assert out == b""


def test_binary_passthrough():
    raw = bytes(range(256))
    out = _assert_idempotent(raw)
    assert out == raw  # no patterns matched


# --- Determinism ---

def test_deterministic_same_input():
    raw = (
        b'Liferay.authToken = \'tok1\'\n'
        b'<link href="/css/x.css?t=1709312456" />\n'
        b'<input name="today" type="hidden" value="01/03/2026">\n'
        b'<a href="/leiturajornal?data=01-03-2026&secao=do1">\n'
        b'<link href="/combo?a=1" id="deadbeef" />\n'
    )
    results = [canonicalize(raw) for _ in range(100)]
    assert all(r == results[0] for r in results)


# --- Combined patterns ---

def test_all_patterns_combined():
    raw = (
        b'<html>\n'
        b'<link href="/combo?a=1" id="ff00ff" />\n'
        b'<link href="/css/main.css?t=1709312456" />\n'
        b'<script>Liferay.authToken = \'secret\'</script>\n'
        b'<input name="today" type="hidden" value="01/03/2026">\n'
        b'<a href="/leiturajornal?data=01-03-2026&secao=do3">link</a>\n'
        b'<p>Real content here</p>\n'
        b'</html>\n'
    )
    out = _assert_idempotent(raw)
    assert b"secret" not in out
    assert b"1709312456" not in out
    assert b"01/03/2026" not in out
    assert b"01-03-2026" not in out
    assert b"ff00ff" not in out
    assert b"Real content here" in out


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
