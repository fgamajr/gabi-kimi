#!/usr/bin/env bash
# E2E: Admin upload flow (storage-check, upload, job status).
# Requires: web on port 8000, optional worker for job processing.
# Usage: GABI_ADMIN_TOKEN=dev-admin-token ./ops/scripts/e2e_admin_upload.sh

set -e
BASE="${GABI_API_BASE:-http://localhost:8000}"
TOKEN="${GABI_ADMIN_TOKEN:?Set GABI_ADMIN_TOKEN}"
XML="${1:-ops/scripts/fixtures/sample_dou_article.xml}"

if [[ ! -f "$XML" ]]; then
  echo "Creating minimal XML fixture..."
  mkdir -p "$(dirname "$XML")"
  cat > "$XML" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<article><body><p>Test</p></body></article>
EOF
fi

echo "1. GET /api/admin/storage-check"
code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/admin/storage-check")
if [[ "$code" != "200" ]]; then
  echo "   FAIL: expected 200, got $code"
  exit 1
fi
echo "   OK ($code)"

echo "2. POST /api/admin/upload"
resp=$(curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -F "file=@$XML" "$BASE/api/admin/upload")
body=$(echo "$resp" | head -n -1)
code=$(echo "$resp" | tail -n 1)
if [[ "$code" != "202" ]]; then
  echo "   FAIL: expected 202, got $code. body=$body"
  exit 1
fi
job_id=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('job_id',''))")
if [[ -z "$job_id" ]]; then
  echo "   FAIL: no job_id in response"
  exit 1
fi
echo "   OK (202) job_id=$job_id"

echo "3. GET /api/admin/jobs/$job_id (poll until terminal, max 120s)"
for i in $(seq 1 60); do
  status=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/admin/jobs/$job_id" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))")
  echo "   [$i] status=$status"
  case "$status" in
    completed|failed|partial) echo "   OK (terminal: $status)"; exit 0 ;;
    queued|processing) sleep 2 ;;
    *) echo "   FAIL: unknown status $status"; exit 1 ;;
  esac
done
echo "   FAIL: timeout (worker may be running full ES sync; check job in UI)"
exit 1
