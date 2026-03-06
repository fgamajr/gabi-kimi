#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
QUARANTINE_BASE="var/archive/quarantine"
QUARANTINE_DIR="${QUARANTINE_BASE}/${STAMP}"
mkdir -p "$QUARANTINE_DIR"

move_to_quarantine() {
  local src="$1"
  if [ ! -e "$src" ] && [ ! -L "$src" ]; then
    return 0
  fi
  local dest="${QUARANTINE_DIR}/${src#./}"
  mkdir -p "$(dirname "$dest")"
  mv "$src" "$dest"
  printf 'quarantined %s -> %s\n' "$src" "$dest"
}

declare -a explicit_paths=(
  ".venv-macos"
  ".pytest_cache"
  "__pycache__"
  "antigravity.md"
  "COMPLETE_IMPLEMENTATION.md"
  "IMPLEMENTATION_SUMMARY.md"
  "QMD_MCP_SETUP.md"
  "Captura de Tela 2026-03-05 às 15.08.48.png"
  "image copy.png"
  "image.png"
  "instructor_a46l9irobhg0f5webscixp0bs_public_1748542336_07_-_007_-_A_Multi-Index_Rag_Pipeline_05.1748542336309.jpg"
  "instructor_a46l9irobhg0f5webscixp0bs_public_1748542336_07_-_007_-_A_Multi-Index_Rag_Pipeline_06.1748542336704.jpg"
  "instructor_a46l9irobhg0f5webscixp0bs_public_1748542337_07_-_007_-_A_Multi-Index_Rag_Pipeline_08.1748542337402.jpg"
  "instructor_a46l9irobhg0f5webscixp0bs_public_1748542337_07_-_007_-_A_Multi-Index_Rag_Pipeline_18.1748542337748.jpg"
  "instructor_a46l9irobhg0f5webscixp0bs_public_1748542338_07_-_007_-_A_Multi-Index_Rag_Pipeline_19.1748542338538.jpg"
  "ops/scripts/backfill_embeddings.py"
  "web/index-with-viewer.html"
  "web/document-viewer.html"
  "web/integration_html.html"
  "web/integration_layer.js"
  "web/integration_styles.css"
  "ops/data/chunks_backfill_cursor_2002_foreground.json"
  "ops/data/chunks_backfill_cursor_bgtest.json"
  "ops/data/chunks_backfill_cursor_debug.json"
  "ops/data/inlabs_2002_only"
)

declare -a discovered_paths=()

while IFS= read -r path; do
  discovered_paths+=("$path")
done < <(
  find . \
    \( -path './.git' -o -path './.git/*' -o -path './var/archive' -o -path './var/archive/*' -o -path './.venv' -o -path './.venv/*' \) -prune \
    -o \( -name '__pycache__' -o -name '.pytest_cache' -o -name '._*' \) -print
)

declare -A seen=()

for path in "${explicit_paths[@]}" "${discovered_paths[@]}"; do
  if [ -z "${path:-}" ]; then
    continue
  fi
  if [ -n "${seen[$path]:-}" ]; then
    continue
  fi
  seen["$path"]=1
  move_to_quarantine "$path"
done

printf '\nquarantine root: %s\n' "$QUARANTINE_DIR"
printf '\nEmpty directories after quarantine (safe prune candidates):\n'
find . -type d -empty \
  -not -path './.git*' \
  -not -path './var/archive*' \
  | sort
