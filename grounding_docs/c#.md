# C# Feasibility Assessment: GABI-SYNC Architecture

## TL;DR

The architecture in `claude_plan.md` is **language-agnostic** - the 5-layer dependency graph, Docker profiles, and separation of concerns all translate 1:1. In fact, **C# is a BETTER fit** for this specific architecture because .NET natively supports exactly the "separate apps in a solution" model the user envisions (coming from C# background). The question is cost: **~3-4 weeks** to port vs. **~1 week** to restructure in Python.

---

## Component-by-Component Mapping

### Layer 0: Types + Exceptions
| Python | C# | Mapping |
|---|---|---|
| `types.py` (enums) | `Gabi.Contracts/Enums/` | **1:1** - C# enums are stronger typed |
| `exceptions.py` | `Gabi.Contracts/Exceptions/` | **1:1** - C# exception hierarchy is native |

**C# advantage:** `record` types, strong enums with `[Flags]`, pattern matching.

### Layer 1: GABI-CONTRACTS
| Python | C# | Mapping |
|---|---|---|
| `@dataclass` contracts | `record` types | **Better in C#** - immutable records with `with` expressions |
| `AsyncIterator[str]` | `IAsyncEnumerable<string>` | **1:1** - native C# 8.0+ |
| `StreamingFetchedContent` | `record` with `IAsyncEnumerable` | **1:1** |
| Pydantic validation | FluentValidation or DataAnnotations | **Slightly more work** but more powerful |

**C# project:** `Gabi.Contracts.csproj` - class library, zero dependencies.

### Layer 2: GABI-INFRA
| Python | C# | Mapping |
|---|---|---|
| Pydantic Settings (`config.py`) | `IOptions<T>` + `appsettings.json` | **Better in C#** - native DI, env override built-in |
| SQLAlchemy async + asyncpg (`db.py`) | EF Core + Npgsql | **1:1** - EF Core async is mature |
| Celery (`celery_app.py`) | **See analysis below** | **Needs rethinking** |
| structlog (`logging.py`) | Serilog or `ILogger<T>` | **Better in C#** - structured logging is first-class |

**Celery replacement options (ranked):**
1. **`BackgroundService` + `System.Threading.Channels`** (Recommended) - No external broker needed for single-worker. Uses Redis for distributed if needed later.
2. **Hangfire** - Persistent job queue with dashboard. Uses Redis/SQL as backend. Closest to Celery semantics.
3. **MassTransit + RabbitMQ** - Full message bus. Overkill for current needs but scales to microservices.

**Recommendation:** Start with `BackgroundService` + `Channel<SyncJob>`. The current usage of Celery is essentially "run this pipeline async" - that's exactly what `BackgroundService` does. Add Hangfire later if you need persistent retries/scheduling.

**C# project:** `Gabi.Infrastructure.csproj` - depends on `Gabi.Contracts`.

### Layer 3: ORM Models
| Python | C# | Mapping |
|---|---|---|
| SQLAlchemy ORM models | EF Core entities | **1:1** - `DbContext`, `DbSet<T>`, fluent config |
| alembic migrations | EF Core Migrations | **1:1** - `dotnet ef migrations add`, `database update` |
| pgvector extension | `Pgvector.EntityFrameworkCore` NuGet | **1:1** - well-supported |

**C# project:** `Gabi.Data.csproj` - depends on `Gabi.Contracts`, `Gabi.Infrastructure`.

### Layer 4a: GABI-DISCOVER
| Python | C# | Mapping |
|---|---|---|
| `DiscoveryEngine` | Same class design | **1:1** |
| URL pattern generation | String interpolation | **1:1** |
| `ChangeDetector` (ETag) | `HttpClient` conditional requests | **Better in C#** - `HttpClient` has native ETag support |

**C# project:** `Gabi.Discover.csproj` - depends on `Gabi.Contracts`, `Gabi.Infrastructure`.

### Layer 4b: GABI-INGEST
| Python | C# | Mapping |
|---|---|---|
| **Fetcher:** httpx/aiohttp streaming | `HttpClient` + `Stream` | **1:1** - `HttpCompletionOption.ResponseHeadersRead` |
| **Streaming queue:** `asyncio.Queue` | `System.Threading.Channels` | **Better in C#** - Channels are purpose-built for this |
| **UTF-8 incremental:** `codecs.IncrementalDecoder` | `Encoding.GetDecoder()` | **1:1** - exact same pattern |
| **CSV streaming:** `csv.DictReader` line-by-line | `CsvHelper` with `IAsyncEnumerable` | **Better in C#** - CsvHelper is superb |
| **HTML parsing:** BeautifulSoup | AngleSharp | **Better in C#** - AngleSharp follows DOM spec |
| **PDF parsing:** pdfplumber | PdfPig (OSS) or iText7 | **Comparable** - PdfPig is lighter |
| **JSON parsing:** `json.loads` | `System.Text.Json` | **Better in C#** - zero-alloc `Utf8JsonReader` |
| **SSRF protection:** manual IP validation | Same logic, `IPAddress.TryParse` | **1:1** |
| **Fingerprint:** `hashlib.sha256` | `SHA256.HashData()` | **1:1** |
| **Chunking:** custom text splitter | Same logic | **1:1** |

**C# projects:**
- `Gabi.Ingest.csproj` - depends on `Gabi.Contracts`, `Gabi.Data`
- Optionally split fetcher/parser into separate projects

### Layer 5: GABI-SYNC
| Python | C# | Mapping |
|---|---|---|
| `_run_sync_pipeline()` | `PipelineRunner.RunAsync()` | **1:1** |
| Celery `sync_source_task` | `BackgroundService` + `Channel<SyncJob>` | **Adaptation needed** |
| Memory monitoring via `psutil` | `Process.GetCurrentProcess().WorkingSet64` | **1:1** |
| `PipelineComponents` DI | Native `IServiceProvider` DI | **Better in C#** - DI is first-class |
| Cancellation via Redis flag | `CancellationToken` propagation | **Much better in C#** - native pattern |

**C# project:** `Gabi.Sync.csproj` - depends on ALL above.

---

## The Streaming Architecture (Critical Feature)

The 587MB CSV streaming with ~200MB constant memory translates **perfectly** to C#:

```
Python                              C#
─────────────────────────────       ─────────────────────────────
asyncio.Queue(maxsize=1000)    →    Channel<byte[]>.CreateBounded(1000)
async for chunk in queue:      →    await foreach (var chunk in reader.ReadAllAsync(ct))
codecs.IncrementalDecoder      →    Encoding.UTF8.GetDecoder()
yield StreamingParseChunk      →    yield return new StreamingParseChunk(...)
async def parse_streaming()    →    async IAsyncEnumerable<StreamingParseChunk>
```

C# `Channels` are actually **more efficient** than Python's `asyncio.Queue` - they're lock-free, support bounded/unbounded, and integrate with `CancellationToken`.

---

## New C# Solution Structure

```
GabiSync.sln
├── src/
│   ├── Gabi.Contracts/              # Layer 0-1: Records, enums, exceptions, interfaces
│   │   ├── Discovery/
│   │   │   └── DiscoveredUrl.cs, DiscoveryResult.cs
│   │   ├── Fetch/
│   │   │   └── FetchedContent.cs, StreamingFetchedContent.cs
│   │   ├── Parse/
│   │   │   └── ParsedDocument.cs, ParseResult.cs, StreamingParseChunk.cs
│   │   ├── Fingerprint/
│   │   ├── Chunk/
│   │   ├── Embed/
│   │   ├── Index/
│   │   ├── Enums/
│   │   └── Exceptions/
│   │
│   ├── Gabi.Infrastructure/         # Layer 2: Config, DB, logging, messaging
│   │   ├── Configuration/
│   │   │   └── GabiSettings.cs
│   │   ├── Persistence/
│   │   │   └── GabiDbContext.cs, Migrations/
│   │   ├── Messaging/
│   │   │   └── IJobQueue.cs, ChannelJobQueue.cs
│   │   └── Extensions/
│   │       └── ServiceCollectionExtensions.cs
│   │
│   ├── Gabi.Discover/               # Layer 4a: URL discovery
│   │   ├── DiscoveryEngine.cs
│   │   ├── ChangeDetector.cs
│   │   └── IDiscoveryService.cs
│   │
│   ├── Gabi.Ingest/                 # Layer 4b: Fetch + Parse + Process
│   │   ├── Fetcher/
│   │   │   ├── IContentFetcher.cs
│   │   │   ├── HttpContentFetcher.cs
│   │   │   ├── StreamingFetcher.cs
│   │   │   └── SsrfValidator.cs
│   │   ├── Parser/
│   │   │   ├── IDocumentParser.cs
│   │   │   ├── CsvParser.cs         # + streaming via IAsyncEnumerable
│   │   │   ├── HtmlParser.cs
│   │   │   ├── PdfParser.cs
│   │   │   ├── JsonParser.cs
│   │   │   └── ParserRegistry.cs
│   │   ├── Fingerprinter.cs
│   │   ├── Deduplicator.cs
│   │   └── Chunker.cs
│   │
│   ├── Gabi.Sync/                   # Layer 5: Orchestration
│   │   ├── PipelineRunner.cs
│   │   ├── SyncBackgroundService.cs  # IHostedService
│   │   ├── MemoryMonitor.cs
│   │   └── ErrorClassifier.cs
│   │
│   └── Gabi.Worker/                 # Console app entry point
│       ├── Program.cs               # Host builder + DI registration
│       ├── appsettings.json
│       └── Gabi.Worker.csproj
│
├── tests/
│   ├── Gabi.Contracts.Tests/
│   ├── Gabi.Discover.Tests/
│   ├── Gabi.Ingest.Tests/
│   └── Gabi.Sync.Tests/
│
├── docker/
│   └── Dockerfile                   # Multi-stage .NET 8 build
├── docker-compose.yml               # Same profiles: core, embed, index, full
└── sources.yaml
```

---

## Trade-off Analysis

### Option A: Rewrite in C# (Recommended if you have time)

| Pros | Cons |
|---|---|
| Native to your background (C# developer) | 3-4 weeks to port ~6000 lines of core logic |
| Better tooling for this architecture (Solution/Projects = Apps) | Need to learn EF Core + Npgsql if unfamiliar |
| `IAsyncEnumerable`, `Channels`, `CancellationToken` are superior | Python ML/NLP ecosystem is richer (spaCy, etc.) |
| Strong typing catches bugs at compile time | Deployment: .NET containers are larger (~200MB vs ~50MB) |
| Native DI container, no Celery complexity | Less community tooling for legal/NLP document processing |
| `record` types are perfect for contracts | TEI integration needs custom HTTP client (same in both) |
| Single binary deployment (publish -c Release) | |

### Option B: Keep Python, just restructure

| Pros | Cons |
|---|---|
| 1 week to restructure (code exists, just reorganize) | Still fighting Python's weak typing and module system |
| Battle-tested streaming code (verified at 226MB memory) | Celery complexity remains |
| Rich NLP ecosystem (spaCy, pdfplumber, etc.) | The "apps as packages" pattern is awkward in Python |
| Existing tests pass | Your strongest language isn't Python |

### Option C: Hybrid (NOT recommended)

| Pros | Cons |
|---|---|
| Best of both worlds in theory | Two languages = double the maintenance |
| | Serialization overhead between services |
| | Much harder to debug end-to-end |

---

## Recommendation

**Go with C# (Option A)** if:
- This is a long-term project you want to maintain for years
- You're faster and more confident in C# than Python
- You value compile-time safety and IDE tooling (Rider/VS)
- You plan to add more team members (C# devs are easier to find in Brazil for enterprise)

**Keep Python (Option B)** if:
- You need this working within 1 week
- The ML/NLP features (embeddings, semantic search) are the primary value
- You want to keep iterating quickly on the pipeline logic

The architecture plan in `claude_plan.md` works **identically** in both languages. The 5-layer dependency graph, Docker profiles, and separation of concerns are language-agnostic.