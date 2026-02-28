# GABI - Arquitetura de Memória

## ⚠️ AMBIENTE SERVERLESS - SEM DISCO

O GABI opera em ambientes serverless (Fly.io) com **1GB RAM** e **sem disco persistente**. Não há spill para disco. A arquitetura é projetada para:

1. **Streaming end-to-end** - nunca acumular dados
2. **Backpressure** - pausar quando sob pressão
3. **Descarte controlado** - último recurso, nunca spill
4. **Processamento sequencial** - concurrency = 1

---

## Memory Budget (1GB RAM)

| Componente | Memória | % do Total |
|------------|---------|------------|
| .NET Runtime | ~200MB | 20% |
| Worker + Pipeline | ~100MB | 10% |
| Job ativo (streaming) | ~50MB | 5% |
| PostgreSQL connections | ~20MB | 2% |
| **Safety margin** | **~600MB** | **60%** |
| Buffers/Overhead | ~30MB | 3% |

---

## Pipeline Stages

### 1. Fetch (Download)

```
HTTP Response Stream
    ↓
64KB chunks (configurável)
    ↓
Parse on-the-fly
    ↓
Discard chunk imediatamente
```

**❌ NUNCA:**
```csharp
// NUNCA FAÇA ISSO - carrega 587MB na RAM!
var content = await response.Content.ReadAsStringAsync();
```

**✅ SEMPRE:**
```csharp
// Stream - processa 64KB por vez
await foreach (var chunk in response.StreamChunks(64 * 1024))
{
    Process(chunk);
    // chunk é descartado após processamento
}
```

### 2. Parse (CSV/PDF)

- **CSV:** Parser streaming (linha a linha)
- **PDF:** Page-by-page processing
- **Max document size:** 10MB (rejeita se maior)

### 3. Chunk (Divisão)

```
Documento texto
    ↓
Chunk 1 (512 tokens) → processa → libera
Chunk 2 (512 tokens) → processa → libera
...
```

**Economia de memória:** `DiscardSourceText = true` após chunking.

### 4. Embed (Geração de embeddings)

- **Batch size:** 32-64 chunks (nunca mais)
- **Rate limiting:** 100ms entre batches
- **Economia:** `DiscardChunksAfterEmbedding = true`

### 5. Index (Elasticsearch)

- **Bulk size:** 50 documentos
- **Flush interval:** a cada 50 docs (não acumula)
- **Economia:** `DiscardAfterIndex = true`

### 6. Graph (Neo4j)

- **Batch size:** 100 nós/arestas
- Unload frequente para não acumular

---

## Backpressure

Quando memória > 75% (750MB):

1. **Pausa** o pipeline (não descarta)
2. **Aguarda** GC
3. **Resume** quando < 70%

```csharp
while (memory > threshold)
{
    GC.Collect();
    await Task.Delay(100);
}
```

Se pressão persistir por > 10 segundos:
- Opção A: Falha o pipeline (padrão)
- Opção B: Descarta items (configurável)

---

## Configuração por Source

```yaml
# sources_v2.yaml
fetch:
  streaming:
    enabled: true
    chunk_size: 64KB      # ← nunca muito grande
    max_size: 500MB       # ← rejeita se maior

pipeline:
  limits:
    max_parallelism: 1    # ← SEMPRE 1 em 1GB
    batch_size: 50        # ← batches pequenos
    backpressure_delay: 100ms
```

---

## Monitoramento

### Métricas exportadas

```
# Prometheus-style
gabi_memory_usage_bytes
gabi_memory_threshold_bytes
gabi_memory_pressure_ratio
gabi_pipeline_backpressure_events_total
gabi_pipeline_backpressure_duration_seconds
gabi_pipeline_documents_dropped_total
```

### Alertas

| Condição | Ação |
|----------|------|
| `memory_pressure_ratio > 0.8` | Página on-call |
| `backpressure_duration > 5min` | Escalar para máquina maior |
| `documents_dropped > 0` | Investigar imediatamente |

---

## Scaling

### Quando escalar?

| Sintoma | Causa | Solução |
|---------|-------|---------|
| Pipeline lento | Backpressure frequente | Fly Machine com 2GB |
| Timeout | Documentos muito grandes | Aumentar timeout + memória |
| Drops | Memória insuficiente | 2GB + paralelismo = 2 |

### Configurações por tamanho

| VM | RAM | MaxParallelism | BatchSize |
|----|-----|----------------|-----------|
| shared-cpu-2x | 1GB | 1 | 50 |
| shared-cpu-4x | 2GB | 2 | 100 |
| dedicated-cpu | 4GB+ | 4 | 200 |

---

## Checklist de Implementação

- [ ] Fetch usa `StreamChunks()`, nunca `ReadAsStringAsync()`
- [ ] Parse é streaming (linha/record por vez)
- [ ] Chunk libera texto original após processar
- [ ] Embed usa batches ≤ 64 chunks
- [ ] Index flushes a cada 50 documentos
- [ ] MemoryManager aplica backpressure
- [ ] Logs de métricas de memória
- [ ] Alertas configurados

---

## Anti-Patterns

❌ **Lista acumulando:**
```csharp
var allRows = new List<Row>(); // NUNCA!
await foreach (var row in parser)
    allRows.Add(row);
```

❌ **String gigante:**
```csharp
var content = File.ReadAllText("587MB.csv"); // NUNCA!
```

❌ **Paralelismo excessivo:**
```csharp
await Parallel.ForEachAsync(sources, new ParallelOptions 
{ 
    MaxDegreeOfParallelism = 4 // NUNCA em 1GB!
}, ...);
```

✅ **Pipeline streaming:**
```csharp
await foreach (var doc in Fetch(source))
    await Index(await Embed(await Chunk(await Parse(doc))));
```
