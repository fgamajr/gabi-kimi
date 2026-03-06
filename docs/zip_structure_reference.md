> Last verified: 2026-03-06

# INLabs ZIP File Structure Analysis Report

Referencia tecnica de analise de ZIPs. O downloader ativo esta em [src/backend/ingest/zip_downloader.py](../src/backend/ingest/zip_downloader.py).

**Analysis Date:** 2026-03-02  
**Analyst:** Automated Analysis System  
**Data Source:** https://inlabs.in.gov.br/

---

## Executive Summary

This report documents the comprehensive analysis of INLabs ZIP file downloads containing DOU (Diário Oficial da União) publications. The analysis covers file structures, naming conventions, XML schemas, and statistical measurements across multiple dates and sections.

### Key Findings

| Metric | Value |
|--------|-------|
| Total ZIP Files Analyzed | 5 |
| Total XML Files | 4,095 |
| Total Image Files | 29 |
| Average XML Size | 3.18 KB |
| Average Image Size | 204.11 KB |
| PDF Signatures Present | No |

---

## 1. ZIP File Download Structure

### Download URL Format
```
https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=YYYY-MM-DD-SECTION.zip
```

Where SECTION is one of:
- `DO1` - Seção 1 (Executive, Legislative, Judicial branches)
- `DO2` - Seção 2 (Private sector notices)
- `DO3` - Seção 3 (Bidding, contracts, personnel)
- `DO1E` - Seção 1 Extra (Extraordinary edition)
- `DO2E` - Seção 2 Extra (Extraordinary edition)
- `DO3E` - Seção 3 Extra (Extraordinary edition)

### Available Sections by Date

Not all sections are published every day. Extra editions (DO*E) are published only when needed.

---

## 2. Internal File Structure

### 2.1 File Organization

ZIP files contain files in a **flat structure** (no subdirectories):

```
YYYY-MM-DD-SECTION.zip
├── XXX_YYYYMMDD_NNNNNNN.xml       (Main content files)
├── XXX_YYYYMMDD_NNNNNNN-N.xml     (Multi-part documents)
├── X_ORGNAME_DD_NNN.jpg           (Associated images)
└── ...
```

### 2.2 File Types Found

| Type | Extension | Count | Description |
|------|-----------|-------|-------------|
| XML Content | `.xml` | 4,095 | Main document content |
| JPEG Images | `.jpg` | 29 | Associated images/photos |
| PDF Files | `.pdf` | 0 | **Not present** |
| Signatures | `.p7s`, `.sig` | 0 | **Not present** |

---

## 3. Naming Conventions

### 3.1 XML File Naming Pattern

**Standard Format:** `XXX_YYYYMMDD_NNNNNNN.xml`

| Component | Description | Example |
|-----------|-------------|---------|
| `XXX` | Section/Journal Code | `515` (DO1), `529` (DO2), `530` (DO3), `600` (DO1E) |
| `YYYYMMDD` | Publication Date | `20260227` |
| `NNNNNNN` | Document ID (materia) | `23615168` |

**Multi-part Format:** `XXX_YYYYMMDD_NNNNNNN-N.xml`

Used when a document spans multiple files (e.g., `600_20260227_23639293-1.xml`, `-2.xml`, `-3.xml`)

#### Section Code Mapping

| Section | Code Range | Example |
|---------|------------|---------|
| DO1 | 515 | `515_20260227_23615168.xml` |
| DO2 | 529 | `529_20260227_23562729.xml` |
| DO3 | 530 | `530_20260227_22423649.xml` |
| DO1E | 600 | `600_20260227_23639224.xml` |

### 3.2 Image File Naming Pattern

**Format:** `X_ORGNAME_DD_NNN.jpg`

| Component | Description | Example |
|-----------|-------------|---------|
| `X` | Section number | `1` (DO1), `3` (DO3) |
| `ORGNAME` | Organization abbreviation | `MPESCA`, `INED`, `BCB` |
| `DD` | Day of month | `27` |
| `NNN` | Sequence number | `001`, `002` |

#### Organization Abbreviations Found

| Abbreviation | Organization |
|--------------|--------------|
| `MPESCA` | Ministério da Pesca e Aquicultura |
| `INED` | Instituto Nacional de Educação de Surdos |
| `BCB` | Banco Central do Brasil |

### 3.3 Naming Statistics

| Pattern | Count | Percentage |
|---------|-------|------------|
| Standard (XXX_YYYYMMDD_NNNNNNN.xml) | 3,994 | 97.5% |
| With Suffix (-N.xml) | 101 | 2.5% |
| Other | 0 | 0% |

---

## 4. XML Schema Structure

### 4.1 Document Hierarchy

```xml
<xml>
  <article [attributes]>
    <body>
      <Identifica />     <!-- Document title/identifier -->
      <Data />           <!-- Date (often empty) -->
      <Ementa />         <!-- Summary/abstract -->
      <Titulo />         <!-- Section title -->
      <SubTitulo />      <!-- Subsection title -->
      <Texto />          <!-- Main content (HTML) -->
    </body>
    <Midias>
      <Midia />          <!-- Media references (empty) -->
      ...
    </Midias>
  </article>
</xml>
```

### 4.2 Article Attributes (Metadata)

| Attribute | Description | Example |
|-----------|-------------|---------|
| `id` | Internal article ID | `"48080804"` |
| `name` | Document type name | `"PORTARIA INTERMINISTERIAL"` |
| `idOficio` | Ofício ID | `"11605005"` |
| `pubName` | Publication name | `"DO1E"` |
| `artType` | Article type | `"Portaria"` |
| `pubDate` | Publication date | `"27/02/2026"` |
| `artClass` | Classification code | `"00038:00000:00000:00000:..."` |
| `artCategory` | Category/organization | `"Ministério da Pesca e Aquicultura"` |
| `artSize` | Size code | `"12"` |
| `artNotes` | Notes | `"Extra"` or empty |
| `numberPage` | Page number | `"5"` |
| `pdfPage` | PDF viewer URL | `http://pesquisa.in.gov.br/...` |
| `editionNumber` | Edition number | `"39-A"` |
| `highlightType` | Highlight type | Empty or type |
| `highlightPriority` | Priority | Empty or value |
| `highlight` | Highlight flag | Empty or text |
| `highlightimage` | Highlight image | Empty or URL |
| `highlightimagename` | Highlight image name | Empty or name |
| `idMateria` | Materia ID | `"23639224"` |

### 4.3 Body Elements

#### Identifica
- Contains the document identification/title
- Format: CDATA
- Example: `PORTARIA INTERMINISTERIAL MPA/MMA Nº 51, DE 27 DE FEVEREIRO DE 2026`

#### Data
- Usually empty
- Occasionally contains document-specific date

#### Ementa
- Contains the document summary/abstract
- Format: CDATA
- May be empty for simple notices

#### Titulo
- Section or department title
- Example: `GABINETE DO MINISTRO`

#### SubTitulo
- Subsection title (often empty)

#### Texto
- Main document content
- Format: CDATA containing HTML
- HTML structure:
  ```html
  <p class="titulo">...</p>
  <p class="identifica">...</p>
  <p class="ementa">...</p>
  <p>...</p>  <!-- Regular paragraphs -->
  <p class="assina">...</p>  <!-- Signature block -->
  <p class="cargo">...</p>   <!-- Position/title -->
  ```

### 4.4 Midias Element

The `<Midias>` element contains empty `<Midia />` placeholders. The actual image files are included in the ZIP but are not referenced within the XML content. Images must be matched by filename convention.

---

## 5. Statistical Analysis

### 5.1 ZIP File Sizes by Section

| Section | ZIP Count | Avg ZIP Size | Total XMLs | Total Images |
|---------|-----------|--------------|------------|--------------|
| DO1 | 1 | 2.37 MB | 412 | 6 |
| DO2 | 1 | 1.11 MB | 900 | 0 |
| DO3 | 1 | 5.38 MB | 2,777 | 5 |
| DO1E | 2 | 1.40 MB | 6 | 18 |
| **Total** | **5** | **10.26 MB** | **4,095** | **29** |

### 5.2 XML File Size Statistics

| Metric | Value |
|--------|-------|
| Count | 4,095 |
| Average | 3.18 KB (3,254 bytes) |
| Median | 1.88 KB |
| Minimum | 1.02 KB |
| Maximum | 272.92 KB |
| 95th Percentile | 6.63 KB |

### 5.3 Image File Size Statistics

| Metric | Value |
|--------|-------|
| Count | 29 |
| Average | 204.11 KB |
| Median | ~140 KB |
| Minimum | 28.78 KB |
| Maximum | 773.24 KB |

### 5.4 Documents per Section

| Section | Avg XML per ZIP | Avg Images per ZIP |
|---------|-----------------|-------------------|
| DO1 | 412.0 | 6.0 |
| DO2 | 900.0 | 0.0 |
| DO3 | 2,777.0 | 5.0 |
| DO1E | 3.0 | 9.0 |

**Notes:**
- DO2 (Seção 2) contains no images - it publishes private sector notices
- DO1E (Extra editions) contain fewer documents but more images per document
- DO3 (Seção 3) contains the highest volume of documents (bidding, contracts)

---

## 6. Image Organization

### 6.1 Image Distribution

| Section | Images | Description |
|---------|--------|-------------|
| DO1 | 6 | Generic institutional photos |
| DO3 | 5 | BCB and INED photos |
| DO1E | 18 | MPESCA fishing quota documents |

### 6.2 Image Categories Found

1. **Institutional Photos**
   - `Fotos_produzidas_pelo_Senado_(...).jpg`
   - Government communication images

2. **Topic-based Banners**
   - `MAPA-Meteorologia Agrícola-red.jpg`
   - `MCIDA-Alimento-red.jpg`
   - `MD-Dia da Mulher-red.jpg`
   - `MDREG-Desastres Naturais-red.jpg`
   - `MMFDH-Crianças-red.jpg`

3. **Organization-specific**
   - `X_BCB_DD_NNN.jpg` - Central Bank documents
   - `X_INED_DD_NNN.jpg` - Education institute documents
   - `X_MPESCA_DD_NNN.jpg` - Fisheries ministry documents

---

## 7. Metadata and Signatures

### 7.1 PDF Signatures

**Result: NO PDF SIGNATURES FOUND**

The ZIP files do not contain:
- PDF files with embedded signatures
- Separate signature files (.p7s, .sig)
- Any cryptographic signature metadata

### 7.2 Available Metadata

The XML files contain rich metadata in the `<article>` element attributes:

- **Identification**: `id`, `idMateria`, `idOficio`
- **Classification**: `artClass`, `artCategory`, `artType`
- **Publication**: `pubName`, `pubDate`, `editionNumber`, `numberPage`
- **External Links**: `pdfPage` (link to PDF viewer)
- **Highlighting**: `highlightType`, `highlightPriority`, `highlightimage`

---

## 8. Data Quality Observations

### 8.1 Consistent Patterns

1. **XML Structure**: All XML files follow the same schema
2. **Naming Convention**: 100% adherence to naming patterns
3. **Encoding**: UTF-8 with CDATA sections for text content
4. **HTML in Texto**: Consistent HTML structure with class attributes

### 8.2 Variations

1. **Empty Elements**: `Data`, `Ementa`, `Titulo`, `SubTitulo` may be empty
2. **Multi-part Documents**: Large documents split with `-N` suffix
3. **Image References**: `<Midia />` elements are empty; images must be matched by filename

### 8.3 Edge Cases

- Documents with no images have empty `<Midias />` element
- Extra editions (DO*E) have fewer documents but higher image ratio
- Some documents have very long text content (up to 272 KB)

---

## 9. Recommendations for Data Processing

### 9.1 File Processing

1. **ZIP Download**: Use session-based authentication
2. **Extraction**: Extract all files to flat directory
3. **XML Parsing**: Use ElementTree with CDATA preservation
4. **Image Matching**: Match images to XML by filename convention, not internal references

### 9.2 Data Extraction

1. **Document ID**: Use `idMateria` attribute as unique identifier
2. **Content Extraction**: Parse HTML within `<Texto>` CDATA
3. **Metadata**: Extract all article attributes for indexing
4. **Image Association**: Link images by filename pattern matching

### 9.3 Validation

1. Verify XML well-formedness
2. Check for required fields: `idMateria`, `pubDate`, `Texto`
3. Validate section codes match expected values
4. Handle multi-part documents as single logical document

---

## 10. Appendix: Sample XML Structure

### 10.1 Simple Document (DO1)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <article id="48049441" 
           name="Acordaos - Processo Etico" 
           idOficio="11589967"
           pubName="DO1" 
           artType="Acórdão"
           pubDate="27/02/2026"
           artCategory="Entidades de Fiscalização..."
           numberPage="160"
           editionNumber="39"
           idMateria="23615168">
    <body>
      <Identifica><![CDATA[ ACÓRDÃO ]]></Identifica>
      <Data><![CDATA[]]></Data>
      <Ementa />
      <Titulo />
      <SubTitulo />
      <Texto><![CDATA[
        <p class="identifica">ACÓRDÃO</p>
        <p>Processo Ético nº 0096/2023...</p>
        <p class="assina">Raphael Castro Mota</p>
        <p class="cargo">Presidente do Conselho</p>
      ]]></Texto>
    </body>
    <Midias />
  </article>
</xml>
```

### 10.2 Complex Document with Images (DO1E)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <article id="48080804"
           name="PORTARIA INTERMINISTERIAL"
           pubName="DO1E"
           artType="Portaria"
           pubDate="27/02/2026"
           artCategory="Ministério da Pesca e Aquicultura"
           artNotes="Extra"
           numberPage="5"
           editionNumber="39-A"
           idMateria="23639224">
    <body>
      <Identifica><![CDATA[ PORTARIA INTERMINISTERIAL MPA/MMA Nº 51... ]]></Identifica>
      <Data><![CDATA[]]></Data>
      <Ementa><![CDATA[ Estabelece o limite de captura... ]]></Ementa>
      <Titulo><![CDATA[GABINETE DO MINISTRO ]]></Titulo>
      <SubTitulo />
      <Texto><![CDATA[
        <p class="titulo">GABINETE DO MINISTRO</p>
        <p class="identifica">PORTARIA INTERMINISTERIAL...</p>
        <p class="ementa">Estabelece o limite de captura...</p>
        ...
      ]]></Texto>
    </body>
    <Midias>
      <Midia></Midia>
      <Midia></Midia>
      ... (18 total)
    </Midias>
  </article>
</xml>
```

---

## 11. Technical Notes

### 11.1 Encoding
- Files use UTF-8 encoding
- Text content wrapped in CDATA sections
- HTML entities properly escaped in attributes

### 11.2 Date Formats
- XML filenames: `YYYYMMDD` (e.g., `20260227`)
- XML attributes: `DD/MM/YYYY` (e.g., `27/02/2026`)

### 11.3 Classification Codes
- `artClass`: Hierarchical code with colon separators
- Format: `AAAAA:BBBBB:CCCCC:...` (12 segments)
- Represents organizational hierarchy

---

## 12. Conclusion

The INLabs ZIP file structure is **well-organized and consistent**:

1. **Flat structure** with clear naming conventions
2. **Comprehensive XML schema** with rich metadata
3. **HTML content** within CDATA for formatting preservation
4. **Image files** included but not internally referenced
5. **No PDF or digital signatures** present
6. **Section-specific patterns** in document volume and image inclusion

This structure facilitates automated processing, indexing, and archival of DOU publications.

---

*Report generated from analysis of 5 ZIP files containing 4,095 XML documents and 29 images across DO1, DO2, DO3, and DO1E sections.*
