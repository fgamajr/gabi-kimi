#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_adversarial_remote.sh [options]

Runs the adversarial API suite on the Linux host over SSH using the Docker
backend service and stops the backend container at the end by default.

Options:
  --host NAME         SSH host alias. Default: ubuntu-vm
  --remote-root PATH  Project path on Linux. Default: /home/parallels/dev/gabi-kimi
  --python PATH       Deprecated. Ignored in Docker mode.
  --port N            Published backend port on Linux. Default: 8001
  --runs N            Number of full suite runs. Default: 3
  --keep-server       Leave the API running after the tests
  --help              Show this help

Default settings run 3 full suites, which is 1065 HTTP calls with the current
ops/test_api_adversarial.py harness.
EOF
}

host="ubuntu-vm"
remote_root="/home/parallels/dev/gabi-kimi"
python_bin=""
port="8001"
runs="3"
keep_server="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      host="$2"
      shift 2
      ;;
    --remote-root)
      remote_root="$2"
      shift 2
      ;;
    --python)
      python_bin="$2"
      shift 2
      ;;
    --port)
      port="$2"
      shift 2
      ;;
    --runs)
      runs="$2"
      shift 2
      ;;
    --keep-server)
      keep_server="1"
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -n "$python_bin" ]]; then
  echo "Warning: --python is deprecated and ignored; Docker backend service is used instead." >&2
fi

echo "Remote adversarial runner"
echo "  host: ${host}"
echo "  root: ${remote_root}"
echo "  port: ${port}"
echo "  runs: ${runs}"
echo "  keep_server: ${keep_server}"

ssh "$host" bash -s -- "$remote_root" "$port" "$runs" "$keep_server" <<'REMOTE'
set -euo pipefail

remote_root="$1"
port="$2"
runs="$3"
keep_server="$4"

cd "$remote_root"

log_root="${remote_root}/var/tmp/adversarial-remote"
mkdir -p "$log_root"
timestamp="$(date +%Y%m%d-%H%M%S)"
server_log="${log_root}/server-${timestamp}.log"

cleanup() {
  if [[ "$keep_server" != "1" ]]; then
    docker compose stop backend >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Starting Docker services..."
docker compose up -d mongo elasticsearch backend >/dev/null
echo "Restarting backend for a clean app start..."
docker compose restart backend >/dev/null
docker compose logs backend --tail 100 >"$server_log" 2>&1 || true

healthy="0"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${port}/" >/dev/null 2>&1; then
    healthy="1"
    break
  fi
  sleep 1
done

if [[ "$healthy" != "1" ]]; then
  echo "API failed to become healthy. Server log:" >&2
  docker compose logs backend --tail 80 >&2 || true
  exit 1
fi

echo "API is healthy. Server log: ${server_log}"

overall_rc="0"
for run in $(seq 1 "$runs"); do
  run_log="${log_root}/run-${timestamp}-${run}.log"
  echo
  echo "=== Run ${run}/${runs} ==="
  if docker compose exec -T backend sh -lc \
    'GABI_API_BASE="http://127.0.0.1:8000" python ops/test_api_adversarial.py' \
    >"$run_log" 2>&1; then
    rc="0"
  else
    rc="$?"
    overall_rc="1"
  fi

  rg -n 'Completed in|ADVERSARIAL TEST REPORT|Status code distribution|Latency:' "$run_log" || true
  if [[ "$rc" != "0" ]]; then
    echo "Run ${run} failed. Full log: ${run_log}" >&2
    tail -n 80 "$run_log" >&2 || true
    echo "Recent backend logs:" >&2
    docker compose logs backend --tail 80 >&2 || true
  else
    echo "Run ${run} log: ${run_log}"
  fi
done

echo
echo "Artifacts saved under: ${log_root}"
exit "$overall_rc"
REMOTE
