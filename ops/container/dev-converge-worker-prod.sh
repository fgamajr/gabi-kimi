#!/bin/sh
set -eu

cd /opt/app

exec python -m src.dev_converge.worker

