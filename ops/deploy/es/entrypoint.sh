#!/bin/bash
set -e

# Fix volume ownership — Fly.io volumes mount as root
chown -R elasticsearch:elasticsearch /usr/share/elasticsearch/data

# Drop privileges and start Elasticsearch
exec su-exec elasticsearch /usr/share/elasticsearch/bin/elasticsearch
