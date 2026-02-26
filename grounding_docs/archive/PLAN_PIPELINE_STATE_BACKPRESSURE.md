# Plano e Prompt: API de Controle de Estado e Dynamic Batch Sizing (Memória)

## 1. Contexto do Problema

Com a nova arquitetura do pipeline (`Seed` -> `Discovery` -> `Fetch` -> `Ingest` -> `EmbedAndIndex`), o processamento de fontes massivas como `tcu_acordaos` (500.000+ documentos) introduziu desafios de escala. 

**O que JÁ TEMOS resolvido no código:**
- **Backpressure Baseado no Banco:** `Discovery`, `Fetch` e `Ingest` já verificam os limites (ex: `MaxPendingFetch`, `MaxPendingIngest`, `MaxPendingEmbed`) usando `PipelineBackpressureConfig` e fazem *yield* (re-agendam a si mesmos) se as filas subsequentes estiverem cheias.
- **Interrupção Graciosa (Hooks):** Os jobs já checam `_context.IsSourcePausedOrStoppedAsync(sourceId, ct)` no início e no meio dos loops para pararem graciosamente e salvarem os cursores.

**O que AINDA FALTA resolver (A Crise Atual):**

1. **State Machine e API de Controle:** Apesar de termos os "hooks" de Pause nos Jobs, não temos a API e a modelagem formal no banco para que o operador (via Dashboard) possa enviar comandos de `Pause`, `Resume` ou `Stop` para uma fonte. Precisamos conectar a ponta da API e do repositório aos hooks que já existem.
2. **Batch Sizing Dinâmico e Limite de Memória (300MB) nas fases que carregam conteúdo:** 
   - Fontes massivas possuem documentos gigantescos (ex: acórdãos com centenas de páginas).
   - **Ingest (fan-out):** Já está seguro: só lê páginas de 200 *(Id, ContentLength)* e usa `FormBatches` por `MaxCharsPerBatch`/`MaxDocsPerBatch` (YAML). Não carrega corpo dos documentos; o risco de 5.000 docs na RAM não se aplica ao fluxo atual. A projeção de mídia carrega até 1000 itens por run — avaliar se há risco de memória nesse trecho.
   - **Fetch:** Processa 25 documentos por batch (`BatchSize = 25`). Se baixar 25 PDFs/respostas gigantes de uma vez, pode estourar a memória. Precisa de limite por tamanho (bytes/tokens) ou redução dinâmica do batch.
   - **EmbedAndIndex:** Recebe lotes formados pelo Ingest (já limitados por chars + até 32 docs). Ainda assim carrega o conteúdo completo de todos os docs do lote, faz chunk + embed de uma vez. Um lote com poucos docs muito grandes (muitos chunks) pode estourar 300MB ou o limite da API de embedding. Garantir flush/streaming ou sub-batches por chunk/token.
   - Objetivo: garantir que *Fetch* e *EmbedAndIndex* (e, se relevante, a projeção de mídia no Ingest) nunca ultrapassem 300MB.

## 2. Abordagem Proposta

O prompt abaixo instrui a LLM a completar a Máquina de Estados e a implementar salvaguardas de memória (Dynamic Batch Sizing) para os executores.

---

# Prompt para a LLM de Código

```markdown
You are a Staff Distributed Systems Engineer working on GABI, a .NET 8 legal document ingestion pipeline using PostgreSQL and Hangfire.

**The Context:**
Our pipeline processes massive document sources (500,000+ docs). We have a strict 300MB process memory limit. 
We have ALREADY implemented the foundational backpressure mechanisms (yielding based on DB counts) and the graceful interruption hooks (`IsSourcePausedOrStoppedAsync`) inside `DiscoveryJobExecutor`, `FetchJobExecutor`, and `IngestJobExecutor`.

**The Remaining Challenges:**

1. **State Management API & Persistence:** We have the hooks checking for "Paused/Stopped" state, but we lack the actual Database schema/entity (`SourceExecutionState`?) and the API endpoints (or commands) to trigger Start, Pause, Resume, and Stop for a specific `source_id`.
2. **Dynamic Batch Sizing (The Memory Crisis):** Documents vary wildly in size (from 1KB to 10MB+ text). 
   - `IngestJobExecutor` fan-out is already safe: it only reads pages of (Id, ContentLength) and uses `FormBatches` (MaxCharsPerBatch, MaxDocsPerBatch from YAML). It does NOT load 5000 document bodies. Do not change that. Optionally review the media-projection path (up to 1000 items per run) for memory risk.
   - `FetchJobExecutor` processes 25 documents per batch (`BatchSize = 25`). Downloading/parsing 25 massive PDFs or JSON responses at once can exceed 300MB. Add size-aware batching or reduce batch size when payloads are large.
   - `EmbedAndIndexJobExecutor` receives batches (already limited by Ingest to ~32 docs and char budget). It still loads full content for the whole batch, then chunks and embeds. A few very large documents (thousands of chunks) can blow memory or API limits. Add token/byte-aware sub-batching or streaming flush so we never hold all chunks in memory.

**Your Task:**

Provide the C# implementation to solve these two challenges securely and efficiently.

### Part 1: Source State Management
1. **Entity & Repository:** Create or complete the DB table/entity that `_context.IsSourcePausedOrStoppedAsync` reads from. How do we track the `TargetState` vs `CurrentState`?
2. **API / Commands:** Implement the handlers or minimal API endpoints that allow an operator to send `Pause`, `Resume`, and `Stop` signals for a source.

### Part 2: Dynamic Batch Sizing & Memory Safety
Protect the 300MB boundary in the executors that load full document content. Do **not** change IngestJobExecutor's fan-out logic (it already uses Id+ContentLength and FormBatches; it does not load document bodies).
1. **FetchJobExecutor:** Ensure HTTP stream reading and DB writes for massive responses (PDFs, CSV, JSON) do not buffer entire responses in memory. Consider size-aware batch size (e.g. reduce from 25 when estimated or actual payload size is large) or process one-by-one when size exceeds a threshold.
2. **EmbedAndIndexJobExecutor:** Batches are already limited by Ingest (chars + doc count). This executor still loads the full batch of documents, chunks all, then embeds. For documents that produce thousands of chunks, add token/byte-aware sub-batching: chunk and embed in smaller flushes, or process one document at a time when chunk count exceeds a safe threshold, so we never hold all chunks + embeddings in memory at once.
3. **IngestJobExecutor (optional):** Only review the media-projection path (MaxMediaItemsPerRun) for memory risk; leave the main fan-out as-is.

*Rules:*
- Adhere strictly to .NET 8 and C# 12 conventions.
- Do not remove the existing backpressure logic (the DB count checks and `_jobQueue.ScheduleAsync` yields).
- Optimize for predictable memory usage (GC pressure) over absolute speed. 
```