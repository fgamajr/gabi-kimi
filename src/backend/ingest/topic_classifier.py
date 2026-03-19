"""Deterministic rules-based topic classifier for DOU documents.

Assigns 1-3 topic tags per document using art_type, issuing_organ,
and the first 512 chars of body text + ementa. No ML — pure keyword
matching for speed and predictability.

CLI:
    python -m src.backend.ingest.topic_classifier --pending   # backfill unclassified docs
    python -m src.backend.ingest.topic_classifier --stats     # show classification coverage
    python -m src.backend.ingest.topic_classifier --sample 20 # classify 20 random docs for review
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

TOPICS = [
    "concurso_selecao",
    "licitacao_compras",
    "contrato_convenio",
    "pessoal_rh",
    "regulacao_norma",
    "consulta_participacao",
    "saude",
    "educacao",
    "meio_ambiente",
    "financeiro",
    "energia_telecom",
    "administrativo",
]

_SPACE_RE = re.compile(r"\s+")


def _norm(text: str | None) -> str:
    """Lowercase, ASCII-fold, collapse whitespace."""
    if not text:
        return ""
    s = unicodedata.normalize("NFD", str(text))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return _SPACE_RE.sub(" ", s).lower().strip()


def _has_any(text: str, terms: list[str]) -> bool:
    return any(t in text for t in terms)


def classify_document(
    identifica: str,
    ementa: str,
    texto: str,
    art_type_normalized: str,
    issuing_organ: str,
) -> list[str]:
    """Classify a DOU document into 1-3 topic tags using deterministic rules."""
    art = _norm(art_type_normalized)
    organ = _norm(issuing_organ)
    # Combine identifica + ementa + art_type + first 512 chars of texto for matching
    combined = _norm(identifica) + " " + _norm(ementa) + " " + art + " " + _norm(texto[:512])

    def _art_is(*keywords: str) -> bool:
        """Check if art_type contains any of the keywords (handles compound types).
        Uses word boundary matching to avoid 'ato' matching 'contrato'."""
        return any(re.search(r'\b' + re.escape(k) + r'\b', art) for k in keywords)

    topics: list[str] = []

    # --- Function topics (what the doc DOES) ---

    # concurso_selecao
    if _art_is("edital", "aviso", "portaria", "resultado", "resultados", "extrato") and _has_any(
        combined,
        ["concurso", "processo seletivo", "selecao publica", "vestibular", "homologacao do resultado"],
    ) and not _has_any(
        combined,
        ["chamada publica", "chamamento", "agricultura familiar", "pnae", "alimentacao escolar"],
    ):
        topics.append("concurso_selecao")

    # licitacao_compras
    if _art_is("edital", "aviso", "pregao", "extrato", "resultado", "resultados") and _has_any(
        combined,
        [
            "licitacao", "pregao", "dispensa", "inexigibilidade",
            "chamada publica", "chamamento", "registro de precos",
            "tomada de precos", "concorrencia",
        ],
    ):
        topics.append("licitacao_compras")

    # contrato_convenio
    if _has_any(art, ["contrato", "convenio"]) or _has_any(
        combined,
        ["extrato de contrato", "termo aditivo", "extrato de convenio", "extrato do contrato", "extrato do convenio"],
    ):
        topics.append("contrato_convenio")

    # pessoal_rh
    if _has_any(
        combined,
        [
            "nomeacao", "exoneracao", "aposentadoria", "pensao",
            "designacao", "cessao", "ferias", "licenca",
            "vacancia", "redistribuicao", "remocao",
        ],
    ) and (not art or _art_is("portaria", "decreto", "ato", "despacho", "apostila")):
        topics.append("pessoal_rh")

    # regulacao_norma
    if _art_is("lei", "decreto", "resolucao", "instrucao normativa", "medida provisoria", "emenda constitucional", "deliberacao"):
        topics.append("regulacao_norma")

    # consulta_participacao
    if _has_any(combined, ["consulta publica", "audiencia publica"]):
        topics.append("consulta_participacao")

    # --- Subject topics (what the doc is ABOUT) ---

    # saude
    if _has_any(organ, ["anvisa", "saude", "ministerio da saude", "sus"]) or _has_any(
        combined, ["medicamento", "vigilancia sanitaria", "registro de medicamento"],
    ):
        topics.append("saude")

    # educacao
    if _has_any(organ, ["mec", "educacao", "capes", "cnpq", "universidade", "instituto federal"]):
        topics.append("educacao")

    # meio_ambiente
    if _has_any(organ, ["ibama", "icmbio", "meio ambiente"]) or _has_any(
        combined, ["licenciamento ambiental", "estudo de impacto ambiental"],
    ):
        topics.append("meio_ambiente")

    # financeiro
    if _has_any(organ, ["banco central", "bcb", "cvm", "receita federal", "rfb", "tesouro nacional"]) or _has_any(
        combined, ["irpf", "imposto de renda", "cambio"],
    ):
        topics.append("financeiro")

    # energia_telecom
    if _has_any(organ, ["aneel", "anatel", "anp", "agencia nacional de energia"]) or _has_any(
        combined, ["tarifa de energia", "espectro de radiofrequencia"],
    ):
        topics.append("energia_telecom")

    # Catch-all
    if not topics:
        topics.append("administrativo")

    # Cap at 3 topics
    return topics[:3]


# ---------------------------------------------------------------------------
# CLI: backfill, stats, sample
# ---------------------------------------------------------------------------


def _get_mongo_collection() -> Any:
    from src.backend.core.config import settings
    from pymongo import MongoClient

    client: Any = MongoClient(settings.MONGO_STRING)
    db = client[settings.DB_NAME]
    return db["documents"]


def _backfill_pending() -> None:
    import time
    from datetime import datetime, timezone

    import sys

    collection = _get_mongo_collection()
    print("Starting backfill (skipping initial count for speed)...", flush=True)

    batch_size = 5000
    classified = 0
    batch_num = 0

    while True:
        cursor = collection.find(
            {"topics": {"$exists": False}},
            {"identifica": 1, "ementa": 1, "texto": 1, "art_type_normalized": 1, "issuing_organ": 1},
        ).limit(batch_size)

        docs = list(cursor)
        if not docs:
            break

        batch_num += 1
        ops = []
        from pymongo import UpdateOne

        for doc in docs:
            topics = classify_document(
                identifica=doc.get("identifica") or "",
                ementa=doc.get("ementa") or "",
                texto=doc.get("texto") or "",
                art_type_normalized=doc.get("art_type_normalized") or "",
                issuing_organ=doc.get("issuing_organ") or "",
            )
            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"topics": topics, "updated_at": datetime.now(timezone.utc)}},
                )
            )

        if ops:
            collection.bulk_write(ops, ordered=False)
            classified += len(ops)

        print(f"  batch {batch_num}: classified {len(ops)} docs (total: {classified:,})", flush=True)
        time.sleep(0.5)

    print(f"Done. Classified {classified:,} documents.", flush=True)


def _show_stats() -> None:
    collection = _get_mongo_collection()
    total = collection.estimated_document_count()
    print(f"Counting classified docs (may take a minute)...", flush=True)
    classified = collection.count_documents({"topics": {"$exists": True}})
    unclassified = total - classified
    pct = (classified / total * 100) if total else 0
    print(f"Total documents:      {total:,}")
    print(f"Classified:           {classified:,} ({pct:.1f}%)")
    print(f"Unclassified:         {unclassified:,}")

    if classified > 0:
        print("\nTopic distribution:")
        pipeline = [
            {"$match": {"topics": {"$exists": True}}},
            {"$unwind": "$topics"},
            {"$group": {"_id": "$topics", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        for row in collection.aggregate(pipeline):
            print(f"  {row['_id']:30s} {row['count']:>10,}")


def _sample(n: int) -> None:
    collection = _get_mongo_collection()
    pipeline = [
        {"$sample": {"size": n}},
        {"$project": {"identifica": 1, "ementa": 1, "texto": 1, "art_type_normalized": 1, "issuing_organ": 1}},
    ]
    for doc in collection.aggregate(pipeline):
        topics = classify_document(
            identifica=doc.get("identifica") or "",
            ementa=doc.get("ementa") or "",
            texto=doc.get("texto") or "",
            art_type_normalized=doc.get("art_type_normalized") or "",
            issuing_organ=doc.get("issuing_organ") or "",
        )
        title = (doc.get("identifica") or "(sem título)")[:80]
        organ = (doc.get("issuing_organ") or "")[:40]
        art = doc.get("art_type_normalized") or ""
        print(f"  [{art:20s}] {title}")
        print(f"    organ: {organ}")
        print(f"    topics: {topics}")
        print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DOU document topic classifier")
    parser.add_argument("--pending", action="store_true", help="Backfill unclassified Mongo docs")
    parser.add_argument("--stats", action="store_true", help="Show classification coverage")
    parser.add_argument("--sample", type=int, metavar="N", help="Classify N random docs for review")
    args = parser.parse_args()

    if args.pending:
        _backfill_pending()
    elif args.stats:
        _show_stats()
    elif args.sample:
        _sample(args.sample)
    else:
        parser.print_help()
