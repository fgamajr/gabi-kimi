# INLabs vs Leiturajornal Comparison - Executive Summary

## What Was Done

1. **Collected data from both sources:**
   - **Leiturajornal:** 268 documents from 2025-02-27 (DO1 section)
   - **INLabs:** 14 documents from sample data (2026-02-27, partial dataset)

2. **Analyzed metadata fields:**
   - Identified 14 fields in leiturajornal
   - Identified 20 fields in INLabs
   - Created semantic mapping between equivalent fields

3. **Compared content completeness:**
   - Measured total character counts
   - Analyzed content structure (plain text vs HTML)
   - Evaluated data quality metrics

4. **Attempted cross-source mapping:**
   - Developed matching algorithm using multiple criteria
   - Achieved 6 successful matches in sample

5. **Created deliverables:**
   - Detailed comparison report (markdown)
   - Structured field mapping (JSON)
   - Field comparison reference (markdown)
   - Analysis script (Python)

## Key Findings

### Document Counts
| Source | Count | Coverage |
|--------|-------|----------|
| Leiturajornal | 268 | Full DO1 section for date |
| INLabs | 14* | Partial sample from different date |

*Note: A same-date comparison requires working INLabs authentication.

### Metadata Richness
- **INLabs:** 20 fields including official IDs and technical metadata
- **Leiturajornal:** 14 fields focused on content and display

### Critical Differences

| Aspect | Leiturajornal | INLabs |
|--------|---------------|--------|
| **Authentication** | Not required | Required |
| **Unique ID** | None (use URL slug) | `id_materia` (8-digit official ID) |
| **Content Format** | Plain text | HTML in XML |
| **Organization Data** | Human-readable path | Machine-readable codes |
| **Best For** | Quick access, prototyping | Production, legal citation |

## Use Case Recommendations

### Use Leiturajornal When:
- Building public dashboards
- Rapid prototyping
- Text analysis (cleaner content)
- Authentication is not possible
- Need quick URL generation

### Use INLabs When:
- Building production pipelines
- Need official document IDs for legal citation
- Rich metadata required
- Archival storage
- Cross-referencing with other legal databases

## Field Mapping Available

A complete semantic mapping has been documented in:
- `dou_source_mapping.json` - Programmatic mapping
- `dou_field_comparison.md` - Human-readable reference

### Key Mappings
```
artType ↔ art_type (document type)
title ↔ identifica (document title)
numberPage ↔ number_page (page number)
editionNumber ↔ edition_number (edition)
pubDate ↔ pub_date (publication date)
content ↔ texto (full text)
hierarchyStr ↔ art_category (organization)
```

## Data Quality

Both sources show high quality:
- **Leiturajornal:** 100% title completeness
- **INLabs:** 100% identifica completeness
- No empty critical fields observed

## Files Created

1. **inlabs_leiturajornal_comparison.py** - Comparison script
2. **INLABS_LEITURAJORNAL_COMPARISON_REPORT.md** - Full detailed report
3. **dou_source_mapping.json** - Structured field mapping
4. **dou_field_comparison.md** - Field reference table
5. **COMPARISON_SUMMARY.md** - This file

## Raw Results Location

JSON output with complete analysis:
```
/tmp/dou_comparison/comparison_2025-02-27_do1.json
```

## Limitations

1. **Date mismatch:** INLabs sample is from 2026-02-27, not 2025-02-27
2. **Sample size:** INLabs data is partial (14 vs expected ~200+)
3. **Authentication:** INLabs credentials had issues during analysis
4. **Single section:** Only DO1 analyzed; DO2/DO3 may differ

## Next Steps (If Needed)

1. Retry with working INLabs credentials for same-date comparison
2. Extend analysis to DO2 and DO3 sections
3. Perform deep content comparison on matched documents
4. Test rate limits and reliability over time

## Conclusion

**Both sources are viable** but serve different purposes:

- **INLabs** is the authoritative source with official IDs and rich metadata
- **Leiturajornal** is more accessible and easier to integrate for public-facing applications

**Recommended approach:** Use INLabs as primary source, leiturajornal as fallback/verification.
