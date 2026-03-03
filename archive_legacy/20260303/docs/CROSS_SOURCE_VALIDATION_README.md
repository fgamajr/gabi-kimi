# Cross-Source Validation Framework

## Overview

This framework provides comprehensive validation for DOU (Diário Oficial da União) data across multiple sources, ensuring data completeness, accuracy, and consistency.

## Quick Start

```bash
# Validate with available test data
python3 cross_source_validate.py --simulate

# Validate with specific data sources
python3 cross_source_validate.py \
    --inlabs-zip /path/to/inlabs.zip \
    --web-dir /path/to/web/html \
    --out validation_report/

# Use different reconciliation strategy
python3 cross_source_validate.py \
    --inlabs-zip /path/to/inlabs.zip \
    --simulate \
    --reconciliation consensus
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CrossSourceValidator                         │
│                    (validation/cross_source_validator.py)       │
└─────────────────────────────────────────────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌───────────────┐    ┌────────────────┐    ┌─────────────────┐
│  Fingerprint  │    │  Cross-Source  │    │  Discrepancy    │
│    Engine     │    │    Matcher     │    │    Detector     │
├───────────────┤    ├────────────────┤    ├─────────────────┤
│• Normalize    │    │• Match by      │    │• Count mismatch │
│  text         │    │  natural key   │    │• Content hash   │
│• Extract      │    │• Fuzzy match   │    │  mismatch       │
│  doc number   │    │• Perfect/probable│  │• Metadata diff  │
│• Compute hash │    │  matches       │    │• Temporal gap   │
└───────────────┘    └────────────────┘    └─────────────────┘
                               │
                               ▼
                  ┌────────────────────┐
                  │ ReconciliationEng  │
                  │    ine             │
                  ├────────────────────┤
                  │• Source hierarchy  │
                  │• Most complete     │
                  │• Most recent       │
                  │• Consensus         │
                  └────────────────────┘
```

## Components

### 1. FingerprintEngine
Creates unique document fingerprints for cross-source matching.

**Key Methods:**
- `normalize_text()` - Normalize text for comparison
- `normalize_doc_type()` - Normalize document type to canonical form
- `extract_doc_number()` - Extract document number from text
- `compute_content_hash()` - Compute normalized content hash

### 2. CrossSourceMatcher
Matches documents across multiple sources.

**Features:**
- Natural key matching (exact)
- Fuzzy title matching (85% similarity threshold)
- Content similarity comparison (90% threshold)
- Perfect and probable match classification

### 3. DiscrepancyDetector
Detects discrepancies between sources.

**Discrepancy Types:**
- `MISSING_IN_SOURCE` - Document exists in one source only
- `COUNT_MISMATCH` - Significant count differences
- `CONTENT_HASH_MISMATCH` - Same ID, different content
- `METADATA_MISMATCH` - Same ID, different metadata
- `TEMPORAL_GAP` - Date coverage differences

### 4. ReconciliationEngine
Resolves conflicts between sources.

**Strategies:**
- `SOURCE_HIERARCHY` - Use priority ranking (default)
- `MOST_COMPLETE` - Use source with most fields
- `MOST_RECENT` - Use most recently updated
- `CONSENSUS` - Require agreement across sources
- `MANUAL_REVIEW` - Flag for human review

## Document Fingerprinting

### Natural Key Strategy

**Primary:** `SHA256(doc_type + "|" + doc_number + "|" + doc_year)`

**Fallback:** `SHA256(title + "|" + date + "|" + organ)`

### Fingerprint Components

```python
@dataclass
class DocumentFingerprint:
    doc_type: str              # e.g., "portaria", "decreto"
    doc_number: Optional[str]  # Document number
    doc_year: Optional[int]    # Document year
    publication_date: str      # ISO date
    edition_number: str        # Edition
    section: str               # Section
    content_hash: str          # Content hash
    title_normalized: str      # Normalized title
    issuing_organ: str         # Organization
    natural_key_hash: str      # Computed key
```

## Quality Metrics

### Completeness Score
```
score = 0.3×(with_type/total) 
      + 0.25×(with_number/total)
      + 0.15×(with_year/total)
      + 0.3×(with_body/total)
```

### Thresholds
- ≥95%: Excellent
- 90-95%: Good
- 80-90%: Acceptable
- <80%: Needs improvement

## Source Priority (Default Hierarchy)

1. **INLabs** - Official government data feed
2. **LeituraJornal** - Official public portal
3. **Web Scraping** - Fallback extraction

## Usage Examples

### Basic Validation
```python
from validation.cross_source_validator import (
    CrossSourceValidator,
    SourceType,
    load_from_extraction_results,
    write_validation_report,
)

# Load documents
docs_by_source = {
    SourceType.INLABS: load_from_extraction_results(
        SourceType.INLABS, Path("data/inlabs")
    ),
    SourceType.LEITURAJORNAL: load_from_extraction_results(
        SourceType.LEITURAJORNAL, Path("data/web")
    ),
}

# Run validation
validator = CrossSourceValidator()
report = validator.validate(docs_by_source)

# Write report
write_validation_report(report, Path("validation_report"))
```

### Custom Reconciliation
```python
from validation.cross_source_validator import (
    CrossSourceValidator,
    ReconciliationStrategy,
)

validator = CrossSourceValidator(
    reconciliation_strategy=ReconciliationStrategy.CONSENSUS,
    source_hierarchy=[
        SourceType.INLABS,
        SourceType.LEITURAJORNAL,
    ]
)
```

### Reconciling a Match Group
```python
# Get a group of matched documents
match_group = report.cross_match.perfect_matches[0]

# Reconcile
authoritative_doc, metadata = validator.reconciler.reconcile(match_group)

print(f"Selected: {authoritative_doc.source.value}")
print(f"Strategy: {metadata['reconciliation_strategy']}")
```

## Output Files

| File | Description |
|------|-------------|
| `cross_source_report.json` | Complete validation results |
| `discrepancies.json` | All detected discrepancies |
| `metrics_{source}.json` | Per-source quality metrics |
| `summary.md` | Human-readable summary |

## Test Results

See [VALIDATION_TEST_RESULTS.md](VALIDATION_TEST_RESULTS.md) for detailed test results from 2026-02-27 DO1 edition.

**Summary:**
- 329 documents from INLabs
- 305 documents from simulated LeituraJornal
- 254 perfect matches (77.2%)
- 92.7% overall completeness
- 30 discrepancies (0 critical)

## Configuration

### Environment Variables
None required - all configuration via CLI or code.

### CLI Options
```
--inlabs-zip PATH       Path to INLabs ZIP file
--web-dir PATH          Path to web HTML directory
--parsed-dir PATH       Path to parsed JSON directory
--out PATH              Output directory (default: cross_validation_report)
--reconciliation STRAT  Strategy: hierarchy|complete|recent|consensus
--simulate              Simulate secondary source for testing
```

## Troubleshooting

### Issue: No matches found
**Cause:** Sources from different dates
**Solution:** Ensure all sources cover the same date range

### Issue: High discrepancy count
**Cause:** Different extraction rules
**Solution:** Standardize extraction rules across sources

### Issue: Low completeness score
**Cause:** Missing required fields
**Solution:** Check extraction rules for document_number, year

## API Reference

### Classes

#### `CrossSourceValidator`
Main entry point for validation.

**Methods:**
- `validate(documents_by_source) -> ValidationReport`

#### `FingerprintEngine`
Creates document fingerprints.

**Methods:**
- `from_extraction_result(source, data) -> DocumentFingerprint`
- `normalize_text(text) -> str`
- `compute_content_hash(body_text) -> str`

#### `CrossSourceMatcher`
Matches documents across sources.

**Methods:**
- `match_documents(documents_by_source) -> CrossMatchResult`

#### `ReconciliationEngine`
Reconciles conflicts.

**Methods:**
- `reconcile(match_group) -> (SourceDocument, dict)`

## License

Part of GABI (Gerador Automatico de Boletins por Inteligencia Artificial) project.
