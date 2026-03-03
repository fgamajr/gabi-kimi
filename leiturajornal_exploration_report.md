# Leiturajornal DOU Data Source Exploration Report

## Test Methodology
- **Data Source**: https://www.in.gov.br/leiturajornal
- **Section**: DO1 (Diário Oficial - Seção 1)
- **Date Format**: DD-MM-YYYY
- **Data Location**: `<script id="params" type="application/json">` tag

## Test Results Summary

| Date | Day of Week | HTTP Status | Articles | Content Status |
|------|-------------|-------------|----------|----------------|
| 2016-01-01 | Friday (New Year's) | 200 | 0 | ✗ Empty |
| 2016-01-02 | Saturday | 200 | 0 | ✗ Empty |
| 2016-01-03 | Sunday | 200 | 0 | ✗ Empty |
| 2016-06-01 | Wednesday | 200 | 221 | ✓ Content |
| 2016-07-01 | Friday | 200 | 221 | ✓ Content |
| 2016-12-29 | Thursday | 200 | 0 | ✗ Empty |
| 2016-12-30 | Friday | 200 | 0 | ✗ Empty |
| 2016-12-31 | Saturday | 200 | 0 | ✗ Empty |

## JSON Structure

### Empty Response (no articles)
```json
{
  "typeNormDay": {
    "DO2ESP": false,
    "DO1ESP": false,
    "DO1A": false,
    "DO3E": false,
    "DO2E": false,
    "DO1E": false
  },
  "idPortletInstance": "Kujrw0TZC2Mb",
  "dateUrl": "01-01-2016",
  "section": "DO1",
  "jsonArray": []
}
```

### Article Response (with content)
```json
{
  "typeNormDay": {...},
  "idPortletInstance": "Kujrw0TZC2Mb",
  "dateUrl": "01-06-2016",
  "section": "DO1",
  "jsonArray": [
    {
      "pubName": "DO1",
      "urlTitle": "alvara-n-1-906-de-6-de-maio-de-2016-22926272",
      "numberPage": "27",
      "subTitulo": "",
      "titulo": "",
      "title": "ALVARÁ Nº 1.906, DE 6 DE MAIO DE 2016",
      "pubDate": "01/06/2016",
      "content": "ALVARÁ Nº 1.906...",
      "editionNumber": "103",
      "hierarchyLevelSize": 3,
      "artType": "ALVARÁ",
      "pubOrder": "DO1",
      "hierarchyStr": "Ministério da Justiça...",
      "hierarchyList": ["Ministério...", "DEPARTAMENTO...", "DIRETORIA..."]
    }
  ]
}
```

## Key Findings

### 1. Availability Pattern
- **DO1 is NOT published on weekends** (Saturday, Sunday) - confirmed by 01-02, 01-03, 12-31
- **DO1 is NOT published on holidays** - New Year's Day (01-01) had no content
- **DO1 IS published on regular weekdays** - June 1 and July 1 had 200+ articles each

### 2. Year-End Gap
The dates Dec 29-31, 2016 all show empty results:
- Dec 29 (Thursday) - Empty - **UNUSUAL**
- Dec 30 (Friday) - Empty - **UNUSUAL** 
- Dec 31 (Saturday) - Empty - Expected (weekend)

This suggests the DOU may have special publishing schedules around year-end holidays.

### 3. Article Structure
Each article contains:
- `pubName`: Publication section (DO1, DO2, etc.)
- `urlTitle`: URL-friendly title slug
- `title`/`titulo`: Article title (official designation)
- `content`: Full text content (truncated in listing)
- `pubDate`: Publication date (DD/MM/YYYY format)
- `editionNumber`: DOU edition number
- `numberPage`: Page number in print edition
- `artType`: Article type/category (e.g., "ALVARÁ", "PORTARIA")
- `hierarchyStr`/`hierarchyList`: Organizational hierarchy

### 4. Data Quality
- All requests returned HTTP 200 (success)
- Empty days return valid JSON with empty `jsonArray: []`
- No error messages in response - just empty arrays for non-publishing days
- Article counts vary: June 1 (221), July 1 (208)

## Crawler Implementation Notes

1. **Date format**: Use DD-MM-YYYY in URL
2. **Section parameter**: `secao=do1` (lowercase)
3. **JSON extraction**: Parse `<script id="params" type="application/json">`
4. **Empty check**: `len(jsonArray) == 0` means no articles for that date
5. **Weekend/holiday handling**: Expect empty results on non-business days
6. **Content date**: `pubDate` in articles uses DD/MM/YYYY format (different from URL format!)

## File Created
- `/home/parallels/dev/gabi-kimi/explore_leiturajornal.py` - Test script for exploring dates
