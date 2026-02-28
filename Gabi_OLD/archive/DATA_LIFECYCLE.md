# Ciclo de Vida dos Dados

Este documento descreve o fluxo completo de um documento através do sistema GabiSync.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Discovery  │────▶│    Fetch    │────▶│    Parse    │────▶│  Normalize  │
│  (URLs)     │     │ (Download)  │     │ (Extrair)   │     │ (Transforms)│
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                                   │
                                                                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│Chunk + Embed│◀────│    Index    │◀────│ Deduplicate │◀────│Fingerprint  │
│ (Vetores)   │     │  (Search)   │     │  (SHA-256)  │     │  (Canônico) │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

---

## 1. Discovery

**Responsabilidade:** Produzir URLs a serem processados.

**Entrada:** `SourceConfig` (do sources.yaml)

**Saída:** `List<DiscoveredSource>`

```csharp
public interface IDiscoveryEngine
{
    IAsyncEnumerable<DiscoveredSource> DiscoverAsync(
        SourceConfig config, 
        CancellationToken ct = default);
}
```

**Regras:**
- Não baixa conteúdo
- Apenas enumera URLs
- Respeita politeness (rate limiting)

---

## 2. Fetch

**Responsabilidade:** Baixar conteúdo se houver mudança.

**Entrada:** `DiscoveredSource`

**Saída:** `FetchedContent` ou `null` (se não mudou)

**Fluxo:**
1. Consultar `change_detection_cache`
2. Fazer HEAD request → obter ETag/Last-Modified
3. Se igual ao cache → `return null` (skip)
4. Se diferente → download completo
5. Calcular `ContentHash` (SHA-256)
6. Atualizar cache

```csharp
if (cached?.Etag == response.Etag)
{
    _metrics.FetchSkipped.Inc();
    return null; // Nada mudou
}
```

---

## 3. Parse

**Responsabilidade:** Converter bytes → texto estruturado.

**Entrada:** `FetchedContent` (bytes)

**Saída:** `ParsedDocument`

**Formatos Suportados:**
- CSV (delimitado por `|`)
- PDF (com extração de texto)
- HTML (com normalização)

**Campos Extraídos:**
- `document_id` (via mapping)
- `title`
- `content`
- `metadata` (year, number, type, etc.)
- `text_fields` (text_relatorio, text_voto, etc.)

---

## 4. Normalize

**Responsabilidade:** Aplicar transforms declarativos.

**Transforms Disponíveis:**
```csharp
"strip_quotes"          // "texto" → texto
"strip_quotes_and_html" // "<p>texto</p>" → texto
"strip_html"            // <p>texto</p> → texto
"to_integer"            // "123" → 123
"to_float"              // "123.45" → 123.45
"to_date"               // "01/01/2024" → DateTime
"normalize_whitespace"  // "a   b" → "a b"
"uppercase"             // texto → TEXTO
"lowercase"             // TEXTO → texto
"url_to_slug"           // /path/to/file → file
"parse_boolean"         // "Sim"/"Não" → true/false
```

**Saída:** Conteúdo canônico pronto para fingerprint.

---

## 5. Fingerprint

**Responsabilidade:** Gerar hash determinístico.

**Entrada:** `ParsedDocument`

**Saída:** `DocumentFingerprint`

```csharp
var normalized = Normalize(document.Content);
var fingerprint = ComputeFingerprint(normalized);
// SHA-256 hex, 64 caracteres
```

---

## 6. Deduplicate

**Responsabilidade:** Detectar duplicatas cross-source.

**Entrada:** `DocumentFingerprint`

**Fluxo:**
1. Buscar no PostgreSQL por `fingerprint`
2. Se não existe → novo documento
3. Se existe e conteúdo igual → skip
4. Se existe e conteúdo diferente → nova versão

```csharp
var existing = await _db.Documents
    .FirstOrDefaultAsync(d => d.Fingerprint == fingerprint);

if (existing == null)
    return DeduplicationAction.Insert;
else if (existing.ContentHash != newHash)
    return DeduplicationAction.UpdateVersion;
else
    return DeduplicationAction.Skip;
```

---

## 7. Index

**Responsabilidade:** Atualizar índices de busca.

**Entrada:** `ParsedDocument` + chunks

**Ações:**
- Inserir/atualizar no PostgreSQL (canônico)
- Inserir/atualizar no Elasticsearch (derivado)
- Marcar `es_indexed = true`

**Ordem Importante:**
1. Commit PostgreSQL primeiro
2. Se sucesso → indexar no ES
3. Se ES falhar → documento fica `es_indexed = false` (para retry)

---

## 8. Chunk + Embed

**Responsabilidade:** Gerar vetores para busca semântica.

**Entrada:** `ParsedDocument.Content`

**Saída:** `List<EmbeddedChunk>`

**Estratégias:**
- `legal_hierarchical` (padrão) - preserva estrutura de artigos
- `whole_document` - documento inteiro como um chunk
- `semantic_section` - por seções semânticas

**Regras:**
- Embeddings são **descartáveis** (podem ser regenerados)
- Chunking deve ser **determinístico** (mesmo texto → mesmos chunks)
- Dimensão fixa: **384** (MiniLM-L12-v2)

```csharp
// Exemplo de chunk hierárquico
"Art. 1º ..."        → Chunk 0, Type: Article
"§ 1º ..."           → Chunk 1, Type: Paragraph  
"Art. 2º ..."        → Chunk 2, Type: Article
```

---

## Estados de um Documento

```csharp
public enum DocumentStatus
{
    Active,     // Documento atual
    Updated,    // Nova versão disponível
    Deleted,    // Soft delete (IsDeleted = true)
    Error       // Erro no processamento
}
```

---

## Transições de Estado

```
Discovery ──▶ [Active] 
                │
                ├── Update ──▶ Updated ──▶ [Active]
                │
                ├── Delete ──▶ Deleted
                │
                └── Error ──▶ Error ──▶ Retry ──▶ [Active/Deleted]
```

---

## Tabela de Persistência

| Fase | PostgreSQL | Elasticsearch | Memória |
|------|-----------|---------------|---------|
| Discovery | ❌ | ❌ | ⚡ (temp) |
| Fetch | ❌ (cache only) | ❌ | ⚡ (temp) |
| Parse | ❌ | ❌ | ⚡ (temp) |
| Normalize | ❌ | ❌ | ⚡ (temp) |
| Fingerprint | ❌ | ❌ | ⚡ (temp) |
| Deduplicate | ✅ (read) | ❌ | ⚡ (temp) |
| **Index** | ✅ **(write)** | ✅ **(write)** | ⚡ (temp) |
| Chunk+Embed | ✅ (write) | ❌ | ⚡ (temp) |

⚡ = transient (liberado após processamento)
