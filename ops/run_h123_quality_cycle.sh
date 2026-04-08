#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-ops/data}"
BASE_ROUND_ID="${AUDIT_ROUND_ID:-quality-$(date -u +%Y%m%dT%H%M%SZ)}"
AUDIT_JUDGE_MODE="${AUDIT_JUDGE_MODE:-official_judge}"
AUTONOMOUS_MAX_ITERATIONS="${AUTONOMOUS_MAX_ITERATIONS:-1}"
AUTONOMOUS_PATCH_HOOK="${AUTONOMOUS_PATCH_HOOK:-}"

run_backend_py() {
  docker compose -f "${COMPOSE_FILE}" exec -T "${BACKEND_SERVICE}" /opt/venv/bin/python "$@"
}

run_backend_module() {
  run_backend_py -m "$@"
}

run_iteration() {
  local iteration="$1"
  local round_id="${BASE_ROUND_ID}"
  if [[ "${AUTONOMOUS_MAX_ITERATIONS}" -gt 1 ]]; then
    round_id="${BASE_ROUND_ID}-iter${iteration}"
  fi
  local quality_json="${HOST_OUTPUT_DIR}/audit_rounds/${round_id}/quality_gate.json"
  local iteration_json="${HOST_OUTPUT_DIR}/audit_rounds/${round_id}/iteration_summary.json"

  echo "[iteration ${iteration}] refresh audited round"
  set +e
  AUDIT_ROUND_ID="${round_id}" AUDIT_JUDGE_MODE="${AUDIT_JUDGE_MODE}" bash ops/run_h123_sample_refresh.sh
  refresh_rc=$?
  set -e
  if [[ "${refresh_rc}" -ne 0 ]]; then
    echo "Refresh failed for ${round_id} with exit code ${refresh_rc}." >&2
    return 2
  fi

  echo "[iteration ${iteration}] assess round"
  set +e
  run_backend_module src.backend.parsing.audit_cli assess-round \
    --round-id "${round_id}" \
    --output "/opt/app/${quality_json}"
  assess_rc=$?
  set -e

  container_id="$(docker compose -f "${COMPOSE_FILE}" ps -q "${BACKEND_SERVICE}")"
  mkdir -p "$(dirname "${quality_json}")"
  docker cp "${container_id}:/opt/app/${quality_json}" "${quality_json}"

  python3 - <<PY > "${iteration_json}"
import json
from pathlib import Path

quality = json.loads(Path(${quality_json@Q}).read_text(encoding="utf-8"))
print(json.dumps({
    "round_id": quality["round_id"],
    "gate_passed": quality["gate_passed"],
    "failing_sources": [source for source, payload in quality["sources"].items() if not payload.get("gate_passed", False)],
}, ensure_ascii=False, indent=2))
PY
  echo "[iteration ${iteration}] quality gate JSON: ${quality_json}"

  if [[ "${assess_rc}" -eq 0 ]] && python3 - <<PY
import json
from pathlib import Path
payload = json.loads(Path(${quality_json@Q}).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("gate_passed") else 1)
PY
  then
    echo "Cycle completed for ${round_id}"
    return 0
  fi

  if [[ -z "${AUTONOMOUS_PATCH_HOOK}" ]]; then
    echo "Quality gate failed for ${round_id} and no AUTONOMOUS_PATCH_HOOK is configured." >&2
    return 2
  fi

  if [[ "${iteration}" -ge "${AUTONOMOUS_MAX_ITERATIONS}" ]]; then
    echo "Reached AUTONOMOUS_MAX_ITERATIONS=${AUTONOMOUS_MAX_ITERATIONS} without passing the gate." >&2
    return 2
  fi

  echo "[iteration ${iteration}] running AUTONOMOUS_PATCH_HOOK"
  ROUND_ID="${round_id}" QUALITY_JSON="${quality_json}" bash -lc "${AUTONOMOUS_PATCH_HOOK}"
  return 1
}

status=1
for ((iteration=1; iteration<=AUTONOMOUS_MAX_ITERATIONS; iteration++)); do
  if run_iteration "${iteration}"; then
    status=0
    break
  fi
  rc=$?
  if [[ "${rc}" -eq 2 ]]; then
    status=2
    break
  fi
done

exit "${status}"
