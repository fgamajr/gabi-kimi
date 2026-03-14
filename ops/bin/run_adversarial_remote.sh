#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_adversarial_remote.sh [options]

Runs the adversarial API suite on the Linux host over SSH using a clean Uvicorn
startup (no stale __pycache__) and stops the server at the end by default.

Options:
  --host NAME         SSH host alias. Default: ubuntu-vm
  --remote-root PATH  Project path on Linux. Default: /home/parallels/dev/gabi-kimi
  --python PATH       Python executable on Linux. Default: <remote-root>/.venv/bin/python
  --port N            API port on Linux. Default: 8000
  --runs N            Number of full suite runs. Default: 3
  --workers N         Uvicorn worker count. Default: 1
  --keep-server       Leave the API running after the tests
  --help              Show this help

Default settings run 3 full suites, which is 1065 HTTP calls with the current
ops/test_api_adversarial.py harness.
EOF
}

host="ubuntu-vm"
remote_root="/home/parallels/dev/gabi-kimi"
python_bin=""
port="8000"
runs="3"
workers="1"
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
    --workers)
      workers="$2"
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

if [[ -z "$python_bin" ]]; then
  python_bin="${remote_root}/.venv/bin/python"
fi

echo "Remote adversarial runner"
echo "  host: ${host}"
echo "  root: ${remote_root}"
echo "  python: ${python_bin}"
echo "  port: ${port}"
echo "  runs: ${runs}"
echo "  workers: ${workers}"
echo "  keep_server: ${keep_server}"

ssh "$host" bash -s -- "$remote_root" "$python_bin" "$port" "$runs" "$workers" "$keep_server" <<'REMOTE'
set -euo pipefail

remote_root="$1"
python_bin="$2"
port="$3"
runs="$4"
workers="$5"
keep_server="$6"

cd "$remote_root"

log_root="${remote_root}/var/tmp/adversarial-remote"
mkdir -p "$log_root"
timestamp="$(date +%Y%m%d-%H%M%S)"
server_log="${log_root}/server-${timestamp}.log"

cleanup() {
  if [[ "$keep_server" != "1" ]]; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "Cleaning stale Python bytecode..."
find src -name '__pycache__' -type d -prune -exec rm -rf {} +

echo "Stopping anything already bound to :${port}..."
fuser -k "${port}/tcp" >/dev/null 2>&1 || true

echo "Starting API server..."
if [[ "$workers" == "1" ]]; then
  setsid -f "$python_bin" -B -m uvicorn src.backend.main:app --host 127.0.0.1 --port "$port" >"$server_log" 2>&1
else
  setsid -f "$python_bin" -B -m uvicorn src.backend.main:app --host 127.0.0.1 --port "$port" --workers "$workers" >"$server_log" 2>&1
fi

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
  tail -n 80 "$server_log" >&2 || true
  exit 1
fi

echo "API is healthy. Server log: ${server_log}"

overall_rc="0"
for run in $(seq 1 "$runs"); do
  run_log="${log_root}/run-${timestamp}-${run}.log"
  echo
  echo "=== Run ${run}/${runs} ==="
  if GABI_API_BASE="http://127.0.0.1:${port}" "$python_bin" -B ops/test_api_adversarial.py >"$run_log" 2>&1; then
    rc="0"
  else
    rc="$?"
    overall_rc="1"
  fi

  rg -n 'Completed in|ADVERSARIAL TEST REPORT|Status code distribution|Latency:' "$run_log" || true
  if [[ "$rc" != "0" ]]; then
    echo "Run ${run} failed. Full log: ${run_log}" >&2
    tail -n 80 "$run_log" >&2 || true
  else
    echo "Run ${run} log: ${run_log}"
  fi
done

echo
echo "Artifacts saved under: ${log_root}"
exit "$overall_rc"
REMOTE
