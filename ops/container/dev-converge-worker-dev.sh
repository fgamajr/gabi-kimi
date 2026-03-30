#!/bin/sh
set -eu

cd /workspace

exec python -m src.dev_converge.worker

