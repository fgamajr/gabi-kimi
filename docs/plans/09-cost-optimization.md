# GABI - Plano de Otimização de Custos Cloud

## Executive Summary

Este documento apresenta estratégias de arquitetura custo-efetiva para o GABI (sistema de ingestão e busca jurídica TCU) considerando:

- **13 fontes de dados** com arquivos de até 587MB
- **Restrição de 1GB RAM** no Fly.io (shared-cpu-2x)
- **Embeddings 384-dim** (MiniLM-L12-v2)
- **Stack**: PostgreSQL, Elasticsearch, Redis, TEI (Text Embeddings Inference)

## 1. Resource Scheduling (Jobs em Horário de Pouca Uso)

### 1.1 Estratégia de Scheduling Inteligente

```yaml
# sources_v2.yaml - Configuração otimizada de schedules
sources:
  # Sources grandes: executar em horários diferentes para evitar contenção
  tcu_normas:           # 587MB - maior arquivo
    pipeline:
      schedule: "0 1 * * 0"   # Domingo 1AM (semanal)
      mode: full_reload
      
  tcu_acordaos:         # Múltiplos anos (1992-2026)
    pipeline:
      schedule: "0 2 * * *"   # Diário 2AM (incremental)
      mode: incremental
      
  # Sources pequenas: agrupar no mesmo horário
  tcu_sumulas:
    pipeline:
      schedule: "0 4 * * *"   # 4AM
      
  tcu_jurisprudencia_selecionada:
    pipeline:
      schedule: "0 4 * * *"   # Mesmo horário (concorrência controlada)
```

### 1.2 Fly Machines com Auto-start/Stop

```toml
# fly.worker.toml
[processes]
  app = "dotnet Gabi.Worker.dll"

[[vm]]
  size = 'shared-cpu-2x'
  memory = '1gb'
  # Auto-stop após job (para cron jobs)
  auto_stop = true
  auto_start = true

# Schedule: Machine só existe durante execução do job
[[schedules]]
  cron = "0 1 * * 0"
  command = "dotnet Gabi.Worker.dll --source=tcu_normas"
```

### 1.3 Implementação de Job Scheduler

```csharp
// Gabi.Sync/Scheduling/CostOptimizedScheduler.cs
public class CostOptimizedScheduler
{
    // Agrupa sources por "tamanho estimado" para balancear carga
    private readonly Dictionary<JobSize, TimeWindow> _schedule = new()
    {
        [JobSize.Large] = new TimeWindow("01:00", "03:00"),    // 587MB files
        [JobSize.Medium] = new TimeWindow("03:00", "05:00"),   // ~100MB
        [JobSize.Small] = new TimeWindow("05:00", "06:00"),    // <10MB
        [JobSize.Incremental] = new TimeWindow("02:00", "04:00") // Delta small
    };
    
    public async Task ScheduleJobsAsync(IEnumerable<SourceConfig> sources)
    {
        // Agrupa sources para minimizar cold starts
        var batches = sources
            .GroupBy(s => EstimateSize(s))
            .SelectMany(g => g.Chunk(2)); // Max 2 concorrentes
            
        foreach (var batch in batches)
        {
            var window = _schedule[EstimateSize(batch.First())];
            await ScheduleBatchAsync(batch, window);
        }
    }
}
```

**Economia estimada**: 60-70% do tempo de máquina (só paga durante execução)

---

## 2. Incremental Processing (Só Processar o que Mudou)

### 2.1 Multi-Camada de Change Detection

```
┌─────────────────────────────────────────────────────────────────┐
│                    CHANGE DETECTION PIPELINE                     │
├─────────────────────────────────────────────────────────────────┤
│  Level 1: HTTP ETag/Last-Modified (zero download)               │
│     ↓ SKIP se não mudou                                         │
│  Level 2: Content-Length comparison                             │
│     ↓ SKIP se igual                                             │
│  Level 3: Header hash (primeiros 1KB)                           │
│     ↓ SKIP se igual                                             │
│  Level 4: Full content hash (SHA-256) - apenas se necessário   │
│     ↓ PROCESS                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Estrutura de Cache em Redis

```yaml
# Redis key structure para change detection
change_detection:
  # Nível 1: Metadados HTTP (TTL: 24h)
  "cd:http:{source_id}:{url_hash}":
    etag: "\"abc123\""
    last_modified: "Wed, 21 Oct 2025 07:28:00 GMT"
    content_length: 587000000
    
  # Nível 2: Hash parcial (primeiros 8KB)
  "cd:header:{source_id}:{url_hash}":
    partial_hash: "sha256:xyz789..."
    
  # Nível 3: Hash completo (confirmação)
  "cd:full:{source_id}:{url_hash}":
    content_hash: "sha256:full123..."
    fingerprint: "sha256:doc456..."
    processed_at: "2025-01-15T02:00:00Z"
```

### 2.3 Implementação Delta para CSVs Grandes

```csharp
// Gabi.Ingest/Delta/DeltaCsvProcessor.cs
public class DeltaCsvProcessor
{
    // Para arquivos grandes (587MB), manter índice por linha
    public async Task<DeltaResult> ProcessDeltaAsync(
        Stream csvStream, 
        string sourceId)
    {
        var rowIndex = await _cache.GetRowIndexAsync(sourceId);
        var changedRows = new List<Row>();
        
        await foreach (var row in csvStream.ParseCsvStreaming())
        {
            var rowHash = ComputeHash(row);
            var key = $"{source_id}:{row[id_column]}";
            
            if (rowIndex.TryGetValue(key, out var cachedHash))
            {
                if (cachedHash == rowHash)
                {
                    _metrics.RowsSkipped++;
                    continue; // Row unchanged
                }
            }
            
            rowIndex[key] = rowHash;
            changedRows.Add(row);
        }
        
        await _cache.SaveRowIndexAsync(sourceId, rowIndex);
        return new DeltaResult(changedRows, rowIndex.Count);
    }
}
```

### 2.4 Taxa de Mudança Estimada por Source

| Source | Tamanho | Frequência | % Mudança/Dia | Processamento |
|--------|---------|------------|---------------|---------------|
| tcu_normas | 587MB | Semanal | ~0.5% | Delta rows |
| tcu_acordaos | ~150MB/ano | Diário | ~0.1% (novos) | Incremental ano |
| tcu_sumulas | ~5MB | Diário | ~0.01% | Full (pequeno) |
| tcu_publicacoes | Variável | Semanal | ~10% | Delta + novo |

**Economia estimada**: 95-99% de processamento evitado em sources estáveis

---

## 3. Tiered Storage (Hot/Warm/Cold)

### 3.1 Arquitetura de Três Camadas

```
┌─────────────────────────────────────────────────────────────────┐
│                         HOT STORAGE                              │
│  PostgreSQL (1-3 meses) + Elasticsearch                         │
│  • Busca em tempo real                                          │
│  • Embeddings em pgvector                                       │
│  • Alta disponibilidade                                         │
│  Custo: ~$15/mês (Fly Postgres)                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (arquivamento automático)
┌─────────────────────────────────────────────────────────────────┐
│                        WARM STORAGE                              │
│  PostgreSQL apenas (3-12 meses)                                 │
│  • Sem embeddings (regeneráveis)                                │
│  • Sem índice ES (tsvector só)                                  │
│  • Acesso ocasional                                             │
│  Custo: Mesmo PG, menos ES                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓ (compressão + backup)
┌─────────────────────────────────────────────────────────────────┐
│                        COLD STORAGE                              │
│  Object Storage (S3/R2) + Compressed                            │
│  • JSON comprimido (gzip/zstd)                                  │
│  • Glacier para >2 anos                                         │
│  • Restauração on-demand                                        │
│  Custo: ~$0.50/mês por 100GB                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Política de Lifecycle Automatizada

```csharp
// Gabi.Sync/Storage/TieredStorageManager.cs
public class TieredStorageManager
{
    public async Task ArchiveOldDocumentsAsync()
    {
        // Hot → Warm (3 meses)
        var toWarm = await _db.Documents
            .Where(d => d.LastAccessed < DateTime.UtcNow.AddMonths(-3))
            .Where(d => d.StorageTier == StorageTier.Hot)
            .Take(1000)
            .ToListAsync();
            
        foreach (var doc in toWarm)
        {
            // Remove embeddings (regeneráveis)
            await _embeddings.DeleteAsync(doc.Id);
            // Remove do ES
            await _elastic.DeleteAsync(doc.Id);
            // Atualiza tier
            doc.StorageTier = StorageTier.Warm;
            doc.EmbeddingStatus = EmbeddingStatus.Archived;
        }
        
        // Warm → Cold (1 ano)
        var toCold = await _db.Documents
            .Where(d => d.LastAccessed < DateTime.UtcNow.AddYears(-1))
            .Where(d => d.StorageTier == StorageTier.Warm)
            .Take(500)
            .ToListAsync();
            
        foreach (var doc in toCold)
        {
            // Exporta para JSON comprimido
            var compressed = await CompressDocumentAsync(doc);
            await _objectStorage.UploadAsync(
                $"cold/{doc.SourceId}/{doc.Id}.json.zst", 
                compressed);
            // Marca no PG como cold
            doc.StorageTier = StorageTier.Cold;
            doc.Content = null; // Libera espaço
        }
        
        await _db.SaveChangesAsync();
    }
}
```

### 3.3 Configuração de Retenção

```yaml
# storage_policy.yaml
retention_policy:
  hot:
    max_age_days: 90
    keep_embeddings: true
    elasticsearch_indexed: true
    
  warm:
    max_age_days: 365
    keep_embeddings: false  # Regenerável via TEI
    elasticsearch_indexed: false
    pg_tsvector: true       # Busca texto nativa
    
  cold:
    compression: zstd       # Melhor que gzip
    storage: r2             # Cloudflare R2 (zero egress)
    restore_on_access: true
    
  delete_after_years: 7     # Compliance legal
```

---

## 4. Embedding Caching (Não Re-embed Conteúdo Igual)

### 4.1 Deduplicação de Embeddings

```csharp
// Gabi.Sync/Embed/EmbeddingCache.cs
public class EmbeddingDeduplicator
{
    // Cache de conteúdo → embedding (hash do texto)
    private readonly IDistributedCache _cache;
    
    public async Task<IReadOnlyList<float>> GetOrComputeAsync(
        string text, 
        Func<string, Task<IReadOnlyList<float>>> compute)
    {
        // Normaliza texto (remove espaços extras, lowercase)
        var normalized = NormalizeText(text);
        var contentHash = ComputeHash(normalized);
        
        // Tenta cache
        var cached = await _cache.GetAsync($"emb:{contentHash}");
        if (cached != null)
        {
            _metrics.EmbeddingCacheHit++;
            return Deserialize(cached);
        }
        
        // Computa e armazena
        var embedding = await compute(normalized);
        await _cache.SetAsync(
            $"emb:{contentHash}",
            Serialize(embedding),
            new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = TimeSpan.FromDays(365),
                // Embeddings são imutáveis - cache longo
            });
            
        return embedding;
    }
}
```

### 4.2 Cache Hierárquico

```
┌─────────────────────────────────────────────────────────────────┐
│                    EMBEDDING CACHE LAYERS                        │
├─────────────────────────────────────────────────────────────────┤
│  L1: In-Memory (Processo)                                       │
│     • LRU cache: 10K embeddings                                 │
│     • Hit time: <1μs                                            │
│                                                                 │
│  L2: Redis (Instance Local)                                     │
│     • TTL: 7 dias                                               │
│     • Hit time: ~1ms                                            │
│     • Eviction: LRU quando maxmemory atingido                   │
│                                                                 │
│  L3: PostgreSQL (Persistent)                                    │
│     • Tabela: embedding_cache                                   │
│     • Colunas: content_hash (PK), vector (384 dim)              │
│     • Hit time: ~5ms                                            │
│     • Custo: ~100 bytes/embedding                               │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Tabela de Cache Persistente

```sql
-- migration: create embedding cache table
CREATE TABLE embedding_cache (
    content_hash CHAR(64) PRIMARY KEY,  -- SHA-256 do texto normalizado
    vector vector(384) NOT NULL,
    model_version VARCHAR(50) NOT NULL, -- 'sentence-transformers/all-MiniLM-L12-v2'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    access_count INT DEFAULT 1,
    last_accessed TIMESTAMPTZ DEFAULT NOW()
);

-- Índice para cleanup de entries antigas
CREATE INDEX idx_embedding_cache_accessed 
ON embedding_cache(last_accessed) 
WHERE last_accessed < NOW() - INTERVAL '1 year';

-- Cleanup mensal
DELETE FROM embedding_cache 
WHERE last_accessed < NOW() - INTERVAL '2 years';
```

### 4.4 Taxa de Cache Esperada

| Cenário | Taxa de Repetição | Economia |
|---------|-------------------|----------|
| Acórdãos (texto similar) | ~30% | 30% calls TEI |
| Normas (artigos replicados) | ~50% | 50% calls TEI |
| Súmulas (imutáveis) | ~95% | 95% calls TEI |

---

## 5. Compression Strategies

### 5.1 Compressão em Múltiplas Camadas

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMPRESSION STACK                             │
├─────────────────────────────────────────────────────────────────┤
│  Transporte (HTTP)          gzip/br (automático)                │
│  Storage (JSON/docs)        zstd level 3                        │
│  Embeddings (vectors)       fp16 quantization                   │
│  Backup/Archive             zstd level 19                       │
│  Full-Text Index            tsvector (nativo PG)                │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Compressão de Embeddings (Quantization)

```csharp
// Gabi.Sync/Embed/EmbeddingQuantization.cs
public static class EmbeddingQuantization
{
    // FP32 → FP16: 50% redução, <0.1% perda de precisão
    public static byte[] ToHalfPrecision(float[] embedding)
    {
        var result = new byte[embedding.Length * 2]; // 2 bytes por float
        for (int i = 0; i < embedding.Length; i++)
        {
            var half = (Half)embedding[i];
            BitConverter.GetBytes(half).CopyTo(result, i * 2);
        }
        return result;
    }
    
    // Int8 quantization: 75% redução, ~1% perda
    public static byte[] ToInt8(float[] embedding)
    {
        // Encontra min/max para scaling
        var min = embedding.Min();
        var max = embedding.Max();
        var scale = (max - min) / 255f;
        
        return embedding.Select(f => (byte)((f - min) / scale)).ToArray();
    }
}
```

### 5.3 Storage Format Otimizado

```yaml
# Armazenamento de documentos
document_storage:
  # JSON com campos comprimidos
  format: json+zstd
  
  # Campos grandes comprimidos individualmente
  compression:
    content: zstd        # Texto comprime bem (5-10x)
    metadata: none       # Pequeno, não vale
    
  # Chunking de storage para acesso parcial
  chunk_size: 64KB
  
# Exemplo de economia
example_savings:
  raw_document: "100KB texto"
  json: "110KB"
  json_gzip: "25KB"      # 4.4x
  json_zstd: "18KB"      # 6.1x (melhor)
```

### 5.4 Compressão de Elasticsearch

```json
// Index template com compressão
{
  "index": {
    "codec": "best_compression",
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "refresh_interval": "30s"
  },
  "mappings": {
    "_source": {
      "compress": true,
      "compress_threshold": "1kb"
    }
  }
}
```

---

## 6. Right-sizing Fly Machines

### 6.1 Estratégia de Scale-to-Zero

```toml
# fly.api.toml - API sempre disponível (usuários)
[http_service]
  internal_port = 8080
  force_https = true
  auto_stop = false      # API: nunca para
  auto_start = true
  min_machines_running = 1

[[vm]]
  size = 'shared-cpu-1x'  # API leve: 256MB suficiente
  memory = '256mb'
```

```toml
# fly.worker.toml - Worker: scale-to-zero
[processes]
  app = "dotnet Gabi.Worker.dll"

[[vm]]
  size = 'shared-cpu-2x'
  memory = '1gb'
  auto_stop = true       # Para quando idle
  auto_start = true      # Inicia no schedule
  min_machines_running = 0

# Executa via scheduler externo (GitHub Actions / cron-job.org)
[[schedules]]
  cron = "0 2 * * *"
  command = "dotnet Gabi.Worker.dll --source=all"
```

### 6.2 Escalagem por Demanda

```csharp
// Gabi.Sync/Scaling/AdaptiveScaler.cs
public class AdaptiveScaler
{
    // Monitora queue depth e escala workers
    public async Task ScaleIfNeededAsync()
    {
        var queueDepth = await _redis.ListLengthAsync("gabi:queue:pending");
        var activeWorkers = await _redis.StringGetAsync("gabi:workers:active");
        
        // Regras de escalagem
        var desiredWorkers = queueDepth switch
        {
            > 1000 => 4,
            > 500 => 2,
            > 100 => 1,
            _ => 0  // Scale to zero
        };
        
        if (desiredWorkers > int.Parse(activeWorkers))
        {
            await ScaleUpAsync(desiredWorkers);
        }
        else if (desiredWorkers < int.Parse(activeWorkers) && queueDepth == 0)
        {
            await ScaleDownAsync(desiredWorkers);
        }
    }
}
```

### 6.3 Machine Sizing por Carga

| Componente | VM Size | RAM | Uso | Custo/Mês |
|------------|---------|-----|-----|-----------|
| gabi-api | shared-cpu-1x | 256MB | 24/7 | ~$2 |
| gabi-worker (idle) | - | - | 0h | $0 |
| gabi-worker (job) | shared-cpu-2x | 1GB | 2h/dia | ~$0.30 |
| postgres | - | 1GB | Fly mini | ~$5 |
| redis | - | 256MB | Fly Upstash | ~$0 (free) |

### 6.4 Alternativa: Scheduled Jobs via GitHub Actions

```yaml
# .github/workflows/gabi-sync.yml
name: GABI Sync

on:
  schedule:
    - cron: '0 2 * * *'  # 2AM UTC
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger Fly Machine
        run: |
          flyctl machine run . \
            --app gabi-worker \
            --env "GABI_JOB=all" \
            --vm-size shared-cpu-2x \
            --vm-memory 1gb \
            --auto-destroy  # Mata após execução
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

**Economia**: Paga apenas durante execução (~2h/dia = ~$0.30/mês vs $5/mês 24/7)

---

## 7. Alternative: Supabase vs Self-Hosted

### 7.1 Comparação de Arquiteturas

```
┌─────────────────────────────────────────────────────────────────┐
│                     OPÇÃO A: SELF-HOSTED                         │
│                     (Fly.io + Postgres)                          │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Controle total sobre infraestrutura                          │
│  ✓ Custo previsível                                             │
│  ✓ Possível escalar para dedicated CPU                          │
│  ✗ Gerenciamento de backups, updates                            │
│  ✗ Configuração inicial mais complexa                           │
│                                                                 │
│  Custo estimado (1K docs/dia): ~$12/mês                         │
│  Custo estimado (10K docs/dia): ~$25/mês                        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     OPÇÃO B: SUPABASE                            │
│              (Postgres gerenciado + pgvector)                    │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Postgres gerenciado (backups automáticos)                    │
│  ✓ pgvector incluído                                            │
│  ✓ Edge Functions para jobs (cron integrado)                    │
│  ✓ Auth/Storage incluídos (futuro)                              │
│  ✗ Limites no free tier (500MB DB, 2GB egress)                  │
│  ✗ Cold starts nas Edge Functions                               │
│  ✗ Vendor lock-in                                               │
│                                                                 │
│  Free Tier: 500MB DB, 2GB egress/mês                            │
│  Pro Tier ($25/mês): 8GB DB, 100GB egress                       │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Supabase Architecture

```yaml
# Configuração GABI em Supabase
supabase_config:
  database:
    tier: free  # ou pro para produção
    extensions:
      - pgvector
      - pg_cron  # Jobs agendados
      
  edge_functions:
    # Substituir Gabi.Worker
    sync_job:
      runtime: deno
      memory: 256MB
      timeout: 300s  # 5 min max no free tier
      schedule: "0 2 * * *"
      
  storage:
    # Cold storage para arquivos grandes
    buckets:
      - name: cold-documents
        compression: true
        
  realtime:
    # Notificações de progresso
    enabled: true
```

### 7.3 Trade-offs Detalhados

| Aspecto | Fly Self-Hosted | Supabase |
|---------|-----------------|----------|
| **Custo inicial** | $5/mês (mínimo) | $0 (free tier) |
| **Custo 10K docs/mês** | ~$25/mês | $25/mês (Pro) |
| **Setup** | Mais complexo | Simples |
| **Backups** | Manual/script | Automático |
| **pgvector** | Instalar manual | Built-in |
| **Escalabilidade** | Ilimitada | Limites por tier |
| **Embeddings (TEI)** | Rodar na Fly | Não suportado* |
| **ES/Reranker** | Rodar na Fly | Não suportado |
| **Multi-region** | Complexo | Built-in |

*TEI = Text Embeddings Inference (container local)

### 7.4 Recomendação Híbrida

```
┌─────────────────────────────────────────────────────────────────┐
│                    ARQUITETURA HÍBRIDA                           │
│              (Supabase + Fly para workloads)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Supabase (Free/Pro):                                           │
│    ├── PostgreSQL + pgvector (documentos + embeddings)          │
│    ├── Edge Functions (discovery leve, API)                     │
│    └── Storage (cold backups)                                   │
│                                                                 │
│  Fly.io (On-demand):                                            │
│    ├── TEI (embeddings - GPU se necessário)                     │
│    ├── Elasticsearch (full-text avançado)                       │
│    └── Worker pesado (processar 587MB files)                    │
│                                                                 │
│  Vantagem: Melhor dos dois mundos                               │
│  Custo: ~$10-20/mês para 10K docs                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Cálculo de Custos

### 8.1 Cenário: 1.000 Documentos/Dia

#### Assumptions

| Parâmetro | Valor |
|-----------|-------|
| Documentos/dia | 1.000 |
| Tamanho médio/doc | 10KB |
| Chunks/doc (médio) | 5 |
| Embeddings gerados/dia | 5.000 |
| Total docs armazenados (ano) | ~365K |
| Storage anual (texto) | ~3.6GB |
| Storage embeddings | ~1.4GB (384-dim × 4 bytes) |

#### Custos Fly.io (Self-Hosted)

| Componente | Config | Horas/Dia | Custo/Mês |
|------------|--------|-----------|-----------|
| gabi-api | shared-cpu-1x (256MB) | 24 | $1.94 |
| gabi-worker | shared-cpu-2x (1GB) | 2 | $0.32 |
| postgres | Fly mini (1GB) | 24 | $4.86 |
| elasticsearch | shared-cpu-2x (2GB) | 24 | $9.72 |
| redis | Upstash free tier | - | $0 |
| **Total infra** | | | **~$17/mês** |

#### Custos Embeddings

| Opção | Custo/1M tokens | Custo/Mês |
|-------|-----------------|-----------|
| OpenAI text-embedding-3-small | $0.02 | ~$1.00 |
| OpenAI text-embedding-3-large | $0.13 | ~$6.50 |
| Local TEI (Fly) | $0 (CPU) | $0 |
| **Recomendado**: TEI local | - | **~$0** |

#### Custo Total Estimado (1K docs/dia)

| Modelo | Custo Mensal |
|--------|--------------|
| **Fly full self-hosted** | **~$17/mês** |
| Fly + OpenAI embeddings | ~$18-23/mês |
| Supabase Pro + Fly worker | ~$25-30/mês |
| Supabase Free (limitado) | ~$5/mês* |

*Limitado a 500MB DB

### 8.2 Cenário: 10.000 Documentos/Dia

#### Assumptions

| Parâmetro | Valor |
|-----------|-------|
| Documentos/dia | 10.000 |
| Tamanho médio/doc | 10KB |
| Chunks/doc (médio) | 5 |
| Embeddings gerados/dia | 50.000 |
| Total docs armazenados (ano) | ~3.65M |
| Storage anual (texto) | ~36GB |
| Storage embeddings | ~14GB |

#### Custos Fly.io (Otimizado)

| Componente | Config | Horas/Dia | Custo/Mês |
|------------|--------|-----------|-----------|
| gabi-api | shared-cpu-2x (512MB) | 24 | $3.88 |
| gabi-worker | shared-cpu-4x (2GB) | 4 | $1.94 |
| postgres | Fly mini (1GB) → dedicated-cpu-1x (2GB) | 24 | $29.16 |
| elasticsearch | dedicated-cpu-1x (4GB) | 24 | $58.32 |
| redis | Upstash paid | - | $10 |
| object storage (R2) | 50GB | - | $0 |
| **Total infra** | | | **~$103/mês** |

#### Otimizações para 10K docs

```yaml
# Otimizações aplicáveis
optimizations:
  # 1. Worker só roda quando necessário (escala com fila)
  worker_scaling:
    min_machines: 0
    max_machines: 3
    scale_trigger: queue_depth > 100
    
  # 2. Elasticsearch só para hot data (últimos 3 meses)
  elasticsearch:
    max_docs: 500000  # ~3 meses
    rollover: monthly
    
  # 3. Warm storage (PG sem ES) para dados antigos
  warm_storage:
    cutoff_days: 90
    search_via: pg_tsvector
    
  # 4. Compressão ativada
  compression:
    documents: zstd  # ~6x redução
    embeddings: fp16  # 50% redução
    
  # 5. Cache de embeddings (deduplicação)
  embedding_cache:
    hit_rate_expected: 0.40  # 40% economia
```

#### Custo Total Estimado (10K docs/dia)

| Modelo | Custo Mensal |
|--------|--------------|
| **Fly otimizado** | **~$60-80/mês** |
| Fly sem otimizações | ~$150/mês |
| Supabase Pro + Fly workers | ~$80-100/mês |
| AWS (EC2 + RDS + ES) | ~$200-300/mês |

### 8.3 Projeção de Crescimento

```
Documentos/Dia    Custo/Mês    Infra Recomendada
────────────────────────────────────────────────────────
1K                $15-20       Fly mini + TEI
5K                $40-50       Fly + cache otimizado
10K               $60-80       Dedicated CPU (PG/ES)
50K               $200-300     Multi-machine, sharding
100K              $400-600     Cluster ES, PG read replicas
```

---

## 9. Checklist de Implementação

### Fase 1: Quick Wins (Semana 1)
- [ ] Configurar auto-stop no fly.worker.toml
- [ ] Implementar ETag caching básico
- [ ] Ativar zstd compression nos documentos
- [ ] Ajustar schedules para não sobrepor

### Fase 2: Otimização de Dados (Semanas 2-3)
- [ ] Implementar delta processing para CSVs
- [ ] Criar tabela embedding_cache no PG
- [ ] Configurar tiered storage (hot/warm)
- [ ] Otimizar ES index template

### Fase 3: Arquitetura Avançada (Semanas 4-6)
- [ ] Implementar adaptive scaler
- [ ] Configurar cold storage (R2)
- [ ] Deploy TEI local (vs OpenAI)
- [ ] Migrar para Supabase se apropriado

### Fase 4: Monitoramento (Contínuo)
- [ ] Dashboard de custos Fly.io
- [ ] Alertas de gastos >$X/mês
- [ ] Métricas de cache hit rate
- [ ] Otimização contínua baseada em dados

---

## 10. Resumo de Economia

| Estratégia | Economia Estimada | Complexidade |
|------------|-------------------|--------------|
| Resource scheduling | 60-70% | Baixa |
| Incremental processing | 95-99% | Média |
| Tiered storage | 40-50% | Média |
| Embedding caching | 30-50% | Baixa |
| Compression | 50-80% | Baixa |
| Scale-to-zero | 90%+ (worker) | Baixa |
| Supabase híbrido | 20-30% | Média |

**Economia combinada estimada**: 70-85% em workloads típicos

---

## Referências

- [Fly.io Pricing](https://fly.io/docs/about/pricing/)
- [Supabase Pricing](https://supabase.com/pricing)
- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [TEI (Text Embeddings Inference)](https://github.com/huggingface/text-embeddings-inference)
- [Zstd Compression](https://facebook.github.io/zstd/)
