#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
LLM_SERVICE="${LLM_SERVICE:-llm}"
HOST_OUTPUT_DIR="${HOST_OUTPUT_DIR:-ops/data}"
PILOT_SOURCE="${PILOT_SOURCE:-tcu_jurisprudencia_selecionada}"
H2_DOU_JOBS="${H2_DOU_JOBS:-400}"
H2_TCU_JOBS="${H2_TCU_JOBS:-200}"
H3_JOBS="${H3_JOBS:-400}"
ROUND_SEED="${ROUND_SEED:-42}"
ROUND_ID="${AUDIT_ROUND_ID:-}"
MODEL_OVERRIDE="${H2_LLM_MODEL_OVERRIDE:-}"
CONTAINER_ROUNDS_DIR="${CONTAINER_ROUNDS_DIR:-/opt/app/ops/data/audit_rounds}"
AUDIT_JUDGE_MODE="${AUDIT_JUDGE_MODE:-official_judge}"

SOURCES=(
  "dou_documents"
  "tcu_acordao_completo"
  "tcu_jurisprudencia_selecionada"
  "tcu_resposta_consulta"
  "tcu_sumula"
  "tcu_boletim_jurisprudencia"
  "tcu_boletim_pessoal"
  "tcu_boletim_informativo_lc"
  "tcu_normas"
  "tcu_btcu"
  "tcu_publicacoes"
)

run_backend_py() {
  docker compose -f "${COMPOSE_FILE}" exec -T "${BACKEND_SERVICE}" /opt/venv/bin/python "$@"
}

run_backend_module() {
  run_backend_py -m "$@"
}

detect_llm_base_url() {
  docker compose -f "${COMPOSE_FILE}" exec -T "${BACKEND_SERVICE}" /opt/venv/bin/python - <<'PY'
import os
print(os.getenv("H2_LLM_BASE_URL", "http://llm:11434"))
PY
}

detect_model() {
  if [[ -n "${MODEL_OVERRIDE}" ]]; then
    printf '%s\n' "${MODEL_OVERRIDE}"
    return
  fi
  docker compose -f "${COMPOSE_FILE}" exec -T "${BACKEND_SERVICE}" /opt/venv/bin/python - <<'PY'
import os
print(os.getenv("H2_LLM_MODEL", "qwen2.5:7b-instruct"))
PY
}

ensure_model_available() {
  local model="$1"
  local base_url
  base_url="$(detect_llm_base_url)"
  if [[ "${base_url}" == "http://llm:11434" ]]; then
    if ! docker compose -f "${COMPOSE_FILE}" ps "${LLM_SERVICE}" >/dev/null 2>&1; then
      echo "LLM service '${LLM_SERVICE}' is not available in compose." >&2
      exit 1
    fi
    if ! docker compose -f "${COMPOSE_FILE}" exec -T "${LLM_SERVICE}" ollama list | awk '{print $1}' | grep -Fxq "${model}"; then
      echo "Required LLM model '${model}' is not available in ${LLM_SERVICE}." >&2
      echo "Set H2_LLM_MODEL_OVERRIDE or pull the model before rerunning." >&2
      exit 1
    fi
    return
  fi

  if ! docker compose -f "${COMPOSE_FILE}" exec -T "${BACKEND_SERVICE}" /opt/venv/bin/python - <<PY
import json
import sys

import httpx

base_url = ${base_url@Q}.rstrip("/")
model = ${model@Q}
try:
    response = httpx.get(f"{base_url}/api/tags", timeout=20.0)
    response.raise_for_status()
    payload = response.json()
except Exception as exc:
    print(f"External LLM endpoint unavailable: {exc}", file=sys.stderr)
    raise SystemExit(1)
models = [str((item or {}).get("name") or "") for item in payload.get("models", [])]
if model not in models:
    print(
        f"Required LLM model '{model}' is not available at {base_url}. Found: {models}",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
  then
    exit 1
  fi
}

csv_sources() {
  local IFS=,
  printf '%s\n' "${SOURCES[*]}"
}

echo "[1/9] preflight"
mkdir -p "${HOST_OUTPUT_DIR}"
MODEL="$(detect_model)"
ensure_model_available "${MODEL}"
run_backend_module ops.migrations.audit_schema --apply
run_backend_module src.backend.parsing.audit_cli panel-health --judge-mode "${AUDIT_JUDGE_MODE}"
run_backend_py -m pytest \
  /opt/app/tests/unit/test_h2_postprocess.py \
  /opt/app/tests/unit/test_h2_pipeline.py \
  /opt/app/tests/unit/test_h3_llm.py \
  /opt/app/tests/unit/test_audit_sampler.py \
  /opt/app/tests/unit/test_audit_judge.py

echo "[2/9] plan audit round"
PLAN_OUTPUT="$(
  run_backend_module src.backend.parsing.audit_cli plan-round \
    --sources "$(csv_sources)" \
    --seed "${ROUND_SEED}" \
    --judge-mode "${AUDIT_JUDGE_MODE}" \
    ${ROUND_ID:+--round-id "${ROUND_ID}"}
)"
ROUND_ID="$(printf '%s\n' "${PLAN_OUTPUT}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["round_id"])')"
CONTAINER_ROUND_DIR="${CONTAINER_ROUNDS_DIR}/${ROUND_ID}"
HOST_ROUND_DIR="${HOST_OUTPUT_DIR}/audit_rounds/${ROUND_ID}"
run_backend_module src.backend.parsing.audit_cli export-round-ids \
  --round-id "${ROUND_ID}" \
  --output-dir "${CONTAINER_ROUND_DIR}"

echo "[3/9] parse selected ids"
for source in "${SOURCES[@]}"; do
  run_backend_module src.backend.parsing.pipeline parse \
    --source "${source}" \
    --raw-id-file "${CONTAINER_ROUND_DIR}/${source}.process.txt"
done

echo "[4/9] h2 refresh"
for source in "${SOURCES[@]}"; do
  max_jobs="${H2_TCU_JOBS}"
  if [[ "${source}" == "dou_documents" ]]; then
    max_jobs="${H2_DOU_JOBS}"
  fi
  cmd=(
    src.backend.parsing.pipeline h2-worker
    --worker-id "h2-${source}-${ROUND_ID}"
    --max-jobs "${max_jobs}"
    --source-filter "${source}"
    --raw-id-file "${CONTAINER_ROUND_DIR}/${source}.process.txt"
    --h2-mode fast
  )
  if [[ "${source}" == "${PILOT_SOURCE}" ]]; then
    cmd+=(--llm-source "${source}" --model "${MODEL}")
  fi
  run_backend_module "${cmd[@]}"
done

echo "[5/9] h3 heuristic refresh"
for source in "${SOURCES[@]}"; do
  run_backend_module src.backend.parsing.pipeline h3-enqueue \
    --source "${source}" \
    --priority 100 \
    --raw-id-file "${CONTAINER_ROUND_DIR}/${source}.process.txt"
  run_backend_module src.backend.parsing.pipeline h3-worker \
    --worker-id "h3-${source}-${ROUND_ID}" \
    --max-jobs "${H3_JOBS}" \
    --source-filter "${source}" \
    --raw-id-file "${CONTAINER_ROUND_DIR}/${source}.process.txt"
done

echo "[6/9] h3 llm pilot"
run_backend_module src.backend.parsing.pipeline h3-enqueue \
  --source "${PILOT_SOURCE}" \
  --priority 10 \
  --status done_full \
  --status done_partial \
  --raw-id-file "${CONTAINER_ROUND_DIR}/${PILOT_SOURCE}.process.txt"
run_backend_module src.backend.parsing.pipeline h3-worker \
  --worker-id "h3-llm-${ROUND_ID}" \
  --max-jobs "${H3_JOBS}" \
  --source-filter "${PILOT_SOURCE}" \
  --raw-id-file "${CONTAINER_ROUND_DIR}/${PILOT_SOURCE}.process.txt" \
  --llm-source "${PILOT_SOURCE}" \
  --model "${MODEL}" \
  --llm-mode fast

echo "[7/9] judge round"
run_backend_module src.backend.parsing.audit_cli judge-round \
  --round-id "${ROUND_ID}" \
  --model "${MODEL}" \
  --judge-mode "${AUDIT_JUDGE_MODE}" \
  --output "${CONTAINER_ROUND_DIR}/panel_summary.json"

echo "[8/9] generate reports"
run_backend_module src.backend.parsing.audit_cli report-round \
  --round-id "${ROUND_ID}" \
  --mode tabs \
  --limit 0 \
  --output "${CONTAINER_ROUND_DIR}/raw_parsed_catalog_round_tabs.html"
run_backend_module src.backend.parsing.audit_cli report-round \
  --round-id "${ROUND_ID}" \
  --mode parsed-only \
  --limit 0 \
  --output "${CONTAINER_ROUND_DIR}/parsed_only_catalog_round.html"

container_id="$(docker compose -f "${COMPOSE_FILE}" ps -q "${BACKEND_SERVICE}")"
mkdir -p "${HOST_ROUND_DIR}"
docker cp "${container_id}:${CONTAINER_ROUND_DIR}/." "${HOST_ROUND_DIR}"

echo "[9/9] summary"
run_backend_py - <<PY
import json
import os

import psycopg

from src.backend.core.config import settings

round_id = ${ROUND_ID@Q}
out = {"round_id": round_id, "sources": {}}
with psycopg.connect(os.getenv("POSTGRES_URL", settings.POSTGRES_URL)) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_type, cohort_type, COUNT(*)
            FROM audit.cohort
            WHERE round_id = %s
            GROUP BY source_type, cohort_type
            ORDER BY source_type, cohort_type
            """,
            (round_id,),
        )
        for source_type, cohort_type, count in cur.fetchall():
            out["sources"].setdefault(source_type, {})[cohort_type] = count
print(json.dumps(out, ensure_ascii=False))
PY

echo "Artifacts updated in ${HOST_ROUND_DIR}"
