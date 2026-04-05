from __future__ import annotations

import pytest

from src.backend.ingest import tcu_csv_postgres_ingest as tcu_pg_ingest
from src.backend.ingest.tcu_csv_raw_catalog import source_by_name
from src.backend.ingest.tcu_csv_raw_id import normalize_tcu_key, tcu_csv_row_primary_key
from src.backend.ingest.tcu_csv_raw_pg import validate_csv_headers


def test_normalize_tcu_key() -> None:
    assert normalize_tcu_key("  foo\nbar  ") == "foo bar"


def test_tcu_csv_row_primary_key() -> None:
    assert tcu_csv_row_primary_key({"KEY": "ACORDAO-1"}) == "ACORDAO-1"
    with pytest.raises(ValueError):
        tcu_csv_row_primary_key({"KEY": ""})


def test_validate_csv_headers_match() -> None:
    spec = source_by_name("boletim_jurisprudencia")
    validate_csv_headers(list(spec.csv_columns), spec)


def test_validate_csv_headers_drift() -> None:
    spec = source_by_name("boletim_jurisprudencia")
    with pytest.raises(ValueError, match="header mismatch"):
        validate_csv_headers(["KEY", "TITULO", "EXTRA_UNKNOWN"], spec)


def test_skip_unchanged_by_head_etag_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tcu_pg_ingest, "fetch_meta_etag", lambda _conn, _url: '"x"')

    class _Resp:
        status_code = 200
        headers = {"etag": '"x"'}

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def head(self, _url: str) -> _Resp:
            return _Resp()

    monkeypatch.setattr(tcu_pg_ingest.httpx, "Client", lambda **_kw: _Client())
    assert tcu_pg_ingest._skip_unchanged_by_head_etag(
        object(), "https://example.com/f.csv", skip_unchanged=True
    )


def test_skip_unchanged_by_head_etag_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tcu_pg_ingest, "fetch_meta_etag", lambda _conn, _url: '"x"')
    assert not tcu_pg_ingest._skip_unchanged_by_head_etag(
        object(), "https://example.com/f.csv", skip_unchanged=False
    )
