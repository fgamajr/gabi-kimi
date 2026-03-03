# Cross-Source Validation Framework for DOU Data

## Executive Summary

This document describes a comprehensive cross-source validation framework designed to ensure data quality, completeness, and accuracy across multiple DOU (Diário Oficial da União) data sources.

## 1. Validation Approaches

### 1.1 Document Count Matching

**Purpose:** Ensure all sources report similar document counts for the same time period.

**Implementation:**
- Compare total document counts per date across sources
- Flag discrepancies >10% as warnings, >20% as errors
- Account for source-specific exclusions (e.g., some sources may filter certain document types)

**Example:**
```
Date: 2024-01-15
  INLabs:     1,247 documents
  Leitura:    1,198 documents (96% of INLabs)
  Status:     ✓ Within acceptable range
```

### 1.2 Content Hash Comparison

**Purpose:** Verify that the same document contains identical content across sources.

**Implementation:**
- Normalize content (remove whitespace variations, signatures, headers)
- Compute SHA-256 hash of normalized text
- Flag mismatches for manual review

**Normalization Steps:**
1. Convert to lowercase
2. Remove accents (á → a)
3. Normalize whitespace
4. Remove signature blocks
5. Remove page headers/footers
6. Remove common stop words

### 1.3 Metadata Field Comparison

**Purpose:** Ensure consistent metadata (type, number, year, authority) across sources.

**Compared Fields:**
| Field | Weight | Tolerance |
|-------|--------|-----------|
| document_type | High | Exact match |
| document_number | High | Exact match |
| document_year | High | Exact match |
| title | Medium | Similarity ≥85% |
| issuing_organ | Medium | Exact match |
| publication_date | High | Exact match |

### 1.4 Temporal Coverage Verification

**Purpose:** Ensure all sources cover the same date range.

**Checks:**
- Minimum/maximum dates per source
- Gap detection (missing dates)
- Publication lag analysis (how quickly each source updates)

## 2. Document Fingerprinting

### 2.1 Unique Identification Strategy

Documents are identified using a hierarchical strategy:

#### Primary Key Strategy
```
natural_key = SHA256(document_type + "|" + document_number + "|" + document_year)
```

**Example:**
```python
# Portaria Nº 123/2024 from Ministério da Economia
natural_key = SHA256("portaria|123|2024")
```

#### Secondary Key Strategy (Fallback)
When number/year unavailable:
```
natural_key = SHA256(title_normalized + "|" + publication_date + "|" + issuing_organ)
```

### 2.2 Fingerprint Components

```python
@dataclass
class DocumentFingerprint:
    doc_type: str              # Normalized document type
    doc_number: Optional[str]  # Extracted number
    doc_year: Optional[int]    # Extracted year
    publication_date: str      # ISO format date
    edition_number: str        # Edition identifier
    section: str               # Section (1, 2, 3, etc.)
    content_hash: str          # Hash of normalized content
    title_normalized: str      # Normalized title
    issuing_organ: str         # Issuing organization
    natural_key_hash: str      # Computed natural key
```

### 2.3 Field Reliability Ranking

| Rank | Field | Reliability | Notes |
|------|-------|-------------|-------|
| 1 | document_type | High | Standardized vocabulary |
| 2 | document_number | High | Official identifier |
| 3 | document_year | High | Usually explicit |
| 4 | publication_date | High | Edition date |
| 5 | issuing_organ | Medium | May vary by source |
| 6 | title | Medium | Minor variations common |
| 7 | body_text | Medium | Formatting differences |
| 8 | page_number | Low | Source-specific |

## 3. Reconciliation Strategy

### 3.1 Source Hierarchy

**Default Priority Order:**
1. **INLabs** (official source) - Highest priority
2. **LeituraJornal** (official portal) - Medium priority
3. **Web Scraping** - Lowest priority

**Rationale:**
- INLabs is the official government data feed
- LeituraJornal is the official public portal
- Web scraping may have extraction errors

### 3.2 Conflict Resolution Rules

#### When Sources Disagree:

| Scenario | Resolution | Example |
|----------|------------|---------|
| Same ID, same content | Use hierarchy | INLabs wins |
| Same ID, different content | Manual review | Flag for investigation |
| Missing in lower priority | Use available | Single source OK |
| Missing in high priority | Warn | Data quality issue |
| Field null in high priority | Use lower priority | Fill gaps |

#### Reconciliation Strategies:

1. **Source Hierarchy** (default)
   - Always use highest-priority source
   - Fast, deterministic
   - May miss better data from lower sources

2. **Most Complete**
   - Use document with most populated fields
   - Good for filling gaps
   - May mix sources within document

3. **Most Recent**
   - Use most recently extracted/updated
   - Good for corrections
   - May be inconsistent

4. **Consensus**
   - Require >50% agreement across sources
   - Flag disputed fields
   - Conservative, many manual reviews

5. **Manual Review**
   - Flag all conflicts for human review
   - Highest accuracy
   - Highest cost

### 3.3 Reconciliation Metadata

Every reconciled document carries metadata:
```json
{
  "reconciliation_strategy": "source_hierarchy",
  "selected_source": "inlabs",
  "hierarchy_position": 0,
  "all_sources": ["inlabs", "leiturajornal"],
  "fields_from": {
    "title": "inlabs",
    "body_text": "inlabs",
    "document_number": "leiturajornal"
  }
}
```

## 4. Quality Metrics

### 4.1 Completeness Score

Formula:
```
completeness = 0.3×(docs_with_type/total) 
             + 0.25×(docs_with_number/total)
             + 0.15×(docs_with_year/total)
             + 0.3×(docs_with_body/total)
```

**Thresholds:**
- ≥95%: Excellent
- 90-95%: Good
- 80-90%: Acceptable
- <80%: Needs improvement

### 4.2 Accuracy Indicators

| Metric | Description | Target |
|--------|-------------|--------|
| Duplicate Rate | Documents with same natural key | <1% |
| Hash Conflicts | Same ID, different content | 0% |
| Consensus Rate | Documents matching across sources | >90% |

### 4.3 Timeliness Metrics

| Metric | Description | Target |
|--------|-------------|--------|
| Extraction Lag | Time from publication to extraction | <24h |
| Update Frequency | How often source is checked | Daily |
| Historical Coverage | Years of available data | >10 years |

### 4.4 Overall Quality Score

```
quality = 0.4×completeness + 0.35×consensus_rate + 0.25×(1 - error_rate)
```

## 5. Implementation

### 5.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    CrossSourceValidator                      │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│FingerprintEng│     │CrossSourceMat│     │DiscrepancyDet│
│   ine        │     │    cher      │     │   ector      │
└──────────────┘     └──────────────┘     └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                   ┌──────────────────┐
                   │ReconciliationEng │
                   │       ine        │
                   └──────────────────┘
```

### 5.2 Usage Example

```python
from validation.cross_source_validator import (
    CrossSourceValidator,
    SourceType,
    load_from_extraction_results,
)

# Load documents from each source
inlabs_docs = load_from_extraction_results(
    SourceType.INLABS, 
    Path("data/inlabs_extracted")
)
web_docs = load_from_extraction_results(
    SourceType.LEITURAJORNAL, 
    Path("data/web_extracted")
)

# Run validation
validator = CrossSourceValidator()
documents_by_source = {
    SourceType.INLABS: inlabs_docs,
    SourceType.LEITURAJORNAL: web_docs,
}
report = validator.validate(documents_by_source)

# Access results
print(f"Consensus rate: {report.consensus_rate:.1%}")
print(f"Discrepancies: {len(report.discrepancies)}")
```

### 5.3 CLI Usage

```bash
# Validate with real data sources
python3 cross_source_validate.py \
    --inlabs-zip data/inlabs/2024-01-15-DO1.zip \
    --web-dir data/web/2024-01-15 \
    --out validation_report/

# Validate with simulated secondary source
python3 cross_source_validate.py \
    --web-dir data/phase0/2023-01-probe/2023-01-02 \
    --simulate \
    --reconciliation hierarchy

# Available reconciliation strategies
python3 cross_source_validate.py --help
```

## 6. Discrepancy Types

### 6.1 MISSING_IN_SOURCE
Document exists in one source but not another.

**Severity:** Warning
**Action:** Check if document was filtered or genuinely missing

### 6.2 COUNT_MISMATCH
Significant difference in total document counts.

**Severity:** Error if >20%, Warning if >10%
**Action:** Investigate filtering rules or extraction issues

### 6.3 CONTENT_HASH_MISMATCH
Same natural key but different content hashes.

**Severity:** Error
**Action:** Manual review to determine authoritative version

### 6.4 METADATA_MISMATCH
Same document but different metadata values.

**Severity:** Warning
**Action:** Use reconciliation strategy to select authoritative value

### 6.5 TEMPORAL_GAP
Date coverage differs between sources.

**Severity:** Info/Warning
**Action:** Check source update schedules

### 6.6 FIELD_MISSING
Required field missing in a source.

**Severity:** Warning
**Action:** Check extraction rules or use fallback field

## 7. Recommendations

### 7.1 Production Deployment

1. **Daily Validation Schedule:**
   - Run cross-source validation daily after all extractions complete
   - Alert on critical discrepancies
   - Weekly quality trend reports

2. **Source Priority:**
   - Maintain INLabs as primary source
   - Use LeituraJornal for validation and gap-filling
   - Use web scraping as fallback only

3. **Escalation:**
   - Auto-reconcile when confidence >95%
   - Flag for manual review when confidence 70-95%
   - Alert immediately when confidence <70%

### 7.2 Future Enhancements

1. **Machine Learning:**
   - Train classifier to predict which source is more accurate
   - Learn from manual reconciliation decisions

2. **Additional Sources:**
   - Integrate LexML
   - Add Planalto.gov.br decreto database
   - Include tribunal-specific sources

3. **Real-time Validation:**
   - Validate during extraction pipeline
   - Reject documents that fail validation rules
   - Incremental validation for large datasets

## 8. Appendix: Validation Checklist

### Pre-deployment:
- [ ] All sources have extraction pipelines
- [ ] Fingerprinting tested on sample data
- [ ] Reconciliation strategy selected and documented
- [ ] Alert thresholds configured
- [ ] Manual review workflow established

### Daily Operations:
- [ ] Validation report generated
- [ ] Discrepancies reviewed
- [ ] Critical issues addressed
- [ ] Metrics trended

### Monthly Review:
- [ ] Completeness scores trending upward
- [ ] New discrepancy patterns identified
- [ ] Source reliability metrics updated
- [ ] Reconciliation rules refined
