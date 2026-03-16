"""ZIP-wide DOU article reconstruction helpers for multipart ingest."""

from __future__ import annotations

from dataclasses import dataclass, replace
import html
from pathlib import Path
import re


@dataclass(slots=True)
class ParsedArticle:
    source_xml_path: str
    raw_id: str
    id_materia: str
    id_oficio: str
    xml_name: str
    pub_name: str
    pub_date: str
    edition_number: str
    number_page: str
    pdf_page: str
    art_type_raw: str
    art_category: str
    art_class_raw: str
    art_size: str
    art_notes: str
    highlight_type: str
    highlight_priority: str
    highlight: str
    highlight_image: str
    highlight_image_name: str
    identifica: str
    data_text: str
    ementa: str
    titulo: str
    sub_titulo: str
    texto_html: str


@dataclass(slots=True)
class ReconstructedArticle:
    article: ParsedArticle
    logical_doc_id_seed: str
    merged_from_xml_paths: list[str]
    is_multipart: bool
    multipart_seq: int
    part_count: int
    was_page_fragment_merged: bool = False
    was_blob_split: bool = False
    split_segment_index: int | None = None
    reconstruction_status: str = "complete"
    reconstruction_notes: list[str] | None = None


_MULTIPART_RE = re.compile(r"^(.*?)-(\d+)$")
_SEPARATOR_RE = re.compile(r"^[_\-]{2,}")
_STARTS_LOWERCASE_RE = re.compile(r"^[a-záàâãéêíóôõúüç]")
_WORD_BREAK_HYPHEN_RE = re.compile(r"\w-$")
_INDEX_DOT_LEADER_RE = re.compile(r"\.{3,}\s*\d+\s*$", re.MULTILINE)
_ACT_HEADER_FULL_RE = re.compile(
    r"(?:PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)"
    r"\s+N[ºo°]\s*[\d\.]+"
    r",?\s+DE\s+\d{1,2}\s+DE\s+\w+\s+DE\s+\d{4}",
    re.IGNORECASE,
)
_ACT_HEADER_RE = re.compile(
    r"(?:PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)"
    r"\s+N[ºo°]\s*[\d\.]+",
    re.IGNORECASE,
)
_P_TAG_RE = re.compile(r"<p\s[^>]*>", re.IGNORECASE)
_TCU_CATEGORY_RE = re.compile(r"Tribunal\s+de\s+Contas\s+da\s+Uni[aã]o", re.IGNORECASE)
_SECTION_HEADER_TYPES = frozenset({"MINISTÉRIO"})
_FRAGMENT_ART_TYPES = frozenset({"AV", "VO"})
_KNOWN_ACT_TYPES = frozenset(
    {
        "PORTARIA",
        "RESOLUÇÃO",
        "INSTRUÇÃO NORMATIVA",
        "DESPACHO",
        "DECRETO",
        "EDITAL",
        "ATO",
        "CIRCULAR",
        "MEDIDA PROVISÓRIA",
        "AVISO",
        "RETIFICAÇÃO",
        "EXTRATO",
        "DECISÃO",
        "ACÓRDÃO",
        "ATA",
        "LEI",
        "CONTRATO",
        "TERMO",
        "PROVIMENTO",
    }
)


def parse_multipart_id(filename: str) -> tuple[str, int]:
    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) < 3:
        return stem, 0
    last = parts[-1]
    match = _MULTIPART_RE.match(last)
    if match:
        return match.group(1), int(match.group(2))
    return last, 0


def group_and_merge_articles(articles: list[ParsedArticle]) -> list[ReconstructedArticle]:
    groups: dict[str, list[tuple[int, ParsedArticle]]] = {}
    for article in articles:
        base_id, part_idx = parse_multipart_id(article.source_xml_path)
        groups.setdefault(base_id, []).append((part_idx, article))

    reconstructed: list[ReconstructedArticle] = []
    for base_id, grouped in groups.items():
        grouped.sort(key=lambda item: item[0])
        if len(grouped) == 1:
            _, article = grouped[0]
            reconstructed.append(
                ReconstructedArticle(
                    article=article,
                    logical_doc_id_seed=base_id,
                    merged_from_xml_paths=[article.source_xml_path],
                    is_multipart=False,
                    multipart_seq=0,
                    part_count=1,
                    reconstruction_notes=[],
                )
            )
            continue
        primary = grouped[0][1]
        merged_html_parts = [article.texto_html.strip() for _, article in grouped if article.texto_html.strip()]
        merged_html = '\n<hr class="multipart-break" />\n'.join(merged_html_parts)
        merged_article = replace(
            primary,
            id_materia=base_id or primary.id_materia,
            texto_html=merged_html,
        )
        reconstructed.append(
            ReconstructedArticle(
                article=merged_article,
                logical_doc_id_seed=base_id,
                merged_from_xml_paths=[article.source_xml_path for _, article in grouped],
                is_multipart=True,
                multipart_seq=0,
                part_count=len(grouped),
                reconstruction_notes=["merged_multipart"],
            )
        )
    return reconstructed


def is_page_fragment(article: ParsedArticle) -> bool:
    ident = (article.identifica or "").strip()
    art = (article.art_type_raw or "").strip()
    if ident and _STARTS_LOWERCASE_RE.match(ident):
        return True
    if _SEPARATOR_RE.match(art):
        return True
    if len(art) <= 1:
        return True
    if art and art[0] in "(*":
        return True
    if art and art[0].isdigit():
        return True
    if _WORD_BREAK_HYPHEN_RE.search(ident) and art.upper() not in _KNOWN_ACT_TYPES:
        return True
    if art.upper() in _SECTION_HEADER_TYPES or art.upper() in _FRAGMENT_ART_TYPES:
        return True
    body_len = len((article.texto_html or "").strip())
    if art.upper() in {"ANEXO", "ANEXOS"} and body_len <= 40:
        return True
    if article.art_category and _TCU_CATEGORY_RE.search(article.art_category) and art.upper() not in _KNOWN_ACT_TYPES:
        return True
    return False


def merge_page_fragments(articles: list[ReconstructedArticle]) -> list[ReconstructedArticle]:
    if not articles:
        return articles
    sorted_articles = sorted(articles, key=lambda item: item.logical_doc_id_seed)
    result: list[ReconstructedArticle] = []
    for item in sorted_articles:
        if is_page_fragment(item.article) and result:
            parent = result[-1]
            merged_html = "\n".join(filter(None, [parent.article.texto_html.rstrip(), item.article.texto_html.strip()]))
            merged_article = replace(parent.article, texto_html=merged_html)
            notes = list(parent.reconstruction_notes or [])
            notes.append(f"merged_page_fragment:{item.article.source_xml_path}")
            result[-1] = replace(
                parent,
                article=merged_article,
                merged_from_xml_paths=parent.merged_from_xml_paths + item.merged_from_xml_paths,
                was_page_fragment_merged=True,
                reconstruction_notes=notes,
            )
            continue
        result.append(item)
    return result


def is_index_document(article: ParsedArticle) -> bool:
    category = article.art_category or ""
    if "Índice de Normas" in category or "Indice de Normas" in category:
        return True
    if (article.art_type_raw or "").strip().upper() in {"MINISTÉRIO", "ÍNDICE DE NORMAS"}:
        return bool(_INDEX_DOT_LEADER_RE.search(article.texto_html or ""))
    return False


def _find_act_boundaries(html_content: str) -> list[tuple[int, str]]:
    boundaries: list[tuple[int, str]] = []
    for match in _P_TAG_RE.finditer(html_content):
        close = html_content.find("</p>", match.end())
        if close == -1:
            continue
        text = re.sub(r"<[^>]+>", "", html_content[match.end() : close]).strip()
        if not text:
            continue
        tag = match.group(0)
        is_identifica_tag = "identifica" in tag.lower()
        if is_identifica_tag and _ACT_HEADER_RE.match(text):
            boundaries.append((match.start(), text))
        elif not is_identifica_tag and _ACT_HEADER_FULL_RE.match(text):
            boundaries.append((match.start(), text))
    return boundaries


def split_blob_reconstructed(item: ReconstructedArticle) -> list[ReconstructedArticle]:
    html_content = item.article.texto_html or ""
    if len(html_content) < 15_000:
        return [item]
    boundaries = _find_act_boundaries(html_content)
    if len(boundaries) < 2:
        return [item]
    results: list[ReconstructedArticle] = []
    for index, (start, identifica) in enumerate(boundaries, 1):
        end = boundaries[index][0] if index < len(boundaries) else len(html_content)
        segment_html = html_content[start:end].strip()
        if not segment_html:
            continue
        art_type_match = re.match(
            r"(PORTARIA|RESOLUÇÃO|INSTRUÇÃO NORMATIVA|DESPACHO|DECRETO|EDITAL|ATO|CIRCULAR|MEDIDA PROVISÓRIA)",
            identifica,
            re.IGNORECASE,
        )
        split_article = replace(
            item.article,
            id_materia=f"{item.article.id_materia or item.logical_doc_id_seed}_seg{index}",
            identifica=identifica,
            art_type_raw=art_type_match.group(1) if art_type_match else item.article.art_type_raw,
            texto_html=segment_html,
            ementa=item.article.ementa if index == 1 else "",
        )
        notes = list(item.reconstruction_notes or [])
        notes.append(f"split_blob_segment:{index}")
        results.append(
            replace(
                item,
                article=split_article,
                logical_doc_id_seed=split_article.id_materia,
                was_blob_split=True,
                split_segment_index=index,
                reconstruction_notes=notes,
            )
        )
    return results or [item]


def canonical_source_url(pdf_page: str | None) -> str | None:
    if not pdf_page:
        return None
    unescaped = html.unescape(pdf_page).strip()
    return re.sub(r"#.*$", "", unescaped) or None
