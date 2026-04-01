from __future__ import annotations

from src.backend.answering.aggregation import (
    _SECTION_ORDER,
    build_aggregation_summary,
    group_by_section,
)
from src.backend.answering.service import _build_evidence_text


def _make_doc(section: str = "", art_type: str = "", **overrides: object) -> dict:
    doc: dict = {
        "_id": "doc-1",
        "title": "Título teste",
        "body_plain": "Conteúdo de teste",
        "issuing_organ": "Órgão X",
        "pub_date": "2024-01-15",
        "section": section,
        "art_type": art_type,
    }
    doc.update(overrides)
    return doc


class TestGroupBySection:
    def test_group_by_section_orders_do1_first(self) -> None:
        docs = [
            _make_doc(section="do3", _id="a"),
            _make_doc(section="do1", _id="b"),
            _make_doc(section="tcu", _id="c"),
        ]
        result = group_by_section(docs)
        keys = list(result.keys())
        assert keys.index("do1") < keys.index("do3")
        assert keys.index("tcu") < keys.index("do3")

    def test_section_order_follows_constant(self) -> None:
        docs = [_make_doc(section=s) for s in reversed(_SECTION_ORDER)]
        result = group_by_section(docs)
        assert list(result.keys()) == _SECTION_ORDER

    def test_unknown_sections_after_known(self) -> None:
        docs = [
            _make_doc(section="do1"),
            _make_doc(section="xyz"),
        ]
        result = group_by_section(docs)
        keys = list(result.keys())
        assert keys[0] == "do1"
        assert keys[1] == "xyz"


class TestBuildAggregationSummary:
    def test_by_section_in_summary(self) -> None:
        docs = [
            _make_doc(section="do1", title="Portaria A"),
            _make_doc(section="do1", title="Portaria B"),
            _make_doc(section="tcu"),
        ]
        summary = build_aggregation_summary(docs, "teste")
        assert "by_section" in summary
        assert summary["by_section"]["do1"] == 2
        assert summary["by_section"]["tcu"] == 1


class TestBuildEvidenceText:
    def test_build_evidence_text_includes_section(self) -> None:
        docs = [
            _make_doc(section="do1", art_type="Portaria"),
        ]
        text = _build_evidence_text(docs)
        assert "DOU Seção 1" in text
        assert "Portaria" in text

    def test_build_evidence_text_includes_tcu_section(self) -> None:
        docs = [
            _make_doc(section="tcu", art_type="Acórdão"),
        ]
        text = _build_evidence_text(docs)
        assert "TCU — Jurisprudência" in text
        assert "Acórdão" in text
