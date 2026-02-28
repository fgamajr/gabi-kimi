# Sprint 3: Real Fetch Implementation - Design Document

**Date**: 2026-02-15
**Status**: Approved
**Sprint**: 3 of 6

---

## 1. Overview

Replace the `FetchJobExecutor` stub with a real implementation that:
- Downloads CSV files via HTTP streaming
- Parses CSV row-by-row (never loads full file in memory)
- Applies field mapping and transforms from `sources_v2.yaml`
- Supports ETag/Last-Modified for change detection
- Stores documents in PostgreSQL

**Memory constraint**: 300MB ceiling (stateless, diskless server)

---

## 2. Architecture

```
HTTP Response (streaming)
       ↓
CsvStreamingReader (row-by-row, ~1 row in memory)
       ↓
MappingEngine (apply field mapping + transforms)
       ↓
DocumentEntity (parsed row)
       ↓
PostgreSQL (documents table)
```

---

## 3. Components

### 3.1 HttpStreamingClient

```csharp
public interface IHttpStreamingClient
{
    Task<StreamResponse> FetchAsync(
        string url,
        string? etag = null,
        string? lastModified = null,
        CancellationToken ct = default);
}

public record StreamResponse(
    Stream ContentStream,
    string? ETag,
    string? LastModified,
    long? ContentLength,
    bool NotModified,
    int StatusCode
);
```

**Key behaviors:**
- `HttpCompletionOption.ResponseHeadersRead` - stream headers only
- Send `If-None-Match` / `If-Modified-Since` for conditional requests
- Return `NotModified = true` on HTTP 304

### 3.2 CsvStreamingParser

```csharp
public interface ICsvStreamingParser
{
    IAsyncEnumerable<CsvRow> ParseRowsAsync(
        Stream contentStream,
        CsvParseConfig config,
        CancellationToken ct = default);
}

public record CsvRow(
    int RowNumber,
    Dictionary<string, string> Fields,
    List<string> Warnings
);

public record CsvParseConfig(
    char Delimiter = '|',
    char QuoteChar = '"',
    bool HasHeader = true,
    string Encoding = "utf-8"
);
```

### 3.3 MappingEngine

```csharp
public interface IMappingEngine
{
    MappedDocument Map(
        Dictionary<string, string> csvFields,
        SourceMappingConfig mapping,
        string sourceId,
        string url);
}

public record MappedDocument(
    string DocumentId,
    string? Title,
    string? Content,
    string? ContentPreview,
    Dictionary<string, object> Metadata,
    Dictionary<string, string> TextFields
);
```

### 3.4 Transforms

```csharp
public static class Transforms
{
    public static string StripQuotes(string value);
    public static string StripHtml(string value);
    public static string NormalizeWhitespace(string value);
    public static string ToInteger(string value);
    public static string ToDate(string value);
}
```

---

## 4. Fail-Safe Strategy

| Failure Scenario | Behavior |
|------------------|----------|
| HTTP 304 Not Modified | Skip, mark `fetch_items.status = 'skipped_unchanged'` |
| HTTP 404/410 | Mark `status = 'not_found'`, log warning, continue |
| HTTP 403/401 | Mark `status = 'forbidden'`, log error, fail job |
| HTTP 5xx | Throw → Hangfire retries → DLQ |
| Connection timeout | Throw → Hangfire retries |
| Malformed CSV row | Log warning, skip row, continue |
| Missing required field | Log warning, skip row, continue |

---

## 5. File Structure

```
src/Gabi.Fetch/
├── HttpStreamingClient.cs
├── CsvStreamingParser.cs
├── MappingEngine.cs
├── Transforms.cs
├── FetchResult.cs
└── Gabi.Fetch.csproj

src/Gabi.Worker/Jobs/
└── FetchJobExecutor.cs (rewrite)
```

---

## 6. Verification Criteria

- [ ] HTTP 304 skips processing
- [ ] CSV row-by-row never exceeds 300MB memory
- [ ] Documents inserted with real content
- [ ] ETag/Last-Modified stored for next run
- [ ] `tcu_sumulas` (1MB) processes successfully
- [ ] `tcu_normas` (500MB) processes without OOM

---

## 7. Implementation Order

1. Create `Gabi.Fetch` project with `HttpStreamingClient`
2. Implement `CsvStreamingParser`
3. Implement `Transforms` + `MappingEngine`
4. Rewrite `FetchJobExecutor`
5. Register services in `Program.cs`
6. Test with small file (`tcu_sumulas`)
7. Test with large file (`tcu_normas`)
