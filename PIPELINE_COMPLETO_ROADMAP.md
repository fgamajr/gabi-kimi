# Pipeline Completo: Zero Kelvin → Discovery → Fetch → Jobs → Hash → Crawler

## 🎯 Diagnóstico Atual

### Estado por Componente

| Componente | Status | Detalhes |
|------------|--------|----------|
| **DiscoveryEngine** | 🟡 Parcial | Implementado: `StaticUrl`, `UrlPattern`. **Faltando:** `WebCrawl`, `ApiPagination` |
| **Fetcher** | 🔴 Não Existe | Contrato `IContentFetcher` existe, sem implementação |
| **Job Queue** | 🟡 Parcial | Entidades e contratos existem. Workers básicos implementados. Faltam: jobs por documento, retry policy avançada |
| **Hasher** | 🟡 Contrato | `DocumentFingerprint` definido. Sem implementação real de hash/deduplicação |
| **Crawler** | 🔴 Não Existe | Necessário para PDFs e APIs da Câmara |

### Fontes no sources.yaml (13 total)

```
📊 Estruturadas (CSV - 8 fontes):
   ✅ tcu_acordaos          - url_pattern (anos 1992-current)
   ✅ tcu_normas            - static_url
   ✅ tcu_sumulas           - static_url
   ✅ tcu_jurisprudencia_selecionada - static_url
   ✅ tcu_resposta_consulta - static_url
   ✅ tcu_informativo_lc    - static_url
   ✅ tcu_boletim_jurisprudencia - static_url
   ✅ tcu_boletim_pessoal   - static_url

🕷️ Não Estruturadas (2 fontes):
   🔴 tcu_publicacoes       - web_crawl + PDF (PRECISA CRAWLER)
   🔴 tcu_notas_tecnicas_ti - web_crawl + PDF (PRECISA CRAWLER)

🌐 APIs (1 fonte):
   🔴 camara_leis_ordinarias - api_pagination (PRECISA ADAPTER API)

💤 Inativas (2 fontes):
   ⏸️ stf_decisoes          - desativado
   ⏸️ stj_acordaos          - desativado
```

---

## 📐 Arquitetura Proposta

### Estrutura de Pastas/Módulos

```
src/
├── Gabi.Discover/              # JÁ EXISTE - Expandir
│   ├── Strategies/
│   │   ├── StaticUrlStrategy.cs
│   │   ├── UrlPatternStrategy.cs
│   │   ├── WebCrawlStrategy.cs          🆕 NOVO
│   │   └── ApiPaginationStrategy.cs     🆕 NOVO
│   └── ChangeDetector.cs
│
├── Gabi.Fetch/                 🆕 NOVO MÓDULO
│   ├── ContentFetcher.cs
│   ├── DocumentCounter.cs
│   ├── MetadataExtractor.cs
│   └── Strategies/
│       ├── CsvFetchStrategy.cs
│       ├── PdfFetchStrategy.cs
│       └── ApiFetchStrategy.cs
│
├── Gabi.Crawler/               🆕 NOVO MÓDULO
│   ├── WebCrawler.cs
│   ├── PdfDownloader.cs
│   ├── LinkExtractor.cs
│   └── PolitenessPolicy.cs
│
├── Gabi.Jobs/                  🆕 NOVO MÓDULO (extrair de Gabi.Sync)
│   ├── JobFactory.cs
│   ├── SourceJobCreator.cs
│   ├── DocumentJobCreator.cs
│   └── JobStateMachine.cs
│
├── Gabi.Hash/                  🆕 NOVO MÓDULO
│   ├── ContentHasher.cs
│   ├── DeduplicationService.cs
│   └── FingerprintComparer.cs
│
├── Gabi.Pipeline/              🆕 NOVO MÓDULO (orquestração)
│   └── PipelineOrchestrator.cs (mover de Gabi.Sync)
│
└── Gabi.Api/Controllers/       🆕 NOVOS ENDPOINTS
    ├── JobsController.cs
    ├── DiscoveryController.cs
    └── CrawlerController.cs
```

---

## 🔄 Fluxo de Estados Detalhado

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         PIPELINE COMPLETO GABI                                   │
└─────────────────────────────────────────────────────────────────────────────────┘

sources.yaml
    │
    ▼
┌─────────────────┐
│  SOURCE REGISTRY │ ◄── Inicialização: carrega fontes do YAML
│   (PostgreSQL)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    DISCOVERY PHASE                           │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Static URL  │  │ URL Pattern  │  │   Web Crawler    │   │
│  │  (csv)      │  │  (anos)      │  │ (pdfs/páginas)   │   │
│  └──────┬──────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                │                    │             │
│  ┌──────┴────────────────┴────────────────────┴─────────┐  │
│  │              API Pagination Adapter                   │  │
│  │         (Câmara dos Deputados API)                    │  │
│  └────────────────────────┬──────────────────────────────┘  │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              DISCOVERED LINKS (PostgreSQL)                  │
│  • url                                                        │
│  • source_id                                                  │
│  • discovery_strategy                                         │
│  • content_type (csv/pdf/html/api)                           │
│  • discovered_at                                              │
│  • last_checked_at                                            │
│  • etag / last_modified (para change detection)              │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                     FETCHER PHASE                            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │           CONTENT FETCHER (por tipo)                │     │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │     │
│  │  │   CSV    │  │   PDF    │  │    API/JSON      │  │     │
│  │  │ (stream) │  │(download)│  │  (pagination)    │  │     │
│  │  └────┬─────┘  └────┬─────┘  └────────┬─────────┘  │     │
│  └───────┼─────────────┼────────────────┼────────────┘     │
│          │             │                │                   │
│          ▼             ▼                ▼                   │
│  ┌────────────────────────────────────────────────────┐     │
│  │              DOCUMENT COUNTER                       │     │
│  │  • Conta documentos disponíveis                     │     │
│  │  • Extrai metadados básicos (título, data, id)     │     │
│  │  • Retorna: contagem + snapshot                    │     │
│  └────────────────────────┬───────────────────────────┘     │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              RECONCILE PHASE (Snapshot + Diff)              │
│                                                              │
│  ┌────────────────────────────────────────────────────┐     │
│  │              RECONCILIATION SERVICE                 │     │
│  │                                                      │     │
│  │  • Snapshot: lista atual de documentos na fonte    │     │
│  │  • Diff: comparar com estado na base               │     │
│  │                                                      │     │
│  │  Ações:                                              │     │
│  │  • INSERT: documentos novos                         │     │
│  │  • UPDATE: hash mudou → reprocessar                 │     │
│  │  • SOFT DELETE: removed_from_source_at              │     │
│  │                                                      │     │
│  │  Métricas: added/updated/removed/unchanged          │     │
│  └────────────────────────┬───────────────────────────┘     │
└───────────────────────────┼──────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│                    JOB FACTORY                               │
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────────┐     │
│  │   JOB POR SOURCE    │    │    JOB POR DOCUMENTO    │     │
│  │                     │    │                         │     │
│  │ • source_id         │───►│ • source_id             │     │
│  │ • total_docs        │    │ • doc_url               │     │
│  │ • strategy          │    │ • doc_metadata          │     │
│  │ • status=pending    │    │ • hash_status=pending   │     │
│  │ • priority=normal   │    │ • priority=calculada    │     │
│  └─────────────────────┘    └─────────────────────────┘     │
│                                                              │
│  Regra: 1 job por source gera N jobs por documento          │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                INGEST JOBS (PostgreSQL)                     │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Job Types:                                          │    │
│  │  • discover  - Descobrir links                       │    │
│  │  • fetch     - Buscar conteúdo                      │    │
│  │  • hash      - Gerar fingerprint                    │    │
│  │  • parse     - Extrair conteúdo                     │    │
│  │  • transform - Validar/enriquecer                   │    │
│  │  • chunk     - Dividir em chunks                    │    │
│  │  • embed     - Gerar embeddings                     │    │
│  │  • index     - Indexar no ES                        │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                              │
│  Estados: pending → running → completed/failed → retry       │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              HASHER / DEDUPLICATION                          │
│                                                              │
│  Estratégia de Hash:                                         │
│  1. Normalizar conteúdo (remover whitespace extra)          │
│  2. SHA-256 do conteúdo normalizado                         │
│  3. Fallback: SHA-256(url + data + título)                  │
│                                                              │
│  Deduplicação:                                               │
│  • Verifica hash no banco antes de processar                │
│  • Se duplicata: marca como skipped + ref original          │
│                                                              │
│  Fingerprint:                                                │
│  { hash, algorithm, content_size, computed_at }             │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│              CRAWLER (quando necessário)                     │
│                                                              │
│  Casos de Uso:                                               │
│  • tcu_publicacoes       - Crawl + PDF download             │
│  • tcu_notas_tecnicas_ti - Crawl + PDF download             │
│  • camara_leis           - API pagination adapter           │
│                                                              │
│  Funcionalidades:                                            │
│  • Respeita robots.txt                                      │
│  • Rate limiting configurável                               │
│  • Retry com backoff exponencial                            │
│  • Extrai links recursivamente                              │
│  • Download de arquivos (PDF, DOCX)                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 📊 Modelo de Dados para Jobs

### IngestJobEntity (Expandido)

```csharp
public class IngestJobEntity
{
    // IDs
    public Guid Id { get; set; }
    public string? ParentJobId { get; set; }  // Para jobs filhos (doc jobs)
    
    // Tipo e Contexto
    public string JobType { get; set; }  // discover, fetch, hash, parse, transform, chunk, embed, index
    public string SourceId { get; set; }
    public long? LinkId { get; set; }
    public string? DocumentId { get; set; }  // Para jobs por documento
    
    // Payload
    public string Payload { get; set; }  // JSON
    public string PayloadHash { get; set; }  // Para idempotência
    
    // Progresso
    public string Status { get; set; }  // pending, running, completed, failed, skipped
    public int ProgressPercent { get; set; }
    public string? ProgressMessage { get; set; }
    
    // Retry
    public int Attempts { get; set; }
    public int MaxAttempts { get; set; }
    public DateTime? RetryAt { get; set; }
    
    // Execução
    public string? WorkerId { get; set; }
    public DateTime? LockedAt { get; set; }
    public DateTime? LockExpiresAt { get; set; }
    
    // Resultado
    public int? LinksDiscovered { get; set; }
    public int? DocumentsProcessed { get; set; }
    public string? Result { get; set; }  // JSON
    public string? LastError { get; set; }
    public string? ErrorDetails { get; set; }
    
    // Hash/Fingerprint
    public string? ContentHash { get; set; }
    public bool? IsDuplicate { get; set; }
    public string? OriginalDocumentId { get; set; }
    
    // Timestamps
    public DateTime ScheduledAt { get; set; }
    public DateTime? StartedAt { get; set; }
    public DateTime? CompletedAt { get; set; }
    
    // Auditoria
    public DateTime CreatedAt { get; set; }
    public DateTime ModifiedAt { get; set; }
}
```

### DocumentEntity (Expandido)

```csharp
public class DocumentEntity
{
    public Guid Id { get; set; }
    public string DocumentId { get; set; }  // ID externo (ex: acordao-1234/2024)
    public string SourceId { get; set; }
    
    // Conteúdo
    public string Title { get; set; }
    public string Content { get; set; }
    public string? ContentNormalized { get; set; }  // Para hash
    
    // Fingerprint
    public string ContentHash { get; set; }
    public string HashAlgorithm { get; set; }  // sha256
    public long ContentSize { get; set; }
    
    // Metadados
    public string Metadata { get; set; }  // JSON
    public DateTime? DocumentDate { get; set; }
    public string? ExternalUrl { get; set; }
    
    // Status
    public string Status { get; set; }  // discovered, fetched, hashed, parsed, chunked, indexed
    public bool IsDuplicate { get; set; }
    public string? OriginalDocumentId { get; set; }
    
    // Soft delete (nunca apagar fisicamente)
    public DateTime? RemovedFromSourceAt { get; set; }
    public string? RemovedReason { get; set; } // "source_deleted", "manual", etc.
    
    // Natural Key (identificador estável)
    public string ExternalId { get; set; } // ID da fonte (número do acórdão, etc.)
    // Índice único: (SourceId, ExternalId)
    
    // Timestamps
    public DateTime DiscoveredAt { get; set; }
    public DateTime? FetchedAt { get; set; }
    public DateTime? HashedAt { get; set; }
    public DateTime? ParsedAt { get; set; }
    public DateTime? IndexedAt { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime ModifiedAt { get; set; }
}
```

---

## 🔄 Padrão Snapshot + Diff + Reconcile

**Snapshot**: Para cada source, obter lista atual de itens (identificadores estáveis).
- CSV: coluna ID ou combinação (número + ano)
- API: ID retornado
- PDF/HTML: URL canônica

**Diff**: Comparar snapshot com estado na base para aquela source_id.

**Reconcile**:
| Situação | Ação |
|----------|------|
| Na fonte e não na base | INSERT (criar doc + jobs) |
| Na fonte e na base | UPDATE (se hash mudou) / skip (idempotente) |
| Na base e não na fonte | SOFT DELETE (set removed_from_source_at) |

### Fluxo de Estados com Reconcile

```
Discovery → Snapshot (lista de IDs/URLs)
                ↓
         Fetch (conteúdo completo)
                ↓
         Reconcile (Diff)
                ↓
         ┌──────┴──────┐
         ▼             ▼
      INSERT       UPDATE/DELETE
         │             │
         ▼             ▼
   JobFactory    JobFactory (update)
         │
         ▼
   Workers (hash/parse/chunk)
```

### Observabilidade

Por run de sync:
- `source_id`, `started_at`, `finished_at`
- `status` (success/partial/failed)
- Métricas: `documents_added`, `documents_updated`, `documents_removed`, `documents_unchanged`
- `errors_count`, `last_snapshot_hash`

---

## 🕷️ Estratégia de Crawler Extensível

### Interface Base

```csharp
public interface ICrawlerStrategy
{
    string StrategyName { get; }
    Task<CrawlResult> CrawlAsync(CrawlRequest request, CancellationToken ct);
}

public class CrawlRequest
{
    public string SourceId { get; set; }
    public string RootUrl { get; set; }
    public CrawlConfig Config { get; set; }
    public int MaxDepth { get; set; }
    public int MaxPages { get; set; }
}

public class CrawlResult
{
    public List<DiscoveredAsset> Assets { get; set; }  // PDFs, arquivos
    public List<DiscoveredLink> Links { get; set; }    // Páginas para continuar
    public List<string> Errors { get; set; }
    public int PagesCrawled { get; set; }
}
```

### Implementações

| Strategy | Para | Descrição |
|----------|------|-----------|
| `TcuPublicationsCrawler` | tcu_publicacoes | Crawl portal TCU + download PDFs |
| `TcuTechnicalNotesCrawler` | tcu_notas_tecnicas_ti | Crawl SEFTI + download PDFs |
| `CamaraApiAdapter` | camara_leis_ordinarias | Adapter para API REST da Câmara |
| `GenericWebCrawler` | Futuras fontes | Crawler genérico configurável |

### Configuração no sources.yaml

```yaml
discovery:
  strategy: web_crawl
  config:
    root_url: "https://portal.tcu.gov.br/publicacoes-institucionais/todas"
    rules:
      max_depth: 2
      max_pages: 100
      rate_limit: 1.0  # requests por segundo
      
      # Seletores CSS
      link_selector: "a[href*='/publicacoes-institucionais/']"
      asset_selector: "a[href$='.pdf']"
      
      # Filtros
      include_patterns: ["*.pdf", "*/download/*"]
      exclude_patterns: ["*/login/*", "*/admin/*"]
      
      # Headers
      user_agent: "GABI-Bot/1.0 (TCU Data Collection)"
      
    # Autenticação (se necessária)
    auth:
      type: none  # ou basic, bearer, api_key
```

---

## 🔐 Estratégia de Hashing e Deduplicação

### Algoritmo

```csharp
public class ContentHasher : IContentHasher
{
    public DocumentFingerprint ComputeFingerprint(string content, string? url = null, 
        string? title = null, DateTime? date = null)
    {
        // 1. Normalizar conteúdo
        var normalized = NormalizeContent(content);
        
        // 2. Tentar hash do conteúdo
        string hash;
        if (!string.IsNullOrWhiteSpace(normalized) && normalized.Length > 50)
        {
            hash = ComputeSha256(normalized);
        }
        else
        {
            // Fallback: hash de metadados
            var fallback = $"{url}|{title}|{date:yyyy-MM-dd}";
            hash = ComputeSha256(fallback);
        }
        
        return new DocumentFingerprint
        {
            Hash = hash,
            Algorithm = HashAlgorithm.Sha256,
            ContentSize = content?.Length ?? 0,
            ComputedAt = DateTime.UtcNow
        };
    }
    
    private string NormalizeContent(string content)
    {
        return content
            ?.Replace("\r\n", "\n")
            ?.Replace("\r", "\n")
            ?.Replace("\t", " ")
            ?.Trim()
            ?? string.Empty;
    }
}
```

### DeduplicationService

```csharp
public class DeduplicationService : IDeduplicationService
{
    private readonly IDocumentRepository _docRepo;
    
    public async Task<DuplicateCheckResult> CheckDuplicateAsync(
        DocumentFingerprint fingerprint, 
        string sourceId,
        CancellationToken ct)
    {
        // Buscar documento com mesmo hash na mesma fonte
        var existing = await _docRepo.GetByHashAsync(fingerprint.Hash, sourceId, ct);
        
        if (existing != null)
        {
            return new DuplicateCheckResult
            {
                IsDuplicate = true,
                ExistingDocumentId = existing.DocumentId,
                Fingerprint = fingerprint
            };
        }
        
        return new DuplicateCheckResult
        {
            IsDuplicate = false,
            Fingerprint = fingerprint
        };
    }
}
```

---

## 📋 Checklist de Implementação

### Fase 1: Foundation (Sprint 1)
- [ ] Criar projeto `Gabi.Fetch`
- [ ] Implementar `ContentFetcher` básico
- [ ] Implementar `DocumentCounter`
- [ ] Criar tabela `documents` expandida
- [ ] Migration para novos campos

### Fase 2: Jobs (Sprint 2)
- [ ] Refatorar `Gabi.Jobs` como módulo separado
- [ ] Implementar `JobFactory`
- [ ] Criar `SourceJobCreator`
- [ ] Criar `DocumentJobCreator`
- [ ] Implementar `JobStateMachine`
- [ ] Criar workers especializados por tipo

### Fase 3: Hashing (Sprint 3)
- [ ] Criar projeto `Gabi.Hash`
- [ ] Implementar `ContentHasher`
- [ ] Implementar `DeduplicationService`
- [ ] Integrar ao pipeline

### Fase 4: Crawler (Sprint 4)
- [ ] Criar projeto `Gabi.Crawler`
- [ ] Implementar `WebCrawler` base
- [ ] Implementar `PdfDownloader`
- [ ] Implementar `TcuPublicationsCrawler`
- [ ] Implementar `CamaraApiAdapter`
- [ ] Expandir `DiscoveryEngine` com novas strategies

### Fase 5: Integração (Sprint 5)
- [ ] Criar `PipelineOrchestrator`
- [ ] Implementar fluxo end-to-end
- [ ] API endpoints para monitoramento
- [ ] Testes Zero Kelvin completos
- [ ] Documentação

---

## 🚀 Execução Zero Kelvin (Alvo)

```bash
# 1. Destruir tudo
docker compose down -v
rm -rf /tmp/gabi-*

# 2. Setup
./scripts/setup.sh

# 3. Iniciar
./scripts/dev app start

# 4. Executar pipeline completo
curl -X POST http://localhost:5100/api/v1/pipeline/run \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"source": "tcu_acordaos", "phases": ["discover", "fetch", "hash", "parse"]}'

# 5. Verificar progresso
curl http://localhost:5100/api/v1/jobs/status \
  -H "Authorization: Bearer $TOKEN"

# Resultado esperado:
# - Links descobertos: ~30 (1 por ano de 1992-2024)
# - Documentos contados: ~500.000 (acórdãos totais)
# - Jobs criados: ~500.000 (1 por documento)
# - Hashes gerados: ~500.000
# - Duplicatas: 0 (primeira execução)
```

---

## 📈 Métricas de Sucesso

| Métrica | Alvo |
|---------|------|
| Fontes configuradas | 13 (11 ativas) |
| Fontes funcionando end-to-end | 11 |
| Throughput (docs/seg) | > 100 |
| Tempo Zero Kelvin → Indexed | < 24h (full load) |
| Taxa de duplicatas | < 0.1% |
| Retry sucesso | > 95% |
