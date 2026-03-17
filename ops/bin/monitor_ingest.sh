#!/bin/bash
# Monitor Mongo-only DOU ingest progress.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

STATE_PATH="${REPO_ROOT}/ops/data/ingest_state.json"
EVENTS_PATH="${REPO_ROOT}/ops/data/ingest_events.jsonl"
LOG_PATH="${REPO_ROOT}/ops/data/ingest_progress.log"
RAW_CACHE_PATH="${RAW_CACHE_PATH:-${REPO_ROOT}/ops/data/raw_cache}"
RATE_STATE_PATH="${REPO_ROOT}/ops/data/monitor_mongo_rate.state"

mongo_count=""
if command -v mongosh >/dev/null 2>&1; then
  mongo_count="$(mongosh --quiet mongodb://127.0.0.1:27017/gabi_dou --eval 'db.documents.countDocuments({})' 2>/dev/null || true)"
else
  mongo_count="$(docker compose exec -T mongo mongosh --quiet mongodb://127.0.0.1:27017/gabi_dou --eval 'db.documents.countDocuments({})' 2>/dev/null || true)"
fi
if [ -z "${mongo_count}" ]; then
  mongo_count="unavailable"
fi

python3 - <<'PY' "$STATE_PATH" "$EVENTS_PATH" "$LOG_PATH" "$RAW_CACHE_PATH" "$mongo_count" "$RATE_STATE_PATH"
import json
import sys
import time
from pathlib import Path

state_path = Path(sys.argv[1])
events_path = Path(sys.argv[2])
log_path = Path(sys.argv[3])
raw_cache_path = Path(sys.argv[4])
mongo_count = sys.argv[5]
rate_state_path = Path(sys.argv[6])
now = time.time()

state = {}
if state_path.exists():
    state = json.loads(state_path.read_text(encoding="utf-8"))

completed = state.get("months_completed", [])
active = state.get("active_months", {})
failed = state.get("months_failed", {})
months_total = state.get("months_total", 0)

recent_docs = 0
recent_months = 0
window_sec = 300
if events_path.exists():
    for line in events_path.read_text(encoding="utf-8").splitlines()[-500:]:
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "month_completed":
            continue
        ts = event.get("ts")
        try:
            event_time = time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if now - event_time <= window_sec:
            recent_docs += int(event.get("doc_count", 0))
            recent_months += 1

cache_files = 0
cache_bytes = 0
if raw_cache_path.exists():
    for path in raw_cache_path.rglob("*"):
        if path.is_file():
            cache_files += 1
            cache_bytes += path.stat().st_size

last_log = ""
if log_path.exists():
    lines = [line for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if lines:
        last_log = lines[-1]

mongo_rate = "warming_up"
try:
    mongo_count_int = int(mongo_count)
except ValueError:
    mongo_count_int = None

if mongo_count_int is not None:
    prev_count = None
    prev_time = None
    if rate_state_path.exists():
        raw = rate_state_path.read_text(encoding="utf-8").strip().split()
        if len(raw) == 2:
            prev_count = int(raw[0])
            prev_time = float(raw[1])
    rate_state_path.write_text(f"{mongo_count_int} {now}\n", encoding="utf-8")
    if prev_count is not None and prev_time is not None and now > prev_time and mongo_count_int >= prev_count:
        delta_docs = mongo_count_int - prev_count
        delta_sec = now - prev_time
        if delta_docs > 0 and delta_sec > 0:
            mongo_rate = str(int(delta_docs * 60 / delta_sec))

print(f"mongo_docs={mongo_count}")
print(f"mongo_docs_per_min={mongo_rate}")
print(f"months={len(completed)}/{months_total} active={len(active)} failed={len(failed)}")
if active:
    preview = ",".join(sorted(active.keys())[:8])
    suffix = "" if len(active) <= 8 else ",..."
    print("running_preview=" + preview + suffix)
if recent_docs > 0:
    print(f"recent_rate_docs_per_min={recent_docs * 60 // window_sec}")
    print(f"recent_months_completed_5m={recent_months}")
else:
    print("recent_rate_docs_per_min=warming_up")
print(f"raw_cache_files={cache_files}")
print(f"raw_cache_gb={cache_bytes / (1024**3):.2f}")
if last_log:
    print(f"last_log={last_log}")
PY
