#!/bin/bash
# Full DOU ingestion: 2009-04 through 2026-01
# Run from project root: bash ops/run_full_ingest.sh
set -e

cd /home/parallels/dev/gabi-kimi

LOG="ops/data/ingest_progress.log"

# Resume from 2009 month 4, then 2010-2025 full years, then 2026
echo "[$(date)] Starting full ingest from 2009-04" >> "$LOG"

# 2009: remaining months
for m in $(seq 4 12); do
  echo "[$(date)] Ingesting 2009-$m" >> "$LOG"
  python3 sync_dou.py --year 2009 --month $m 2>&1 | tail -1 >> "$LOG"
done

# 2010 through 2025: full years
for y in $(seq 2010 2025); do
  echo "[$(date)] Ingesting year $y" >> "$LOG"
  python3 sync_dou.py --year $y 2>&1 | tail -1 >> "$LOG"
done

# 2026
echo "[$(date)] Ingesting year 2026" >> "$LOG"
python3 sync_dou.py --year 2026 2>&1 | tail -1 >> "$LOG"

echo "[$(date)] Full ingest complete" >> "$LOG"
