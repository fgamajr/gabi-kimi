from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from typing import Any

from validation.extractor import ExtractRunResult


def write_report(run: ExtractRunResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir = out_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    suspicious_dir = out_dir / "suspicious_pages"
    suspicious_dir.mkdir(parents=True, exist_ok=True)

    # per-file parsed output
    for fr in run.files:
        stem = _safe_stem(fr.file)
        (parsed_dir / f"{stem}.json").write_text(
            json.dumps(fr.parsed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if fr.suspicious_split or fr.missing_required or fr.empty_body_count > 0:
            (suspicious_dir / f"{stem}.json").write_text(
                json.dumps(
                    {
                        "file": fr.file,
                        "document_count": fr.document_count,
                        "suspicious_split": fr.suspicious_split,
                        "missing_required": fr.missing_required,
                        "empty_body_count": fr.empty_body_count,
                        "duplicate_identity_count": fr.duplicate_identity_count,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    stats = _compute_stats(run)
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    _write_field_coverage_csv(run, out_dir / "field_coverage.csv")
    _write_selector_reliability_csv(run, out_dir / "selector_reliability.csv")
    _write_anomalies_md(run, stats, out_dir / "anomalies.md")


def _compute_stats(run: ExtractRunResult) -> dict[str, Any]:
    total_pages = len(run.files)
    doc_counts = [f.document_count for f in run.files]
    total_docs = sum(doc_counts)
    return {
        "total_pages": total_pages,
        "total_documents": total_docs,
        "pages_with_zero_documents": sum(1 for x in doc_counts if x == 0),
        "pages_with_gt_20_documents": sum(1 for x in doc_counts if x > 20),
        "avg_documents_per_page": (total_docs / total_pages) if total_pages else 0,
        "total_empty_body": sum(f.empty_body_count for f in run.files),
        "total_missing_required": sum(len(f.missing_required) for f in run.files),
        "total_duplicate_identities": sum(f.duplicate_identity_count for f in run.files),
    }


def _write_field_coverage_csv(run: ExtractRunResult, path: Path) -> None:
    present = Counter()
    empty = Counter()
    heur = Counter()
    total = Counter()

    for fr in run.files:
        for d in fr.parsed.get("documents", []):
            doc = d.get("document") or {}
            for k, v in doc.items():
                total[f"document.{k}"] += 1
                if v is None or str(v).strip() == "":
                    empty[f"document.{k}"] += 1
                else:
                    present[f"document.{k}"] += 1
            for hf in fr.heuristics_only_fields:
                heur[hf] += 1

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["field", "present", "empty", "total", "presence_pct", "heuristics_only_count"])
        for field in sorted(total.keys()):
            t = total[field]
            p = present[field]
            e = empty[field]
            pct = (p / t * 100) if t else 0
            w.writerow([field, p, e, t, f"{pct:.2f}", heur[field]])


def _write_selector_reliability_csv(run: ExtractRunResult, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["selector", "attempts", "successes", "success_rate_pct"])
        for sel in sorted(run.selector_stats.keys()):
            st = run.selector_stats[sel]
            rate = (st.successes / st.attempts * 100) if st.attempts else 0
            w.writerow([sel, st.attempts, st.successes, f"{rate:.2f}"])


def _write_anomalies_md(run: ExtractRunResult, stats: dict[str, Any], path: Path) -> None:
    lines = ["# Structural Reliability Report", "", "## Summary"]
    for k, v in stats.items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## Per-file anomalies"]
    any_anomaly = False
    for fr in run.files:
        problems = []
        if fr.document_count == 0:
            problems.append("0 documents")
        if fr.suspicious_split:
            problems.append(f"suspicious split ({fr.document_count} docs)")
        if fr.empty_body_count > 0:
            problems.append(f"empty body_text={fr.empty_body_count}")
        if fr.duplicate_identity_count > 0:
            problems.append(f"duplicate identities={fr.duplicate_identity_count}")
        if fr.missing_required:
            problems.append(f"missing required={len(fr.missing_required)}")
        if not problems:
            continue
        any_anomaly = True
        lines.append(f"- `{fr.file}`: " + ", ".join(problems))

    if not any_anomaly:
        lines.append("- none")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _safe_stem(path_str: str) -> str:
    return path_str.replace("/", "_").replace("\\", "_").replace(":", "_")
