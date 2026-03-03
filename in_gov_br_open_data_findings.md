# IN.gov.br Open Data Findings

## Executive Summary

The IN.gov.br (Imprensa Nacional) provides DOU (Diário Oficial da União) open data through a web interface with downloadable XML files in ZIP format. The data is available from **2013 to present** across three sections (S01, S02, S03).

---

## 1. Page Structure Analysis

**Primary URL:** https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados

### Architecture:
- **Platform:** Liferay Portal (government CMS)
- **CDN:** Azion (Brazilian edge network)
- **Document Store:** Liferay Document Library (`/documents/`)

### Page Components:
1. **Information Panel** - Describes data format and access rules
2. **Year Selector** (`#ano-dados`) - Dropdown for year selection (2013-2026)
3. **Month Selector** (`#mes-dados`) - Populated dynamically via JavaScript
4. **Asset Publisher Portlet** - Displays file listings after selection

---

## 2. Direct Download Links

### File Naming Convention:
```
S{section}{month}{year}.zip
```

**Section Codes:**
- `S01` - Seção 01 (Presidency, ministries, federal agencies)
- `S02` - Seção 02 (Tender notices, contracts)
- `S03` - Seção 03 (Private sector notices)

**Month Codes:**
- 01-12 (January to December)

**Example:** `S01012025.zip` = Section 01, January 2025

### URL Pattern:
```
https://www.in.gov.br/documents/49035712/{folder_id}/{filename}/{uuid}?version=1.0&t={timestamp}&download=true
```

**Working Examples:**
- 2025/01: https://www.in.gov.br/documents/49035712/611333333/S01012025.zip/18340514-80e8-72b4-4c07-9bc58a129162?version=1.0&t=1738869650850&download=true
- 2013/01: https://www.in.gov.br/documents/49035712/50301183/S01012013.zip/ed456a8e-f93b-4e68-bba8-ec0423c4f44d?version=1.0&t=1542215234417&download=true

---

## 3. API Documentation

**Status: NO PUBLIC API AVAILABLE**

### Findings:
- ❌ **Hydra API documentation endpoint** (`/o/api/doc`) - Returns 403 Forbidden
- ❌ **CKAN API** (dados.gov.br) - Returns JavaScript-dependent page
- ❌ **REST endpoints** - No discoverable REST API
- ⚠️ **Internal APIs exist but are blocked/restricted**

### Search Functionality:
- The portal has a search portlet but it's designed for human interaction
- No documented JSON API endpoints
- Search uses Liferay's internal mechanisms

---

## 4. Bulk Data Dumps

**Format:** Monthly ZIP archives containing individual XML files

### Coverage:
| Attribute | Value |
|-----------|-------|
| **Start Date** | January 2013 |
| **End Date** | Current month |
| **Total Years** | 13+ years |
| **Sections** | 3 (S01, S02, S03) |
| **Update Frequency** | Monthly (first Tuesday of each month) |

### File Sizes (Examples):
- **S01012025.zip**: ~269 MB (January 2025, Section 1)
- **S01012013.zip**: ~5 MB (January 2013, Section 1)

### Growth Trend:
- **2013 files**: ~5-10 MB per section
- **2025 files**: 100-400 MB per section
- **Growth factor**: ~30x over 12 years

---

## 5. Machine-Readable Formats

### XML Schema (2025 format):
```xml
<xml>
  <article id="{unique_id}" 
           name="{filename}" 
           idOficio="{office_id}" 
           pubName="DO1" 
           artType="{type}" 
           pubDate="DD/MM/YYYY" 
           artClass="{classification_code}" 
           artCategory="{hierarchy}" 
           artSize="{size}" 
           numberPage="{page}" 
           pdfPage="{pdf_url}" 
           editionNumber="{edition}" 
           idMateria="{material_id}"
           highlightType=""
           highlightPriority=""
           highlight=""
           highlightimage=""
           highlightimagename="">
    <body>
      <Identifica><![CDATA[Title]]></Identifica>
      <Data><![CDATA[]]></Data>
      <Ementa><![CDATA[Summary/Abstract]]></Ementa>
      <Titulo />
      <SubTitulo />
      <Texto><![CDATA[HTML Content]]></Texto>
    </body>
    <Midias />
  </article>
</xml>
```

### XML Schema (2013 format - legacy):
```xml
<xml>
  <article numberPage="1" 
           pubName="DO1" 
           name="PORTARIA" 
           artType="PORTARIA" 
           pubDate="DD/MM/YYYY" 
           artCategory="{hierarchy}" 
           pdfPage="{url}" 
           editionNumber="1">
    <body>
      <Identifica><![CDATA[Title]]></Identifica>
      <Data />
      <Ementa>Summary</Ementa>
      <Texto><![CDATA[HTML Content]]></Texto>
      <Autores>
        <assina>Signatory</assina>
      </Autores>
    </body>
  </article>
</xml>
```

### Format Evolution:
| Feature | 2013 | 2025 |
|---------|------|------|
| `id` attribute | ❌ | ✅ |
| `idOficio` | ❌ | ✅ |
| `artClass` (classification code) | ❌ | ✅ |
| `artSize` | ❌ | ✅ |
| `idMateria` | ❌ | ✅ |
| `<Midias />` element | ❌ | ✅ |
| `<Titulo>` element | ❌ | ✅ |
| `<SubTitulo>` element | ❌ | ✅ |
| Embedded images | ❌ | ✅ (JPG files in ZIP) |

---

## 6. Data Dictionary Status

**CRITICAL GAP:**

> "O dicionário de dados, arquivo necessário para auxiliar no entendimento do conteúdo em XML, será disponibilizado em data a ser definida."

**Translation:** "The data dictionary, a file needed to assist in understanding the XML content, will be made available on a date to be defined."

**Status:** ❌ **NOT AVAILABLE** (as of March 2026)
- No published XSD schema
- No field documentation
- No attribute reference guide

---

## 7. Comparison to Other Sources

### vs. GABI Project's Current Approach:
| Aspect | IN.gov.br Open Data | GABI Web Scraping |
|--------|---------------------|-------------------|
| **Format** | XML (structured) | HTML (scraped) |
| **Completeness** | All sections | Targeted sections |
| **Images** | Included in ZIP | Not captured |
| **Metadata** | Rich XML attributes | Limited to visible HTML |
| **Timeliness** | Monthly batch | Daily real-time |
| **Consistency** | Fixed schema | Changes with site redesign |
| **API Access** | None | N/A (direct crawling) |

### vs. Dados.gov.br:
- IN.gov.br data is NOT properly cataloged on dados.gov.br
- dados.gov.br page requires JavaScript and has no functional API
- The link from IN.gov.br to dados.gov.br is essentially a dead end

---

## 8. What's Promised vs. What's Delivered

### Promised:
| Feature | Status |
|---------|--------|
| XML format open data | ✅ **DELIVERED** |
| ZIP compression | ✅ **DELIVERED** |
| Monthly updates | ✅ **DELIVERED** (first Tuesday of month) |
| Data dictionary | ❌ **NOT DELIVERED** ("date to be defined" since 2013) |
| Machine-readable catalog | ⚠️ **PARTIAL** (Liferay-based, not API-friendly) |
| API access | ❌ **NOT AVAILABLE** |

### Access Method:
- **Promised:** "Year > Month > file.zip" hierarchical access
- **Delivered:** Web form with JavaScript-dependent navigation
- **Reality:** Requires programmatic URL construction or browser automation

---

## 9. Data Quality Assessment

### Strengths:
✅ **Structured XML format** - Well-formed, parseable
✅ **Consistent metadata** - Publication dates, page numbers, categories
✅ **Hierarchical classification** - `artCategory` shows organizational hierarchy
✅ **PDF cross-references** - Links to certified PDF versions
✅ **Historical coverage** - 13+ years of data

### Weaknesses:
❌ **No data dictionary** - Field meanings undocumented
❌ **Schema evolution** - 2013 vs 2025 formats differ significantly
❌ **Missing unique IDs in older data** - 2013 files lack `id` attribute
❌ **Embedded media** - Modern files include images (increases complexity)
❌ **No API** - Must scrape or construct URLs manually

### Data Integrity Notes:
- ⚠️ **"Formato aberto não substitui versão certificada"** - XML does not replace certified PDF version
- ⚠️ **Large file sizes** - Recent files are 30x larger than 2013 files
- ⚠️ **Split files** - Large months split into multiple parts (e.g., `S01122024_Parte_01.zip`)

---

## 10. Recommendations

### For Data Consumers:
1. **Use ZIP downloads** for bulk historical analysis
2. **Parse XML directly** - Well-formed and consistent
3. **Handle schema evolution** - Support both 2013 and 2025 formats
4. **Request data dictionary** from IN.gov.br contact

### For GABI Project:
1. **Consider hybrid approach** - Use open data for historical, crawling for real-time
2. **XML parsing module** - Add extractor for IN.gov.br XML format
3. **Cross-reference validation** - Use PDF links for verification
4. **Archive ZIP files** - Maintain local copies (URLs have timestamps/tokens)

### For IN.gov.br:
1. **Publish data dictionary** - Document XML schema
2. **Enable CORS** - Allow API access to document library
3. **Provide stable URLs** - Remove timestamp tokens from download links
4. **Publish CKAN catalog** - Properly catalog on dados.gov.br

---

## Appendix: URL Construction Guide

### To get file listings:
```
https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados?ano={YYYY}&mes={MonthName}
```

Month names (Portuguese): Janeiro, Fevereiro, Março, Abril, Maio, Junho, Julho, Agosto, Setembro, Outubro, Novembro, Dezembro

### To download files:
Extract from page HTML or construct via Liferay API (requires authentication):
```
https://www.in.gov.br/documents/49035712/{folder_id}/{filename}/{uuid}?version=1.0&t={timestamp}&download=true
```

**Note:** UUIDs and timestamps are dynamic - must be scraped from page.

---

*Report generated: 2026-03-02*
*Data source: https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados*
