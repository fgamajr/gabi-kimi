"""Primary key policy for TCU open-data CSV rows loaded into Postgres raw tables.

Policy (aligned with existing Mongo/ES ingest):
  id == normalized CSV column KEY == Mongo _id == ES _id (doc_id)

See tcu_ingest.py / tcu_jurisprudencia_ingest.py (update_one _id = doc['doc_id']).
"""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")


def normalize_tcu_key(raw: str | None) -> str:
    """Match tcu_processor._normalize / tcu_jurisprudencia_processor._normalize."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFC", raw)
    return _SPACE_RE.sub(" ", text).strip()


def tcu_csv_row_primary_key(row: dict[str, str]) -> str:
    """Stable Postgres PK for a TCU CSV row. Raises if KEY is missing after normalize."""
    key = normalize_tcu_key(row.get("KEY"))
    if not key:
        msg = "CSV row missing or empty KEY after normalize"
        raise ValueError(msg)
    return key
