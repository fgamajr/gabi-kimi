# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adere ao [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [0.1.0] - 2025-01-15

### Adicionado

#### Contratos (Gabi.Contracts)
- Camada 0-1 de contratos com zero dependências externas
- 21 arquivos de contratos organizados por domínio:
  - **Chunk/**: Chunk, ChunkType, ChunkingResult, IChunker
  - **Discovery/**: DiscoveredSource, DiscoveryConfig, DiscoveryResult, ChangeDetectionVerdict, ChangeDetectionBatch, IDiscoveryEngine
  - **Embed/**: EmbeddedChunk, EmbeddingResult, EmbeddingConfig, IEmbedder
  - **Enums/**: DocumentStatus, SourceType, SourceStatus, ExecutionStatus, DlqStatus, SensitivityLevel, SearchType, SyncResult
  - **Fetch/**: FetchedContent, StreamingFetchedContent, FetchConfig, IContentFetcher
  - **Fingerprint/**: DocumentFingerprint, DuplicateCheckResult, IFingerprinter, HashAlgorithm
  - **Index/**: IndexingResult, IndexDocument, IndexChunk, IndexingStatus, IDocumentIndexer
  - **Parse/**: ParsedDocument, ParseConfig, ParseResult, ParseBatch, ParseError, IDocumentParser
  - **Sync/**: ISyncEngine, SyncContext, SyncStats
  - **Transform/**: AvailableTransforms

#### Documentação de Arquitetura
- `docs/architecture/INVARIANTS.md` - Invariantes do sistema (Leis Físicas)
- `docs/architecture/DATA_LIFECYCLE.md` - Ciclo de vida dos dados
- `docs/architecture/OBSERVABILITY.md` - Métricas, logs e tracing
- `docs/architecture/MCP_INTEGRATION.md` - Especificação MCP
- `docs/architecture/LAYERED_ARCHITECTURE.md` - Arquitetura em camadas

#### Estrutura de Solução
- Solution `GabiSync.sln` com 6 projetos:
  - `Gabi.Contracts` (Layer 0-1)
  - `Gabi.Postgres` (Layer 2-3) → Gabi.Contracts
  - `Gabi.Discover` (Layer 4) → Gabi.Contracts
  - `Gabi.Ingest` (Layer 4) → Gabi.Contracts, Gabi.Postgres
  - `Gabi.Sync` (Layer 5) → Gabi.Contracts, Gabi.Postgres
  - `Gabi.Worker` (Host) → Todos

#### Conceitos Incorporados do Projeto Anterior
- Contratos de pipeline do `.antigravity/00_CONTRACTS.md`
- Arquitetura em 3 camadas (Control, Data, Serving)
- Invariantes: idempotência, soft delete, fingerprint SHA-256
- Change detection com ETag/Last-Modified/Content-Hash
- Separação PostgreSQL (canônico) vs Elasticsearch (derivado)
- Observabilidade: métricas Prometheus, logs JSON, lineage
- Especificação MCP: tools search, get_document, list_sources, get_source_stats

### Características

- **Dimensionalidade fixa**: 384 (MiniLM-L12-v2)
- **Fingerprint**: SHA-256 hexadecimal (64 chars)
- **Soft Delete**: Documentos nunca são fisicamente removidos
- **Idempotência**: Mesma entrada → mesma saída
- **Streaming**: Suporte nativo via `IAsyncEnumerable<T>`

### Decisões de Design

| Decisão | Motivo |
|---------|--------|
| PostgreSQL + pgvector | ACID, joins, vector search nativo |
| C# / .NET 8 | Native DI, IAsyncEnumerable, Channels |
| 6 projetos modulares | Isolamento, testabilidade, deploy independente |
| Records imutáveis | Thread-safety, previsibilidade |
| Zero deps em Contracts | Garantia de estabilidade de contratos |

### Próximos Passos (MCP 002)

- [ ] Implementar Gabi.Discover (DiscoveryEngine com change detection)
- [ ] Implementar Gabi.Ingest (Pipeline de ingestão)
- [ ] Implementar Gabi.Postgres (EF Core models e DbContext)
- [ ] Implementar Gabi.Sync (SyncEngine com retry e DLQ)
- [ ] Implementar Gabi.Worker (Background jobs com Hangfire)
