#!/usr/bin/env bash
# ╔═══════════════════════════════════════════════════════════════╗
# ║ DEPRECATED: Este script esta sendo migrado para o            ║
# ║ ReliabilityLab C# (tests/ReliabilityLab/).                  ║
# ║ Ver: tests/ReliabilityLab/README.md para a versao moderna.   ║
# ╚═══════════════════════════════════════════════════════════════╝
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

API_URL="${API_URL:-http://localhost:5100}"
SOURCE_ID="${SOURCE_ID:-e2e_media_projection}"
EXTERNAL_ID="${EXTERNAL_ID:-e2e_media_$(date +%s)}"
MEDIA_URL="${MEDIA_URL:-https://youtube.com/watch?v=e2e_media_$(date +%s)}"
TITLE="${TITLE:-E2E Media Projection Test}"
TRANSCRIPT_TEXT="${TRANSCRIPT_TEXT:-Este é um transcript de teste E2E para validar a projeção de mídia em documento textual.}"
SUMMARY_TEXT="${SUMMARY_TEXT:-Resumo E2E da mídia.}"

log() {
  echo "[e2e-media] $*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd curl
require_cmd python3

if ! docker compose ps postgres >/dev/null 2>&1; then
  echo "Docker compose postgres service not found. Start stack first." >&2
  exit 1
fi

if ! curl -fsS "$API_URL/health" >/dev/null 2>&1; then
  echo "API not ready at $API_URL. Start API/Worker first." >&2
  exit 1
fi

login_token=""
for attempt in $(seq 1 20); do
  login_raw="$(curl -s -w '\n%{http_code}' -X POST "$API_URL/api/v1/auth/login" \
    -H 'Content-Type: application/json' \
    -d '{"username":"operator","password":"op123"}')"
  status_code="$(echo "$login_raw" | tail -n1)"
  body="$(echo "$login_raw" | sed '$d')"

  if [[ "$status_code" == "200" ]]; then
    login_token="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["token"])' <<<"$body")"
    break
  fi

  if [[ "$status_code" == "429" ]]; then
    sleep 2
    continue
  fi

  echo "Login failed (HTTP $status_code): $body" >&2
  exit 1
done

if [[ -z "$login_token" ]]; then
  echo "Could not obtain JWT token after retries." >&2
  exit 1
fi

log "Ensuring source_registry row for source_id=$SOURCE_ID"
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U gabi -d gabi >/dev/null <<SQL
INSERT INTO source_registry (
  "Id", "Name", "Provider", "DiscoveryStrategy", "DiscoveryConfig",
  "Enabled", "FetchProtocol", "TotalLinks", "CreatedAt", "UpdatedAt", "CreatedBy", "UpdatedBy"
)
VALUES (
  '${SOURCE_ID}',
  'E2E Media Projection Source',
  'E2E',
  'static_url',
  '{"strategy":"static_url"}',
  true,
  'https',
  0,
  NOW(),
  NOW(),
  'e2e',
  'e2e'
)
ON CONFLICT ("Id") DO NOTHING;
SQL

metadata_json="$(python3 - <<PY
import json
print(json.dumps({
  "origin": "e2e_test",
  "media_type": "youtube_video",
  "test_case": "media_projection"
}))
PY
)"

log "Inserting media item with transcript_status=completed"
media_item_id="$(docker compose exec -T postgres psql -q -v ON_ERROR_STOP=1 -U gabi -d gabi -tA <<SQL
INSERT INTO media_items (
  "SourceId", "ExternalId", "MediaUrl", "Title", "TranscriptText", "SummaryText",
  "TranscriptStatus", "TranscriptConfidence", "Metadata",
  "CreatedAt", "UpdatedAt", "CreatedBy", "UpdatedBy"
)
VALUES (
  '${SOURCE_ID}',
  '${EXTERNAL_ID}',
  '${MEDIA_URL}',
  '${TITLE}',
  '${TRANSCRIPT_TEXT}',
  '${SUMMARY_TEXT}',
  'completed',
  'high',
  '${metadata_json}',
  NOW(),
  NOW(),
  'e2e',
  'e2e'
)
RETURNING "Id";
SQL
)"
media_item_id="$(echo "$media_item_id" | head -n1 | tr -d '[:space:]')"

if [[ -z "$media_item_id" ]]; then
  echo "Failed to insert media item." >&2
  exit 1
fi

log "Triggering ingest phase for source_id=$SOURCE_ID"
ingest_raw="$(curl -s -w '\n%{http_code}' -X POST "$API_URL/api/v1/dashboard/sources/${SOURCE_ID}/phases/ingest" \
  -H "Authorization: Bearer $login_token" \
  -H 'Content-Type: application/json' \
  -d '{}')"
ingest_status="$(echo "$ingest_raw" | tail -n1)"
ingest_body="$(echo "$ingest_raw" | sed '$d')"
if [[ "$ingest_status" != "200" ]]; then
  echo "Failed to trigger ingest (HTTP $ingest_status): $ingest_body" >&2
  exit 1
fi

job_id="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("job_id",""))' <<<"$ingest_body")"
if [[ -z "$job_id" ]]; then
  echo "No job_id returned: $ingest_body" >&2
  exit 1
fi

log "Polling job_registry for completion (job_id=$job_id)"
job_status=""
for _ in $(seq 1 60); do
  job_status="$(docker compose exec -T postgres psql -U gabi -d gabi -tA \
    -c "SELECT COALESCE(\"Status\",'') FROM job_registry WHERE \"JobId\"='${job_id}' LIMIT 1;" | tr -d '[:space:]')"
  if [[ "$job_status" == "completed" ]]; then
    break
  fi
  if [[ "$job_status" == "failed" ]]; then
    error_msg="$(docker compose exec -T postgres psql -U gabi -d gabi -tA \
      -c "SELECT COALESCE(\"ErrorMessage\",'') FROM job_registry WHERE \"JobId\"='${job_id}' LIMIT 1;")"
    echo "Ingest job failed: $error_msg" >&2
    exit 1
  fi
  sleep 1
done

if [[ "$job_status" != "completed" ]]; then
  echo "Timed out waiting ingest completion. Final status='$job_status'" >&2
  exit 1
fi

log "Validating projected document"
doc_count="$(docker compose exec -T postgres psql -U gabi -d gabi -tA \
  -c "SELECT COUNT(*) FROM documents WHERE \"SourceId\"='${SOURCE_ID}' AND \"ExternalId\"='${EXTERNAL_ID}' AND \"Status\"='completed';" | tr -d '[:space:]')"
if [[ "$doc_count" != "1" ]]; then
  echo "Expected 1 projected document, got $doc_count" >&2
  exit 1
fi

content_checks="$(docker compose exec -T postgres psql -U gabi -d gabi -tA <<SQL
SELECT
  ("Content" LIKE '%## Transcript%' AND "Content" LIKE '%${TRANSCRIPT_TEXT}%')::int,
  ("Metadata"::jsonb->>'origin' = 'media_projection_v1')::int,
  ("ProcessingStage" = 'ingested')::int
FROM documents
WHERE "SourceId"='${SOURCE_ID}' AND "ExternalId"='${EXTERNAL_ID}'
LIMIT 1;
SQL
)"

if [[ "$content_checks" != "1|1|1" ]]; then
  echo "Projected document checks failed: $content_checks (expected 1|1|1)" >&2
  exit 1
fi

link_count="$(docker compose exec -T postgres psql -U gabi -d gabi -tA \
  -c "SELECT COUNT(*) FROM discovered_links WHERE \"SourceId\"='${SOURCE_ID}' AND \"Url\"='${MEDIA_URL}' AND \"IngestStatus\"='completed';" | tr -d '[:space:]')"
if [[ "$link_count" != "1" ]]; then
  echo "Expected 1 discovered_link for projected media, got $link_count" >&2
  exit 1
fi

log "PASS: media projection created canonical document (source_id=$SOURCE_ID, external_id=$EXTERNAL_ID, media_item_id=$media_item_id)"
