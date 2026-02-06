# Arquitetura do Sistema

## Visão Geral

sources.yaml
   ↓
Execution Manifest
   ↓
Pipeline Determinístico
   ↓
PostgreSQL (canônico)
   ↓
Elasticsearch + pgvector
   ↓
APIs / MCP

## Camadas

### 1. Control Plane
- Scheduler
- Execution manifests
- Retry / backoff
- DLQ

### 2. Data Plane
- Download
- Parse
- Normalize
- Deduplicate

### 3. Serving Plane
- Search API
- Feed API
- Chat / RAG
- MCP Tools

Nenhuma camada conhece detalhes internos da outra.
