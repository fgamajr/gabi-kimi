from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from src.backend.core.config import settings

logger = logging.getLogger(__name__)

_STALENESS_THRESHOLD_HOURS = 48

_SOURCE_QUERIES: dict[str, tuple[str, str]] = {
    "dou": (
        settings.ES_INDEX,
        '{"size":0,"aggs":{"last":{"max":{"field":"pub_date"}}}}',
    ),
    "tcu_acordaos": (
        settings.TCU_ES_INDEX,
        '{"size":0,"aggs":{"last":{"max":{"field":"data_sessao"}}}}',
    ),
    "tcu_normas": (
        settings.TCU_NORMAS_INDEX,
        '{"size":0,"aggs":{"last":{"max":{"field":"data_inicio_vigencia"}}}}',
    ),
    "tcu_publicacoes": (
        settings.TCU_PUBLICACOES_INDEX,
        '{"size":0,"aggs":{"last":{"max":{"field":"pub_date"}}}}',
    ),
}


@dataclass(frozen=True)
class SourceFreshness:
    name: str
    last_indexed: datetime | None
    stale: bool
    gap_hours: float | None


@dataclass(frozen=True)
class CorpusFreshness:
    sources: tuple[SourceFreshness, ...]
    any_stale: bool
    checked_at: datetime

    def disclaimer(self) -> str | None:
        stale = [s.name for s in self.sources if s.stale]
        if not stale:
            return None
        return (
            f"Aviso: os índices {', '.join(stale)} podem estar desatualizados "
            f"(última indexação há mais de {_STALENESS_THRESHOLD_HOURS}h). "
            "Verifique as publicações recentes diretamente no DOU/TCU."
        )


async def check_corpus_freshness(
    client: httpx.AsyncClient | None = None,
) -> CorpusFreshness:
    now = datetime.now(timezone.utc)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=10.0)

    source_results: list[SourceFreshness] = []
    try:
        for source_name, (index, query_body) in _SOURCE_QUERIES.items():
            try:
                resp = await client.post(
                    f"{settings.ES_URL}/{index}/_search",
                    content=query_body,
                    headers={"content-type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                value_as_str = (
                    data.get("aggregations", {}).get("last", {}).get("value_as_string")
                )
                if value_as_str:
                    last_dt = datetime.fromisoformat(
                        value_as_str.replace("Z", "+00:00")
                    )
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    gap = (now - last_dt).total_seconds() / 3600
                    stale = gap > _STALENESS_THRESHOLD_HOURS
                else:
                    last_dt = None
                    gap = None
                    stale = True
                source_results.append(
                    SourceFreshness(
                        name=source_name,
                        last_indexed=last_dt,
                        stale=stale,
                        gap_hours=round(gap, 1) if gap is not None else None,
                    )
                )
            except Exception as exc:
                logger.warning("freshness check failed for %s: %s", source_name, exc)
                source_results.append(
                    SourceFreshness(
                        name=source_name,
                        last_indexed=None,
                        stale=True,
                        gap_hours=None,
                    )
                )
    finally:
        if owns_client:
            await client.aclose()

    any_stale = any(s.stale for s in source_results)
    return CorpusFreshness(
        sources=tuple(source_results),
        any_stale=any_stale,
        checked_at=now,
    )
