# Handover para Cursor — Pipeline DOU 5 anos + MCP (2026-02-27)

Documento para a próxima sessão/agente: o que foi feito, estado atual e como continuar. **Não editar o plano** em `~/.cursor/plans/`; usar este handover como referência.

---

## Resumo em uma frase

Ativamos o pipeline completo (Seed → Discovery → Fetch → Ingest → **chunk_and_extract**) com DOU 5 anos (cap 5000), pgvector + ONNX na API, e um **MCP server .NET** (Gabi.Mcp) que expõe busca híbrida (BM25 + vetor + grafo) para o Cursor via stdio.

---

## O que foi implementado nesta sessão

### 1. Pipeline: `chunk_and_extract` em vez de `embed_and_index`

- **IngestJobExecutor** — enfileira `chunk_and_extract` (fan-out) e backpressure por `chunk_and_extract`.
- **HangfireJobQueueRepository** — `chunk_and_extract` → fila `embed`; incluído em `EnforceSingleInFlightPerSource`.
- **DriftAuditorJobExecutor** — reparos enfileiram `chunk_and_extract`.
- **Gabi.Api** — endpoint `POST /api/v1/admin/sources/{id}/repair-projection` enfileira `chunk_and_extract`.

Assim o fan-out (BM25 + pgvector + KG) passa a rodar de fato.

### 2. Infra e dados

- **Modelo ONNX** — `./scripts/download-model.sh` executado; `models/paraphrase-multilingual-MiniLM-L12-v2/model.onnx` + `vocab.txt` presentes (vocab.txt pode estar truncado no HuggingFace; se ONNX falhar, checar).
- **Postgres com pgvector** — `docker-compose.yml` usa imagem `pgvector/pgvector:pg15`. Tabelas `document_embeddings` e `document_relationships` criadas (SQL aplicado manualmente; migração EF `20260227120000_AddDocumentEmbeddingsAndRelationships` registrada em `__EFMigrationsHistory`).
- **dotnet-ef** — instalado como ferramenta local (`.config/dotnet-tools.json`) para `./scripts/dev db apply` no futuro.

### 3. Fontes DOU (5 anos)

- **sources_v2.yaml**  
  - `dou_dados_abertos_mensal`: `start_year: 2021`, `sections: ["do1"]`.  
  - `dou_inlabs_secao1_atos_administrativos`: `start: "2021-01-01"`.

### 4. API: busca híbrida sem TEI

- **Program.cs (Gabi.Api)** — `ISearchService` registrado quando existe `Gabi:ElasticsearchUrl`. Escolha do embedder: **ONNX** (se `model.onnx` + `vocab.txt` existirem) → TEI → Hash. Helper `RegisterTeiEmbedder` para quando TEI estiver configurado.
- **GET /api/v1/documents/{id}** — novo endpoint para documento por ID (usado pelo MCP).

### 5. MCP server (Gabi.Mcp)

- **Projeto:** `src/Gabi.Mcp/` — console .NET 8, ModelContextProtocol 1.0.0, stdio.
- **GabiApiClient** — login (GABI_API_TOKEN ou GABI_API_USER/PASSWORD), GET para a API.
- **GabiMcpTools** — 6 tools: `SearchDocuments`, `GetDocument`, `GetRelatedDocuments`, `SearchLegalReferences`, `ListSources`, `GetPipelineStatus`.
- **Config Cursor:** `.cursor/mcp.json` — servidor `gabi-search`, command `dotnet run --project src/Gabi.Mcp/Gabi.Mcp.csproj --no-build`, env `GABI_API_URL`, `GABI_API_USER`, `GABI_API_PASSWORD`.

### 6. Pipeline disparado

- Seed e **run-pipeline** para `dou_dados_abertos_mensal` com `max_docs_per_source: 5000` executados via API.
- Worker pode ter usado HashEmbedder se o cwd não for a raiz do repo (ONNX procura `models/` em relação ao cwd). Para ONNX no Worker: rodar na raiz ou configurar `Embeddings:OnnxModelDir` absoluto.

---

## Estado atual (sem commit)

- **Branch:** `feat/fullpipeline`; mudanças não commitadas.
- **Build:** `dotnet build GabiSync.sln` — OK.
- **Architecture tests:** 3/3 — OK.
- **PG:** ~2228 documentos em `documents`; `document_embeddings` e `document_relationships` existem (contagens dependem do pipeline/backfill).
- **Config key do embedder:** no Worker é `Embeddings:Provider` (não `Gabi:Embeddings:Provider`).

---

## Como rodar e validar

```bash
# Infra
./scripts/dev infra up
./scripts/dev db apply   # usa dotnet tool run dotnet-ef (ou aplica SQL manual se necessário)

# API (raiz do repo para ONNX na API)
ConnectionStrings__Default="Host=localhost;Port=5433;Database=gabi;Username=gabi;Password=gabi_dev_password" \
Gabi__ElasticsearchUrl="http://localhost:9200" \
Jwt__Key="dev-only-jwt-key-not-for-production-please-change-0123456789" \
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"

# Worker (raiz do repo para achar models/)
dotnet run --project src/Gabi.Worker

# Pipeline DOU (cap 5000)
TOKEN=$(curl -s -X POST http://localhost:5100/api/v1/auth/login -H "Content-Type: application/json" -d '{"username":"operator","password":"op123"}' | jq -r .token)
curl -s -X POST http://localhost:5100/api/v1/dashboard/seed -H "Authorization: Bearer $TOKEN"
curl -s -X POST http://localhost:5100/api/v1/dashboard/sources/dou_dados_abertos_mensal/run-pipeline \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"max_docs_per_source":5000,"chain_next":true}'

# Busca híbrida
curl -s "http://localhost:5100/api/v1/search?q=acórdão&page=1&pageSize=5" -H "Authorization: Bearer $TOKEN" | jq .

# MCP (Cursor): reiniciar Cursor ou recarregar; servidor gabi-search em .cursor/mcp.json
```

---

## Próximos passos sugeridos

- **Backfill:** resetar `Status='pending'` (e limpar `EmbeddingId`/`ProcessingStage`) para documentos sem embedding e reenfileirar ingest para rodar `chunk_and_extract` nos lotes.
- **Worker com ONNX:** garantir que o Worker rode na raiz do repo ou que `Embeddings:OnnxModelDir` aponte para o diretório do modelo.
- **IVFFlat:** após >10k linhas em `document_embeddings`, criar índice ivfflat para busca por similaridade.
- **Commit:** revisar diff, fazer commit (ou squashes) em `feat/fullpipeline`.

---

## Referências

- **Plano usado:** `~/.cursor/plans/dou_5yr_pipeline_mcp_998810c0.plan.md` (não editar).
- **Handover geral do projeto:** `HANDOVER.md` na raiz.
- **Arquitetura:** `CLAUDE.md`, `docs/architecture/LAYERED_ARCHITECTURE.md`, `docs/ARCHITECTURE_MAP.md`.
