from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re
from typing import Any

from validation.html_tools import HtmlTag, find_first_attr, parse_html_tags, select_tags
from validation.rules import LoadedRules, parse_attr_selector, parse_contains_selector


@dataclass(slots=True)
class SelectorStat:
    attempts: int = 0
    successes: int = 0


@dataclass(slots=True)
class FileResult:
    file: str
    page_url: str | None
    document_count: int
    suspicious_split: bool
    missing_required: list[str]
    empty_body_count: int
    duplicate_identity_count: int
    heuristics_only_fields: list[str]
    parsed: dict[str, Any]


@dataclass(slots=True)
class ExtractRunResult:
    files: list[FileResult] = field(default_factory=list)
    selector_stats: dict[str, SelectorStat] = field(default_factory=dict)


class ExtractionHarness:
    def __init__(self, rules: LoadedRules) -> None:
        self.rules = rules
        self.selector_stats: dict[str, SelectorStat] = {}

    def run_file(self, html_path: Path) -> FileResult:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        tags = parse_html_tags(html)

        page_url = self._canonical_url(tags)
        docs = self._split_documents(tags)
        publication_issue = self._extract_publication_issue(tags, page_url)

        parsed_docs: list[dict[str, Any]] = []
        missing_required: list[str] = []
        empty_body_count = 0
        duplicate_identity = 0
        seen_identity: set[str] = set()
        heur_only: set[str] = set()

        for idx, doc_ctx in enumerate(docs, start=1):
            doc = self._extract_document(doc_ctx)
            coll = self._extract_collections(doc_ctx)

            identity = self._stable_identity(doc)
            if identity in seen_identity:
                duplicate_identity += 1
            seen_identity.add(identity)

            if not (doc.get("body_text") or "").strip():
                empty_body_count += 1

            for k in ["document_number", "document_year", "issuing_authority", "issuing_organ"]:
                if doc.get(k) is not None:
                    heur_only.add(f"document.{k}")

            parsed_docs.append(
                {
                    "index": idx,
                    "document": doc,
                    "document_identity": {
                        "stable_hash": identity,
                        "natural_keys": {
                            "document_type": doc.get("document_type"),
                            "document_number": doc.get("document_number"),
                            "document_year": doc.get("document_year"),
                            "publication_date": publication_issue.get("publication_date"),
                        },
                    },
                    **coll,
                }
            )
            self._check_required("document", doc, missing_required)

        parsed = {
            "file": str(html_path),
            "page_url": page_url,
            "publication_issue": publication_issue,
            "documents": parsed_docs,
        }

        return FileResult(
            file=str(html_path),
            page_url=page_url,
            document_count=len(parsed_docs),
            suspicious_split=len(parsed_docs) > 20,
            missing_required=missing_required,
            empty_body_count=empty_body_count,
            duplicate_identity_count=duplicate_identity,
            heuristics_only_fields=sorted(heur_only),
            parsed=parsed,
        )

    def run_folder(self, html_dir: Path) -> ExtractRunResult:
        out = ExtractRunResult()
        for p in sorted(html_dir.rglob("*.html")):
            out.files.append(self.run_file(p))
        out.selector_stats = self.selector_stats
        return out

    def _canonical_url(self, tags: list[HtmlTag]) -> str | None:
        links = [t for t in tags if t.name == "link" and t.attrs.get("rel", "") == "canonical"]
        return find_first_attr(links, "href")

    def _split_documents(self, tags: list[HtmlTag]) -> list[list[HtmlTag]]:
        split_cfg = (((self.rules.extract.get("page") or {}).get("split") or {}).get("documents") or {})
        selectors = list(split_cfg.get("boundary_selectors") or ["h2, h3, h4, h5", "strong", "p"])
        starts_re = [re.compile(p) for p in (((self.rules.heuristics.get("split") or {}).get("document_start_patterns") or []))]

        blocks: list[HtmlTag] = []
        seen: set[int] = set()
        for sel in selectors:
            for t in select_tags(tags, sel):
                if t.order in seen:
                    continue
                seen.add(t.order)
                blocks.append(t)
        blocks.sort(key=lambda x: x.order)

        if not blocks:
            return [tags]

        starts = []
        if starts_re:
            for i, b in enumerate(blocks):
                if any(r.search(b.text) for r in starts_re):
                    starts.append(i)

        if not starts:
            return [blocks]

        docs: list[list[HtmlTag]] = []
        starts = sorted(set(starts))
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(blocks)
            seg = blocks[s:e]
            if seg:
                docs.append(seg)
        return docs if docs else [blocks]

    def _extract_publication_issue(self, tags: list[HtmlTag], page_url: str | None) -> dict[str, Any]:
        entity = (((self.rules.extract.get("entities") or {}).get("publication_issue") or {}).get("scalars") or {})
        out: dict[str, Any] = {}
        for field, cfg in entity.items():
            out[field] = self._extract_scalar(tags, cfg.get("selectors") or [], None, page_url)
        return out

    def _extract_document(self, doc_tags: list[HtmlTag]) -> dict[str, Any]:
        entity = (((self.rules.extract.get("entities") or {}).get("document") or {}).get("scalars") or {})
        out: dict[str, Any] = {}
        for field, cfg in entity.items():
            out[field] = self._extract_scalar(doc_tags, cfg.get("selectors") or [], doc_tags, None)

        joined = "\n".join(self._doc_paragraphs(doc_tags))
        if out.get("document_number") is None:
            m = re.search(r"(?i)\b(n[ºo\.]?\s*\d+[\./-]?\d*)\b", joined)
            out["document_number"] = m.group(1) if m else None
        if out.get("document_year") is None:
            m = re.search(r"\b(19|20)\d{2}\b", joined)
            out["document_year"] = int(m.group(0)) if m else None
        return out

    def _extract_collections(self, doc_tags: list[HtmlTag]) -> dict[str, Any]:
        paragraphs = self._doc_paragraphs(doc_tags)
        text_blob = "\n".join(paragraphs)

        participants = []
        role_map = (((self.rules.heuristics.get("classify") or {}).get("participant_role") or {}).get("patterns") or {})
        role_regs = {k: re.compile(v) for k, v in role_map.items()}
        name_re = re.compile(r"(?i)([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\.-]{4,})")
        rep_re = re.compile(r"(?i)\b(em nome de|representando|patrono de)\b\s*(.*)$")
        org_re = re.compile(r"(?i)\b(ministerio|secretaria|agencia|tribunal|conselho|prefeitura)\b")
        for p in paragraphs:
            role = next((rk for rk, rr in role_regs.items() if rr.search(p)), None)
            if not role:
                continue
            nm = name_re.search(p)
            if not nm:
                continue
            rep = rep_re.search(p)
            participants.append(
                {
                    "person_name": nm.group(1).strip(),
                    "role_label": role,
                    "organization_name": p if org_re.search(p) else None,
                    "represents_entity": rep.group(2).strip() if rep else None,
                }
            )

        signatures = []
        sig_regs = [
            re.compile(r"(?i)^assinado por:\s*(.+)$"),
            re.compile(r"(?i)^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÇ\s\.-]{4,})$"),
        ]
        role_title_re = re.compile(r"(?i)\b(ministro|diretor|secretario|presidente|relator)\b.*$")
        for i, p in enumerate(paragraphs, start=1):
            person = None
            for rr in sig_regs:
                m = rr.search(p.strip())
                if m:
                    person = m.group(1).strip()
                    break
            if not person:
                continue
            rt = role_title_re.search(p)
            signatures.append(
                {
                    "person_name": person,
                    "role_title": rt.group(0).strip() if rt else None,
                    "sequence_in_document": i,
                }
            )

        refs = []
        ref_re = re.compile(
            r"(?i)\b(lei\s*n?[ºo\.]?\s*\d+[\./]?\d*|decreto\s*n?[ºo\.]?\s*\d+[\./]?\d*|art\.\s*\d+|constituicao federal|sumula\s*\d+|resolucao\s*n?[ºo\.]?\s*\d+)\b"
        )
        for m in ref_re.finditer(text_blob):
            txt = m.group(1)
            refs.append(
                {
                    "reference_text": txt,
                    "reference_type": self._reference_type(txt),
                    "reference_category": self._reference_category(txt),
                    "normalized_identifier": self._norm_ref(txt),
                }
            )

        procedures = []
        ptype_re = re.compile(
            r"(?i)\b(adi|adc|adpf|re|resp|pet|processo administrativo|licitacao|pregao|concorrencia)\b"
        )
        pid_re = re.compile(r"(?i)\b\d{3,}(?:[\./-]\w+)*\b")
        jur_re = re.compile(r"(?i)\b(stf|stj|tst|trf\d|tj\w+|df|sp|rj|mg|rs|pr|sc|ba)\b")
        for p in paragraphs:
            tm = ptype_re.search(p)
            im = pid_re.search(p)
            if not (tm and im):
                continue
            jm = jur_re.search(p)
            procedures.append(
                {
                    "procedure_type": tm.group(1).lower(),
                    "procedure_identifier": im.group(0),
                    "jurisdiction": jm.group(1).upper() if jm else None,
                }
            )

        events = []
        et_re = re.compile(
            r"(?i)\b(decisao|deliberacao|homologacao|revogacao|aprovacao|promulgacao|suspensao|votacao)\b"
        )
        ed_re = [
            re.compile(r"(?i)\b\d{1,2}/\d{1,2}/\d{4}\b"),
            re.compile(r"(?i)\b\d{4}-\d{2}-\d{2}\b"),
        ]
        sp_re = re.compile(r"(?i)(sessao\s+de\s+\d{1,2}\s+de\s+[a-zç]+\s+de\s+\d{4})")
        out_re = re.compile(r"(?i)\b(provido|improvido|deferido|indeferido|homologado|arquivado)\b")
        seq = 0
        for p in paragraphs:
            tm = et_re.search(p)
            if not tm:
                continue
            seq += 1
            dm = next((r.search(p) for r in ed_re if r.search(p)), None)
            sm = sp_re.search(p)
            om = out_re.search(p)
            events.append(
                {
                    "event_type": tm.group(1).lower(),
                    "event_date": dm.group(0) if dm else None,
                    "session_period": sm.group(1) if sm else None,
                    "event_text": p,
                    "outcome": om.group(1).lower() if om else None,
                    "sequence_in_document": seq,
                }
            )

        return {
            "document_participant": self._dedup(participants, ["person_name", "role_label"]),
            "document_signature": self._dedup(signatures, ["person_name", "role_title"]),
            "normative_reference": self._dedup(refs, ["reference_text"]),
            "procedure_reference": self._dedup(procedures, ["procedure_type", "procedure_identifier"]),
            "document_event": self._dedup(events, ["event_type", "event_text"]),
        }

    def _extract_scalar(
        self,
        tags: list[HtmlTag],
        selectors: list[str],
        context: list[HtmlTag] | None,
        page_url: str | None,
    ) -> Any:
        for raw in selectors:
            stat = self.selector_stats.setdefault(raw, SelectorStat())
            stat.attempts += 1

            val = self._resolve_selector(raw, tags, context, page_url)
            if val is not None and str(val).strip() != "":
                stat.successes += 1
                return self._cleanup(str(val))
        return None

    def _resolve_selector(
        self,
        selector: str,
        tags: list[HtmlTag],
        context: list[HtmlTag] | None,
        page_url: str | None,
    ) -> Any:
        if selector == "__page.url":
            return page_url

        if context is not None and selector.startswith("__document."):
            return self._resolve_doc_token(selector, context)

        css, attr = parse_attr_selector(selector)
        base, contains = parse_contains_selector(css)
        nodes = select_tags(tags, base)
        if contains:
            nodes = [n for n in nodes if contains.lower() in n.text.lower()]
        if not nodes:
            return None

        if attr:
            return find_first_attr(nodes, attr)
        return nodes[0].text

    def _resolve_doc_token(self, token: str, context: list[HtmlTag]) -> Any:
        if token == "__document.heading":
            for n in context:
                if n.name in {"h1", "h2", "h3", "h4", "h5"}:
                    return n.text
            return None
        if token == "__document.first_strong":
            for n in context:
                if n.name == "strong":
                    return n.text
            return None
        if token == "__document.paragraphs":
            return "\n".join(self._doc_paragraphs(context))
        if token == "__document.paragraphs[0]":
            p = self._doc_paragraphs(context)
            return p[0] if p else None
        if token == "__document.first_nonempty_paragraph":
            for p in self._doc_paragraphs(context):
                if p:
                    return p
            return None
        if token == "__document.heading_context":
            return "\n".join([n.text for n in context[:5] if n.text])
        if token == "__document.trailing_paragraphs":
            p = self._doc_paragraphs(context)
            return "\n".join(p[-5:]) if p else None
        return None

    def _doc_paragraphs(self, nodes: list[HtmlTag]) -> list[str]:
        out = [n.text for n in nodes if n.name == "p" and n.text]
        if out:
            return out
        return [n.text for n in nodes if n.text]

    def _check_required(self, entity: str, row: dict[str, Any], bag: list[str]) -> None:
        for field, required in self.rules.required_fields.get(entity, {}).items():
            if required and row.get(field) in (None, ""):
                bag.append(f"{entity}.{field}")

    def _stable_identity(self, doc: dict[str, Any]) -> str:
        parts = [
            str(doc.get("document_type") or ""),
            str(doc.get("document_number") or ""),
            str(doc.get("document_year") or ""),
            str(doc.get("title") or ""),
            str(doc.get("issuing_organ") or ""),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    def _reference_type(self, text: str) -> str:
        t = text.lower()
        if "lei" in t:
            return "law"
        if "decreto" in t:
            return "regulation"
        if "sumula" in t:
            return "precedent"
        if "art." in t or "artigo" in t:
            return "article"
        return "unknown"

    def _reference_category(self, text: str) -> str:
        t = text.lower()
        if "lei" in t:
            return "law"
        if "constituicao" in t:
            return "constitution"
        if "sumula" in t or "precedente" in t or "tema" in t:
            return "precedent"
        if any(k in t for k in ["decreto", "portaria", "instrucao normativa", "resolucao"]):
            return "regulation"
        if "art." in t or "artigo" in t:
            return "article"
        if "tratado" in t or "convencao" in t:
            return "treaty"
        return "unknown"

    def _norm_ref(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def _dedup(self, rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        out: list[dict[str, Any]] = []
        for r in rows:
            k = tuple(r.get(x) for x in keys)
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    def _cleanup(self, value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()
