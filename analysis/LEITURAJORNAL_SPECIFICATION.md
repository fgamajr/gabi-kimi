# Leiturajornal HTML Structure Technical Specification

## 1. Overview

The leiturajornal endpoint serves the Brazilian Official Gazette (Diário Oficial da União - DOU) in HTML format with embedded JSON data containing article listings.

**Base URL:** `https://www.in.gov.br/leiturajornal`

## 2. URL Parameters

| Parameter | Format | Description | Example |
|-----------|--------|-------------|---------|
| `data` | DD-MM-YYYY | Publication date | `28-02-2025` |
| `secao` | string | Section identifier | `do1`, `do2`, `do3`, `do1e`, `do2e`, `do3e`, `do1a`, `do1esp`, `do2esp` |

### Section Values
- **DO1**: Seção 1 - Atos do Poder Executivo
- **DO2**: Seção 2 - Atos do Poder Judiciário e Ministério Público
- **DO3**: Seção 3 - Contratos, Editais e Outros Atos
- **DO1E**: Extra edition of DO1 (contains multiple sub-editions: DO1_EXTRA_A through DO1_EXTRA_H)
- **DO2E**: Extra edition of DO2 (contains sub-editions: DO2_EXTRA_A through DO2_EXTRA_D)
- **DO3E**: Extra edition of DO3
- **DO1A**: Administração section
- **DO1ESP**, **DO2ESP**: Special editions

## 3. Response Format

### 3.1 HTTP Headers
```
Content-Type: text/html;charset=UTF-8
Content-Encoding: gzip (when requested with --compressed)
Cache-Control: private, no-cache, no-store, must-revalidate
```

### 3.2 HTML Structure
```html
<!DOCTYPE html>
<html class="ltr" dir="ltr" lang="pt-BR">
<head>
    <title>Leitura do Jornal - Imprensa Nacional</title>
    <!-- ... -->
</head>
<body>
    <!-- ... -->
    <script id="params">
    {
        "typeNormDay": {...},
        "idPortletInstance": "Kujrw0TZC2Mb",
        "dateUrl": "28-02-2025",
        "section": "DO1",
        "jsonArray": [...]
    }
    </script>
    <!-- ... -->
</body>
</html>
```

## 4. JSON Schema

### 4.1 Root Object

| Field | Type | Description |
|-------|------|-------------|
| `typeNormDay` | object | Boolean flags for available special editions |
| `idPortletInstance` | string | Liferay portlet instance ID |
| `dateUrl` | string | Date in DD-MM-YYYY format |
| `section` | string | Requested section (may be comma-separated for extra editions) |
| `jsonArray` | array | Array of article objects |

### 4.2 typeNormDay Object

| Field | Type | Description |
|-------|------|-------------|
| `DO1E` | boolean | DO1 Extra edition available |
| `DO2E` | boolean | DO2 Extra edition available |
| `DO3E` | boolean | DO3 Extra edition available |
| `DO1A` | boolean | DO1 Admin section available |
| `DO1ESP` | boolean | DO1 Special edition available |
| `DO2ESP` | boolean | DO2 Special edition available |

### 4.3 Article Object (jsonArray items)

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `pubName` | string | Publication section name | `"DO1"`, `"DO2_EXTRA_B"` |
| `urlTitle` | string | URL-friendly slug | `"instrucao-normativa-no-1-de-27-de-fevereiro-de-2025-615354367"` |
| `numberPage` | string | Page number (as string) | `"6"`, `"347"` |
| `subTitulo` | string | Subtitle (usually empty) | `""` |
| `titulo` | string | Title variant (usually empty) | `""` |
| `title` | string | Full article title | `"INSTRUÇÃO NORMATIVA No 1, de 27 de FEVEREIRO de 2025"` |
| `pubDate` | string | Publication date (DD/MM/YYYY) | `"28/02/2025"` |
| `content` | string | Article excerpt (truncated at ~400 chars) | `"INSTRUÇÃO NORMATIVA N o 1..."` |
| `editionNumber` | string | Edition number | `"42"` |
| `hierarchyLevelSize` | integer | Number of hierarchy levels | 3 |
| `artType` | string | Article type/classification | `"Instrução Normativa"` |
| `pubOrder` | string | Sorting/ordering key | `"DO100008:00002:00006:..."` |
| `hierarchyStr` | string | Full hierarchy path (slash-separated) | `"Ministério da Agricultura/..."` |
| `hierarchyList` | array | Hierarchy as array of strings | `["Ministério", "Secretaria", ...]` |

## 5. Field Details

### 5.1 pubOrder Format
Colon-separated hierarchical code with 12 segments:
```
DO{section}{org_id}:{level2}:{level3}:...:{level12}
```
- Starts with `DO1`, `DO2`, or `DO3` + 5-digit organization code
- Each level is zero-padded to 5 digits
- Unused levels are `00000`

### 5.2 urlTitle Format
```
{type}-[{subtype}-]...-{date_parts}-{numeric_id}
```
Examples:
- `instrucao-normativa-no-1-de-27-de-fevereiro-de-2025-615354367`
- `portaria-n-845-gab-reit-ifma-de-27-de-fevereiro-de-2025-615383784`
- `aviso-de-reabertura-de-prazo-615572188`

### 5.3 artType Values
125+ distinct values including:
- Standard types: `Portaria`, `Decreto`, `Resolução`, `Instrução Normativa`
- Aviso variants: `Aviso de Licitação`, `Aviso de Homologação`, `Aviso de Adjudicação`
- Extrato variants: `Extrato de Contrato`, `Extrato de Termo Aditivo`
- Edital variants: `Edital de Concurso Público`, `Edital de Convocação`
- Case variations exist: `PORTARIA` vs `Portaria`

### 5.4 Content Field
- Truncated at approximately 400 characters
- Ends with `...` when truncated
- Contains article header/introduction text
- Full text available via separate article URL

## 6. Section Variations

### 6.1 Standard Sections (do1, do2, do3)
- `section` field matches request parameter (uppercase: DO1, DO2, DO3)
- `pubName` matches `section` for all articles
- Contains articles from single edition

### 6.2 Extra Editions (do1e, do2e, do3e)
- `section` field contains comma-separated list of all sub-editions
- Example: `"DO1E,DO1_EXTRA_E,DO1_EXTRA_F,DO1_EXTRA_G,DO1_EXTRA_H,DO1_EXTRA_A,DO1_EXTRA_B,DO1_EXTRA_C,DO1_EXTRA_D"`
- `pubName` in articles indicates specific sub-edition
- DO1E contains sub-editions A through H
- DO2E contains sub-editions A through D

## 7. Evolution Over Time

### 7.1 Schema Stability
- **2017-2025**: Core schema remains unchanged
- Same 14 fields present across all years
- No structural changes detected

### 7.2 Data Volume Changes
| Year | DO1 Articles | DO2 Articles | DO3 Articles |
|------|--------------|--------------|--------------|
| 2017 | ~229 | N/A (empty) | N/A |
| 2025 | ~338 | ~1,025 | ~3,436 |

### 7.3 Content Length
- Consistent 400-character limit on `content` field
- `content` length range: 178-403 characters

## 8. Edge Cases

### 8.1 Empty jsonArray
- Occurs on weekends and holidays
- `jsonArray: []` with HTTP 200 status
- Not an error condition

### 8.2 Special Characters
- Content uses UTF-8 encoding
- Portuguese diacritics: áéíóúãõâêîôûçÁÉÍÓÚÃÕÂÊÎÔÛÇ
- No HTML entities in JSON data (raw Unicode)

### 8.3 Field Variations
- `subTitulo` and `titulo` are typically empty strings
- `hierarchyList` length may not always match `hierarchyLevelSize`
- `numberPage` is string, not integer

### 8.4 Encoding
- HTML response is UTF-8
- Gzip compression supported (reduces size ~70-80%)

## 9. Pagination and AJAX

### 9.1 No Pagination
- All articles for a date/section returned in single request
- No `page`, `offset`, or `limit` parameters supported
- No AJAX loading detected

### 9.2 Complete Data
- `jsonArray` contains ALL articles for the requested date/section
- Large responses (DO3 can exceed 3.6MB uncompressed)

## 10. Metadata Availability

### 10.1 Available Fields for Filtering/Grouping
- `pubName`: Section/sub-edition
- `artType`: Article classification
- `hierarchyStr` / `hierarchyList`: Organizational hierarchy
- `numberPage`: Page location
- `editionNumber`: Edition identifier

### 10.2 URL Construction
Article detail URLs can be constructed as:
```
https://www.in.gov.br/en/web/dou/-/artigo/{urlTitle}
```

## 11. Error Conditions

| Scenario | Response | Indicator |
|----------|----------|-----------|
| Future date | Empty jsonArray | `jsonArray: []` |
| Weekend/Holiday | Empty jsonArray | `jsonArray: []` |
| Invalid section | Empty jsonArray | `jsonArray: []` |
| Malformed date | Redirect or error | URL unchanged |

## 12. Compression and Performance

### 12.1 Compression Ratios
| Section | Uncompressed | Gzipped | Ratio |
|---------|--------------|---------|-------|
| DO1 | ~495KB | ~85KB | 83% |
| DO2 | ~1.2MB | ~180KB | 85% |
| DO3 | ~3.6MB | ~520KB | 86% |

### 12.2 Recommended Request Headers
```
Accept-Encoding: gzip, deflate
User-Agent: Mozilla/5.0 (compatible; Bot/1.0)
```

## 13. Implementation Notes

### 13.1 Parser Requirements
1. Handle UTF-8 encoding properly
2. Support gzip decompression
3. Extract JSON from `<script id="params">` tag
4. Handle comma-separated section values
5. Normalize case for `artType` comparisons
6. Validate JSON before parsing

### 13.2 Data Quality Checks
1. Verify all required fields present
2. Check `pubName` consistency (or variation for extra editions)
3. Validate `pubDate` format (DD/MM/YYYY)
4. Handle empty arrays gracefully
