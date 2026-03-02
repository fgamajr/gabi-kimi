#!/usr/bin/env bash
set -e

STAMP=$(date +%Y%m%d-%H%M%S)
git add -A >/dev/null 2>&1 || true
git commit -m "AUTO-SNAPSHOT $STAMP" >/dev/null 2>&1 || true
git tag "pre-claude-$STAMP"
echo "Snapshot: pre-claude-$STAMP"