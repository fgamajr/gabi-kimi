# ADR 002: Sources.yaml Version 2 - Clean Configuration

**Status:** Proposed  
**Date:** 2026-02-12  
**Author:** GABI Team  
**Decision:** Adopt new sources.yaml structure aligned with modular architecture  

## Context

The current `sources.yaml` (v1) has grown organically and mixes multiple concerns:

```yaml
# v1 Problems:
- Mixed discovery/fetch/parse/mapping at same level
- Mapping is verbose and repetitive
- No clear contract boundaries
- Optional features (embed/index) deeply nested
- No reusable transforms/validation
```

## Decision

Adopt `sources_v2.yaml` with strict separation of concerns aligned to the modular architecture.

## Key Changes

### 1. Clear Phase Separation

**v1 (Mixed):**
```yaml
tcu_acordaos:
  discovery: { ... }
  fetch: { ... }
  parse: { ... }
  mapping: { ... }  # Where does this belong?
  lifecycle: { ... }
  indexing: { ... }  # Optional but at same level
  embedding: { ... }  # Optional but at same level
```

**v2 (Clear boundaries):**
```yaml
tcu_acordaos:
  identity: { ... }      # Who/what is this source
  discovery: { ... }     # Where to find (Layer 4a)
  fetch: { ... }         # How to retrieve (Layer 4b)
  parse: { ... }         # How to parse (Layer 4b)
  transform: { ... }     # Post-processing (Layer 4b)
  pipeline: { ... }      # Orchestration (Layer 5)
    optional:
      embed: { ... }     # Clearly optional
      index: { ... }     # Clearly optional
```

### 2. Field-Level Configuration

**v1 (Verbose mapping):**
```yaml
mapping:
  document_id: {from: "KEY", transform: strip_quotes}
  year: {from: "ANOACORDAO", transform: strip_quotes}
  text_relatorio: {from: "RELATORIO", transform: strip_quotes_and_html}
  # ... 20+ fields
```

**v2 (Semantic fields):**
```yaml
fields:
  document_id:
    source: KEY
    transforms: [strip_quotes]
    required: true
    
  content:
    source: ACORDAO
    transforms: [strip_quotes, strip_html]
    required: true
    store: true   # In PG
    index: true   # In ES
    chunk: true   # Create embeddings
    
  metadata:
    relator: {source: RELATOR, transforms: [strip_quotes]}
    # Flattened for clarity
```

### 3. Transform Registry

**v1 (Inline transforms):**
```yaml
transform: strip_quotes  # What is this? Where defined?
```

**v2 (Central registry):**
```yaml
# At end of file
transforms:
  strip_quotes:
    description: "Remove surrounding quotes"
    type: builtin
    
  strip_quotes_and_html:
    type: builtin
    pipeline: [strip_quotes, strip_html]  # Composable!
```

### 4. Streaming Configuration

**v1 (Hidden in parse):**
```yaml
parse:
  streaming: true
  batch_size: 10
  max_parse_size_bytes: 1073741824
```

**v2 (Explicit in fetch):**
```yaml
fetch:
  streaming:
    enabled: true
    chunk_size: 64KB
    queue_size: 1000
    decode_unicode: true
  limits:
    max_size: 1GB  # Safety guard
```

### 5. Document Composition

**v2 adds document template:**
```yaml
parse:
  document:
    id_template: "acordao-{number}/{year}"
    title_template: "Acórdão {number}/{year}"
    content_fields: [content, text_relatorio, text_voto, text_decisao]
```

### 6. Validation Rules

**v2 adds declarative validation:**
```yaml
transform:
  validate:
    - rule: required_fields
      fields: [document_id, year, number, content]
    - rule: field_format
      field: year
      pattern: "^\\d{4}$"
```

## Mapping to Code Architecture

```yaml
# sources_v2.yaml section → Code module
discovery:    → gabi/discover/
fetch:        → gabi/ingest/fetcher/
parse:        → gabi/ingest/parser/
transform:    → gabi/ingest/transforms/
pipeline:     → gabi/sync/
```

Each section maps to a specific app in the modular architecture.

## Benefits

1. **Single Source of Truth**: `sources.yaml` drives the entire pipeline
2. **Type Safety**: Can generate Pydantic models from schema
3. **IDE Support**: YAML structure guides configuration
4. **Validation**: Schema validation before runtime
5. **Documentation**: Self-documenting structure
6. **Extensibility**: Easy to add new transforms, sources, phases

## Migration Path

```python
# Migration script: v1 → v2
# 1. Read v1 YAML
# 2. Transform structure
# 3. Output v2 YAML
# 4. Validate against schema
```

## Backwards Compatibility

v2 is NOT backwards compatible. Options:

1. **Hard cut**: Rename sources.yaml → sources_v1.yaml, use sources_v2.yaml
2. **Dual support**: Code reads both versions during transition
3. **Migration script**: Auto-convert v1 to v2

**Recommendation**: Option 1 (hard cut) since we're doing a major refactor anyway.

## Schema Validation

```python
# Pydantic models for validation
from pydantic import BaseModel

class SourceConfig(BaseModel):
    identity: IdentityConfig
    discovery: DiscoveryConfig
    fetch: FetchConfig
    parse: ParseConfig
    transform: Optional[TransformConfig] = None
    pipeline: PipelineConfig
```

## Examples

### TCU Normas (587MB streaming)

```yaml
tcu_normas:
  discovery:
    strategy: static_url
    config:
      url: "https://sites.tcu.gov.br/dados-abertos/normas/arquivos/norma.csv"
      
  fetch:
    streaming:
      enabled: true  # Critical for 587MB file
      chunk_size: 64KB
      queue_size: 1000
    limits:
      max_size: 1GB
      
  parse:
    strategy: csv_row_to_document
    fields:
      content:
        source: TEXTONORMA
        transforms: [strip_quotes, strip_html]
        store: true
        index: true
        chunk: true
        
  pipeline:
    mode: full_reload
    optional:
      embed:
        enabled: true
        chunking:
          strategy: semantic
          unit: article
```

### TCU Acórdãos (Pattern-based)

```yaml
tcu_acordaos:
  discovery:
    strategy: url_pattern
    config:
      template: ".../acordao-completo-{year}.csv"
      parameters:
        year:
          type: range
          start: 1992
          end: current
          
  pipeline:
    mode: incremental
    schedule: "0 2 * * *"
```

## References

- ADR 001: Modular Architecture
- `sources.yaml` (v1 - current)
- `sources_v2.yaml` (v2 - proposed)
