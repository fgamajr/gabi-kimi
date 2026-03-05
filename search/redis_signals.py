"""Redis-backed query signals: top searches, prefix boosts, and suggest cache."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import threading
from typing import Any

try:
    import redis
except ModuleNotFoundError:  # pragma: no cover
    redis = None  # type: ignore[assignment]


_LOCK = threading.Lock()
_CLIENT = None
_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s\-./]+", flags=re.UNICODE)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _cfg() -> dict[str, Any]:
    return {
        "enabled": _bool_env("SEARCH_ANALYTICS_ENABLED", True),
        "url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "prefix": os.getenv("REDIS_PREFIX", "gabi"),
        "min_len": int(os.getenv("TOP_SEARCH_MIN_QUERY_LEN", "3")),
        "max_len": int(os.getenv("TOP_SEARCH_MAX_QUERY_LEN", "120")),
        "day_ttl": int(os.getenv("TOP_SEARCH_DAY_TTL_SEC", str(14 * 24 * 3600))),
        "week_ttl": int(os.getenv("TOP_SEARCH_WEEK_TTL_SEC", str(16 * 7 * 24 * 3600))),
        "suggest_ttl": int(os.getenv("SUGGEST_CACHE_TTL_SEC", "120")),
    }


def _k(suffix: str) -> str:
    return f"{_cfg()['prefix']}:{suffix}"


def _get_client():
    global _CLIENT
    if not _cfg()["enabled"] or redis is None:
        return None
    if _CLIENT is not None:
        return _CLIENT
    with _LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            client = redis.from_url(_cfg()["url"], decode_responses=True)
            client.ping()
            _CLIENT = client
        except Exception:
            _CLIENT = None
    return _CLIENT


def normalize_query(query: str) -> str:
    q = _SPACE_RE.sub(" ", _NON_WORD_RE.sub(" ", (query or "").strip().lower())).strip()
    return q


def _rotate_sets(client, now_utc: datetime) -> None:
    day_stamp = now_utc.strftime("%Y-%m-%d")
    week_stamp = now_utc.strftime("%G-W%V")

    day_stamp_key = _k("meta:search:day_stamp")
    week_stamp_key = _k("meta:search:week_stamp")
    day_zset = _k("zset:search:top:day")
    week_zset = _k("zset:search:top:week")

    current_day = client.get(day_stamp_key)
    if current_day != day_stamp:
        pipe = client.pipeline()
        pipe.delete(day_zset)
        pipe.set(day_stamp_key, day_stamp, ex=_cfg()["day_ttl"])
        pipe.execute()

    current_week = client.get(week_stamp_key)
    if current_week != week_stamp:
        pipe = client.pipeline()
        pipe.delete(week_zset)
        pipe.set(week_stamp_key, week_stamp, ex=_cfg()["week_ttl"])
        pipe.execute()


def record_query(query: str) -> None:
    client = _get_client()
    if client is None:
        return

    norm = normalize_query(query)
    cfg = _cfg()
    if not norm or norm == "*" or len(norm) < cfg["min_len"] or len(norm) > cfg["max_len"]:
        return

    now_utc = datetime.now(timezone.utc)
    try:
        _rotate_sets(client, now_utc)
        day_zset = _k("zset:search:top:day")
        week_zset = _k("zset:search:top:week")
        pipe = client.pipeline()
        pipe.zincrby(day_zset, 1, norm)
        pipe.expire(day_zset, cfg["day_ttl"])
        pipe.zincrby(week_zset, 1, norm)
        pipe.expire(week_zset, cfg["week_ttl"])
        pipe.execute()
    except Exception:
        return


def top_searches(period: str = "day", n: int = 10) -> list[dict[str, Any]]:
    client = _get_client()
    if client is None:
        return []
    n = max(1, min(n, 30))
    key = _k("zset:search:top:week" if period == "week" else "zset:search:top:day")
    try:
        rows = client.zrevrange(key, 0, n - 1, withscores=True)
    except Exception:
        return []
    return [{"term": str(term), "count": int(score)} for term, score in rows]


def top_prefix_matches(prefix: str, n: int = 10) -> list[dict[str, Any]]:
    client = _get_client()
    if client is None:
        return []
    p = normalize_query(prefix)
    if not p:
        return []

    scores: dict[str, float] = {}
    keys = [_k("zset:search:top:day"), _k("zset:search:top:week")]
    try:
        for key in keys:
            for term, score in client.zscan_iter(key, match=f"{p}*"):
                t = str(term)
                scores[t] = scores.get(t, 0.0) + float(score)
    except Exception:
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[: max(1, min(n, 30))]
    return [{"term": term, "count": int(score)} for term, score in ranked]


def get_cached_suggest(prefix: str) -> list[dict[str, Any]] | None:
    client = _get_client()
    if client is None:
        return None
    p = normalize_query(prefix)
    if not p:
        return None
    key = _k(f"cache:suggest:{p}")
    try:
        raw = client.get(key)
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def set_cached_suggest(prefix: str, suggestions: list[dict[str, Any]]) -> None:
    client = _get_client()
    if client is None:
        return
    p = normalize_query(prefix)
    if not p:
        return
    key = _k(f"cache:suggest:{p}")
    try:
        client.set(key, json.dumps(suggestions, ensure_ascii=False), ex=_cfg()["suggest_ttl"])
    except Exception:
        return


def redis_available() -> bool:
    return _get_client() is not None

