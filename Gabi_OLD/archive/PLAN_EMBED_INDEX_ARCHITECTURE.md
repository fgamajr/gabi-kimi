# Plano de Implementação: Separação de Estágios Embed e Index (Option B - Minimum Viable Separation)

## 1. Contexto e Decisão Arquitetural
Devido às restrições estritas de memória (300MB) e às características de I/O das chamadas de API de Embedding e do Elasticsearch, a abordagem monolítica (Option A) é inviável. A decisão arquitetural é a **Opção B com Separação Mínima Viável**:
- **Embed e Index combinados em um único Job**: Evita overhead de persistência intermediária de vetores no Postgres apenas para leitura subsequente.
- **Filas separadas**: O processo de `Ingest` enfileira múltiplos jobs de `EmbedAndIndex`.
- **Granularidade**: `Ingest` processa 5000 documentos e faz fan-out para jobs de `EmbedAndIndex` em lotes menores (32-64 documentos) para manter o consumo de memória baixo e permitir retentativas isoladas em caso de `429 Too Many Requests`.

## 2. Passos de Implementação

### Passo 2.1: Definição de Contratos e Estágios
- Atualizar/Verificar os contratos de `PipelineStages` para refletir o estágio `Embed` (ou `EmbedAndIndex`).
- Definir interfaces como `IEmbedService` e `IIndexService` (se ainda não existirem) em `Gabi.Contracts`.

### Passo 2.2: Configuração do Hangfire (Filas e Workers)
- Adicionar uma nova fila chamada `embed` na configuração do Hangfire (`["seed", "discovery", "fetch", "ingest", "embed", "default"]`).
- Configurar o pool de workers para respeitar o limite de 300MB:
  - Fila `ingest` (pesada): Limitar a 1 worker (ou garantir que a concorrência não estoure a memória).
  - Fila `embed` (I/O bound): 2 a 4 workers para paralelizar chamadas de rede.

### Passo 2.3: Criar o `EmbedAndIndexJobExecutor`
- Implementar o job que receberá um lote de IDs de documentos (ex: 32 a 64 IDs) ou executará uma query para buscar documentos pendentes de embedding.
- O fluxo dentro do job deve ser:
  1. Carregar os documentos do Postgres.
  2. Gerar chunks de texto (se necessário).
  3. Chamar a API de Embedding.
  4. Realizar o *bulk push* dos vetores para o Elasticsearch.
  5. Atualizar o status dos documentos no Postgres para concluído.

### Passo 2.4: Atualizar o `IngestJobExecutor` (Fan-out)
- Modificar o estágio final do `IngestJobExecutor`. Após salvar os 5000 documentos no banco de dados, ele deve dividir esses documentos em lotes de 32 a 64.
- Enfileirar um `EmbedAndIndexJob` para cada lote.

### Passo 2.5: Adaptar o Controle de Single-In-Flight
- Avaliar o `HangfireJobQueueRepository` (que atualmente prevê 1 job por source por tipo).
- Como o `Ingest` fará fan-out de *múltiplos* jobs de `Embed` para a mesma source, a regra de Single-In-Flight para o tipo `Embed` não pode bloquear o processamento paralelo dos lotes dessa mesma source, ou o lock deve ser feito por *lote* e não por *source*. A solução mais simples é contornar o lock de source-level para jobs do tipo `EmbedAndIndex`, permitindo que múltiplos lotes da mesma source rodem concorrentemente até o limite de workers da fila `embed`.

### Passo 2.6: Tratamento de Erros e Resiliência
- Implementar um filtro de retentativa específico ou capturar exceções HTTP 429 na API de Embedding.
- Configurar backoff exponencial e respeitar o cabeçalho `Retry-After`.

---

# Prompt para a LLM de Código

```markdown
You are an expert C# .NET 8 backend developer working on GABI, a distributed legal document ingestion pipeline. 
We have made an architectural decision to implement the "Embed" and "Index" stages using a "Minimum Viable Separation" choreographic pattern via Hangfire.

**Current State:**
- The pipeline ends at `IngestJobExecutor`, which processes batches of 5000 documents and saves them to PostgreSQL.
- We have a strict 300MB process memory limit.
- Hangfire uses a Single-In-Flight lock per source/job-type (`HangfireJobQueueRepository`).

**Task Overview:**
Implement the fan-out from `Ingest` to a new combined `EmbedAndIndex` job stage.

**Implementation Requirements:**

1. **New Job Executor (`EmbedAndIndexJobExecutor`):**
   - Create a new Hangfire job executor for the `embed` queue.
   - It should take a source ID and a batch of Document IDs (or a specific range/batch ID). Size: 32-64 documents.
   - Logic: 
     a. Fetch document text from Postgres.
     b. Chunk text and call `IEmbedService` (assume interface exists or create a stub).
     c. Call `IIndexService` to bulk index into Elasticsearch (stub if needed).
     d. Update document status in Postgres.
   - Must handle `429 Too Many Requests` gracefully (e.g., throw a specific exception that triggers a customized Hangfire retry policy with delay).

2. **Update `IngestJobExecutor` (The Fan-out):**
   - After successfully persisting the 5000 documents in Postgres, slice the processed document IDs into chunks of 64.
   - Enqueue a Hangfire job for `EmbedAndIndexJobExecutor` for each chunk.

3. **Queue Configuration (`Program.cs` / App config):**
   - Ensure the Hangfire queues are ordered: `["seed", "discovery", "fetch", "ingest", "embed", "default"]`.

4. **Concurrency & Single-In-Flight Adjustment:**
   - Because `Ingest` enqueues MULTIPLE `EmbedAndIndex` jobs for the same source, you must ensure `HangfireJobQueueRepository` allows concurrent `EmbedAndIndex` jobs for the same source, OR modify the job design so it polls pending documents for a source in a loop (if keeping the strict single-in-flight per source). *Decide the best approach: we prefer allowing multiple batches to process concurrently for network I/O speed, so relaxing the lock for this specific job type is preferred.*

**Constraints:**
- Use file-scoped namespaces.
- Use `record` for DTOs/commands.
- Pass `CancellationToken` to all async methods.
- Keep memory allocation minimal (use `IAsyncEnumerable` where applicable, though batch size of 64 makes lists acceptable here).
- Do not modify existing working logic of Discovery or Fetch.

Please output the necessary C# files/modifications to implement this pattern.
```
