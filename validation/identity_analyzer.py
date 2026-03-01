from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from difflib import SequenceMatcher
from typing import Any

import yaml


@dataclass(slots=True)
class IdentityConfig:
    strategies: list[dict[str, Any]]
    content_canonicalize: list[str]
    occurrence_inputs: list[str]
    edition_inputs: list[str]


def load_identity_config(path: str | Path, source_id: str = "dou") -> IdentityConfig:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    identity = None
    if isinstance(data, dict) and "sources" in data:
        src = (data.get("sources") or {}).get(source_id) or {}
        identity = src.get("identity")
    if identity is None:
        identity = data.get("identity") if isinstance(data, dict) else None
    if not isinstance(identity, dict):
        raise ValueError(f"identity block not found for source '{source_id}' in {p}")

    natural = identity.get("natural_key") or {}
    hashes = identity.get("hashes") or {}
    content = hashes.get("content_hash") or {}
    occurrence = hashes.get("occurrence_hash") or {}
    edition = identity.get("edition_id") or {}

    strategies = list(natural.get("strategies") or [])
    if not strategies:
        raise ValueError("identity.natural_key.strategies is required")

    return IdentityConfig(
        strategies=strategies,
        content_canonicalize=list(content.get("canonicalize") or []),
        occurrence_inputs=list(occurrence.get("inputs") or []),
        edition_inputs=list(edition.get("inputs") or []),
    )


def analyze_identity(parsed_dir: Path, cfg: IdentityConfig, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_records(parsed_dir, cfg)

    groups = _identity_groups(records)
    splits = _suspicious_splits(records)
    false_versions = _false_versions(records)
    false_occ = _false_occurrences(records)
    strat = _strategy_distribution(records)

    (out_dir / "identity_groups.json").write_text(
        json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "suspicious_splits.json").write_text(
        json.dumps(splits, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "false_versions.json").write_text(
        json.dumps(false_versions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "false_occurrences.json").write_text(
        json.dumps(false_occ, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_strategy_csv(strat, out_dir / "strategy_distribution.csv")

    summary = _summary(records, strat, groups, splits, false_versions, false_occ)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")
    return {
        "records": len(records),
        "groups": len(groups.get("groups", [])),
        "fallback_pct": strat.get("fallback_pct", 0.0),
        "suspicious_split_events": splits.get("summary", {}).get("total", 0),
    }


def _load_records(parsed_dir: Path, cfg: IdentityConfig) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fp in sorted(parsed_dir.glob("*.json")):
        data = json.loads(fp.read_text(encoding="utf-8"))
        page_url = str(data.get("page_url") or "")
        pub = data.get("publication_issue") or {}
        pub_norm = {k: _norm(pub.get(k)) for k in pub.keys()}
        docs = data.get("documents") or []
        for i, row in enumerate(docs, start=1):
            doc = row.get("document") or {}
            doc_norm = {k: _norm(v) for k, v in doc.items()}
            source = {
                "file": data.get("file"),
                "page_url": page_url,
                "doc_index": i,
            }
            rec = _hash_record(doc_norm, pub_norm, source, cfg)
            rec["raw"] = {
                "title": doc.get("title"),
                "document_number": doc.get("document_number"),
                "document_year": doc.get("document_year"),
                "document_type": doc.get("document_type"),
                "publication_date": pub.get("publication_date"),
            }
            out.append(rec)
    return out


def _hash_record(doc: dict[str, str], pub: dict[str, str], source: dict[str, Any], cfg: IdentityConfig) -> dict[str, Any]:
    strategy_name = "none"
    strategy_values: list[str] = []
    for s in cfg.strategies:
        name = str(s.get("name") or "unnamed")
        fields = list(s.get("inputs") or [])
        vals = [_field_value(f, doc, pub, source) for f in fields]
        if all(v for v in vals):
            strategy_name = name
            strategy_values = vals
            break
    natural_key_hash = _sha(strategy_name + "|" + "|".join(strategy_values))

    body_text = _field_value("body_text_semantic", doc, pub, source)
    body_text = _canonicalize_content(body_text, cfg.content_canonicalize)
    content_hash = _sha(body_text)

    edition_vals = [_field_value(f, doc, pub, source) for f in cfg.edition_inputs]
    edition_id = _sha("|".join(edition_vals))
    occurrence_vals = []
    for f in cfg.occurrence_inputs:
        if f == "edition_id":
            occurrence_vals.append(edition_id)
        else:
            occurrence_vals.append(_field_value(f, doc, pub, source))
    occurrence_hash = _sha("|".join(occurrence_vals))

    return {
        "natural_key_hash": natural_key_hash,
        "content_hash": content_hash,
        "occurrence_hash": occurrence_hash,
        "strategy": strategy_name,
        "edition_id": edition_id,
        "body_text_semantic": body_text,
        "source_url_canonical": _field_value("source_url_canonical", doc, pub, source),
        "doc_number": _field_value("document_number", doc, pub, source),
        "doc_year": _field_value("document_year", doc, pub, source),
        "title": _field_value("title_normalized", doc, pub, source),
        "source_file": source.get("file"),
    }


def _identity_groups(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for r in records:
        g = groups.setdefault(
            r["natural_key_hash"],
            {
                "natural_key_hash": r["natural_key_hash"],
                "distinct_content_hashes": set(),
                "distinct_occurrence_hashes": set(),
                "titles": set(),
                "years": set(),
                "files": set(),
            },
        )
        g["distinct_content_hashes"].add(r["content_hash"])
        g["distinct_occurrence_hashes"].add(r["occurrence_hash"])
        if r.get("title"):
            g["titles"].add(r["title"])
        if r.get("doc_year"):
            g["years"].add(r["doc_year"])
        if r.get("source_file"):
            g["files"].add(r["source_file"])

    out = []
    for g in groups.values():
        out.append(
            {
                "natural_key_hash": g["natural_key_hash"],
                "distinct_content_hashes": len(g["distinct_content_hashes"]),
                "distinct_occurrence_hashes": len(g["distinct_occurrence_hashes"]),
                "titles": sorted(g["titles"]),
                "years": sorted(g["years"]),
                "files": len(g["files"]),
            }
        )
    out.sort(key=lambda x: (-x["distinct_occurrence_hashes"], -x["distinct_content_hashes"]))
    return {"groups": out}


def _suspicious_splits(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_title: dict[str, set[str]] = {}
    by_num_year: dict[tuple[str, str], set[str]] = {}
    for r in records:
        t = r.get("title") or ""
        if t:
            by_title.setdefault(t, set()).add(r["natural_key_hash"])
        n = r.get("doc_number") or ""
        y = r.get("doc_year") or ""
        if n and y:
            by_num_year.setdefault((n, y), set()).add(r["natural_key_hash"])

    title_splits = [
        {"title": t, "natural_key_hashes": sorted(list(hs)), "count": len(hs)}
        for t, hs in by_title.items()
        if len(hs) > 1
    ]
    num_splits = [
        {"document_number": n, "document_year": y, "natural_key_hashes": sorted(list(hs)), "count": len(hs)}
        for (n, y), hs in by_num_year.items()
        if len(hs) > 1
    ]
    return {
        "summary": {
            "same_title_diff_natural_key": len(title_splits),
            "same_number_year_diff_natural_key": len(num_splits),
            "total": len(title_splits) + len(num_splits),
        },
        "same_title_diff_natural_key": title_splits,
        "same_number_year_diff_natural_key": num_splits,
    }


def _false_versions(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_nk: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_nk.setdefault(r["natural_key_hash"], []).append(r)

    findings: list[dict[str, Any]] = []
    for nk, rows in by_nk.items():
        by_content: dict[str, dict[str, Any]] = {}
        for r in rows:
            by_content.setdefault(r["content_hash"], r)
        ch = list(by_content.values())
        if len(ch) < 2:
            continue
        for i in range(len(ch)):
            for j in range(i + 1, len(ch)):
                a, b = ch[i], ch[j]
                ta = a.get("body_text_semantic") or ""
                tb = b.get("body_text_semantic") or ""
                ratio = SequenceMatcher(None, ta, tb).ratio() if ta or tb else 1.0
                if ratio >= 0.995:
                    findings.append(
                        {
                            "natural_key_hash": nk,
                            "content_hash_a": a["content_hash"],
                            "content_hash_b": b["content_hash"],
                            "similarity_ratio": round(ratio, 6),
                            "classification": "small_edit_distance",
                        }
                    )
    return {"false_versions": findings, "count": len(findings)}


def _false_occurrences(records: list[dict[str, Any]]) -> dict[str, Any]:
    same_edition_content: dict[tuple[str, str], set[str]] = {}
    same_url: dict[str, set[str]] = {}
    for r in records:
        same_edition_content.setdefault((r["edition_id"], r["content_hash"]), set()).add(r["occurrence_hash"])
        u = r.get("source_url_canonical") or ""
        if u:
            same_url.setdefault(u, set()).add(r["occurrence_hash"])

    occ_splits = [
        {
            "edition_id": e,
            "content_hash": c,
            "occurrence_hashes": sorted(list(hs)),
            "count": len(hs),
        }
        for (e, c), hs in same_edition_content.items()
        if len(hs) > 1
    ]
    url_splits = [
        {"source_url_canonical": u, "occurrence_hashes": sorted(list(hs)), "count": len(hs)}
        for u, hs in same_url.items()
        if len(hs) > 1
    ]
    return {
        "same_edition_same_text_diff_occurrence_hash": occ_splits,
        "same_url_across_occurrence_hashes": url_splits,
        "count": len(occ_splits) + len(url_splits),
    }


def _strategy_distribution(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for r in records:
        s = r.get("strategy") or "none"
        counts[s] = counts.get(s, 0) + 1
    total = len(records)
    rows = []
    for k in sorted(counts.keys()):
        c = counts[k]
        pct = (c / total * 100.0) if total else 0.0
        rows.append({"strategy": k, "count": c, "percentage": round(pct, 2)})
    fallback = counts.get("fallback", 0)
    none = counts.get("none", 0)
    return {
        "rows": rows,
        "total": total,
        "fallback_pct": (fallback / total * 100.0) if total else 0.0,
        "none_pct": (none / total * 100.0) if total else 0.0,
        "unreliable_pct": ((fallback + none) / total * 100.0) if total else 0.0,
    }


def _write_strategy_csv(stats: dict[str, Any], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "count", "percentage"])
        for r in stats.get("rows", []):
            w.writerow([r["strategy"], r["count"], f"{r['percentage']:.2f}"])


def _summary(
    records: list[dict[str, Any]],
    strat: dict[str, Any],
    groups: dict[str, Any],
    splits: dict[str, Any],
    false_versions: dict[str, Any],
    false_occ: dict[str, Any],
) -> str:
    lines = [
        "# Identity Summary",
        "",
        f"- documents_analyzed: {len(records)}",
        f"- identity_groups: {len(groups.get('groups', []))}",
        f"- suspicious_splits_total: {splits.get('summary', {}).get('total', 0)}",
        f"- false_versions_total: {false_versions.get('count', 0)}",
        f"- false_occurrences_total: {false_occ.get('count', 0)}",
        f"- fallback_usage_pct: {strat.get('fallback_pct', 0.0):.2f}",
        f"- strategy_none_pct: {strat.get('none_pct', 0.0):.2f}",
        f"- unreliable_strategy_pct (fallback+none): {strat.get('unreliable_pct', 0.0):.2f}",
        "",
        "## Strategy Distribution",
        "",
        "| strategy | count | percentage |",
        "|---|---:|---:|",
    ]
    for r in strat.get("rows", []):
        lines.append(f"| {r['strategy']} | {r['count']} | {r['percentage']:.2f}% |")
    lines.append("")
    return "\n".join(lines) + "\n"


def _field_value(field: str, doc: dict[str, str], pub: dict[str, str], source: dict[str, Any]) -> str:
    if field == "issuing_organ_normalized":
        return doc.get("issuing_organ") or doc.get("issuing_authority") or ""
    if field == "title_normalized":
        return doc.get("title") or ""
    if field == "body_text_first_200_chars_normalized":
        return (doc.get("body_text") or "")[:200]
    if field == "body_text_semantic":
        return doc.get("body_text") or ""
    if field == "source_url_canonical":
        u = str(source.get("page_url") or "")
        return re.sub(r"[?#].*$", "", u)
    if field in {"publication_date", "edition_number", "edition_section", "page_number"}:
        return pub.get(field) or ""
    if field in doc:
        return doc.get(field) or ""
    return ""


def _canonicalize_content(text: str, steps: list[str]) -> str:
    out = text or ""
    for s in steps:
        if s == "remove_signature_blocks":
            out = re.sub(r"(?is)assinado por:.*$", "", out).strip()
        elif s == "normalize_whitespace":
            out = re.sub(r"\s+", " ", out).strip()
        elif s == "normalize_quotes":
            out = out.replace("“", '"').replace("”", '"').replace("’", "'").replace("`", "'")
        elif s == "remove_page_headers":
            out = re.sub(r"(?im)^\s*di[aá]rio oficial da uni[aã]o.*$", "", out)
    return out


def _norm(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()
