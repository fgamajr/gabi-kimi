# Data Analysis Plan: 2002 DOU Dataset

## 1. Executive Summary
This document outlines the strategy for ingesting, analyzing, and structuring the 2002 Diário Oficial da União (DOU) dataset. The goal is to transition from raw XML files to a queryable, high-performance MongoDB Atlas database that supports hybrid search (Vector + BM25).

## 2. Data Source & Methodology

### 2.1 Source Identification
- **Provider**: Imprensa Nacional (IN).
- **Platform**: Liferay Portal (`in.gov.br`).
- **Access Method**: Direct ZIP download via reverse-engineered `folderId`.
- **Target Dataset**: January 2002 (Representative Month).
    - **Registry Entry**: `2002-01` → `folderId: 50300469`.
    - **Files**: `S01012002.zip` (Section 1), `S02012002.zip` (Section 2), `S03012002.zip` (Section 3).

### 2.2 Download Methodology
The download process uses the "Liferay Registry Strategy":
1.  Lookup `folderId` for the target month in `dou_catalog_registry.json`.
2.  Construct URL: `https://www.in.gov.br/documents/49035712/{folderId}/{filename}`.
3.  Download and unzip in-memory or to temporary storage.
4.  Iterate through extracted files (XMLs and Images).

*Note: 2002 data requires a robust retry mechanism (e.g., exponential backoff) due to server instability (504 Gateway Timeouts).*

## 3. XML Structure Analysis

Based on the analysis of `S03012002.zip` (5,817 files), the XML schema is flat and consistent.

### 3.1 Hierarchy
```xml
<xml>
  <article>
    <body>
      <Identifica>...</Identifica> <!-- Title/Header -->
      <Ementa>...</Ementa>         <!-- Abstract/Summary -->
      <Data>...</Data>             <!-- Date/Location line -->
      <Texto>...</Texto>           <!-- Main Content (HTML-like) -->
    </body>
  </article>
</xml>
```

### 3.2 Attributes (Metadata)
The `<article>` tag contains critical metadata:
- `pubName`: Publication Section (e.g., "DO3", "DO1").
- `pubDate`: Date string (e.g., "03/01/2002").
- `artType`: Article type (e.g., "Extrato de Contrato", "Portaria").
- `artCategory`: Hierarchical category path.
- `name`: Internal system name or title.
- `numberPage`: Page number in the physical edition.
- `pdfPage`: Reference to the PDF page.
- `editionNumber`: Issue number.

### 3.3 Data Types
- **Dates**: DD/MM/YYYY format. Needs conversion to ISO 8601 / `datetime`.
- **Text**: `Texto` contains HTML entities and tags (`<p>`, `<b>`, etc.). Needs sanitization for search but preservation for display.
- **Images**: Linked via filenames in attributes or `<img>` tags within `Texto`. (None found in Jan 2002 Section 3 sample, but common in Section 1).

## 4. MongoDB Schema Design

We will use a single collection `documents` to store all articles. This "Wide Collection" pattern works best for Atlas Search.

### 4.1 Collection: `documents`

We will adopt a rich, flat schema optimized for both search and enrichment.

| Field | Type | Description | Indexing |
| :--- | :--- | :--- | :--- |
| `_id` | String | Deterministic ID: `{YYYY-MM-DD}_{SECTION}_{FILENAME}` | Primary |
| `source_id` | String | Original XML filename | Unique Index |
| `source_zip` | String | Origin ZIP filename | Index |
| `pub_date` | Date | Publication date (ISO) | Index |
| `section` | String | "DO1", "DO2", "DO3" | Index + Facet |
| `edition` | String | Issue number | - |
| `page` | Int | Page number | - |
| `art_type` | String | Article type (e.g., "Portaria") | Index + Facet |
| `orgao` | String | Organization (e.g., "Ministério da Fazenda") | Index + Facet |
| `identifica` | String | Raw Title (Identifica) | Atlas Search (pt-br) |
| `ementa` | String | Raw Abstract (Ementa) | Atlas Search (pt-br) |
| `texto` | String | Raw Body (Texto) | Atlas Search (pt-br) |
| `content_html` | String | Preserved HTML content | - |
| `structured` | Object | Extracted fields: `act_number`, `act_year`, `signer` | - |
| `references` | Array | `[{ type: "revoga", target: "..." }]` | Index `target` |
| `enrichment` | Object | LLM-generated summary, tags, relevance score | Index `category`, `score` |
| `images` | Array | List of image objects (path, caption, alt_text) | - |
| `embedding` | Array | Vector embedding of content | Atlas Vector Search |
| `metadata` | Object | `ingestion_timestamp`, `processing_version` | - |
| `usage` | Object | `search_hits`, `shared_count` | - |

### 4.2 Indexing Strategy

**Atlas Search (`default`)**:
- **Analyzer**: `lucene.brazilian` (for `identifica`, `ementa`, `texto`, `enrichment.summary`).
- **Facets**: `section`, `art_type`, `orgao`, `enrichment.category`.

**Vector Search (`vector_index`)**:
- 1536 dimensions (OpenAI `text-embedding-3-small` standard).

**Standard Indexes**:
- `{ pub_date: -1 }`
- `{ section: 1, pub_date: -1 }`
- `{ art_type: 1 }`
- `{ orgao: 1 }`
- `{ "references.target": 1 }`

### 4.3 Image Handling Strategy
Although the Jan 2002 sample (Section 3) did not contain images, other sections often include them.

**Detection**:
- **HTML**: `<img>` tags in the `Texto` content (e.g., `<img src="Image1.jpg">`).
- **Attributes**: Some XMLs link images via attributes like `image="Image1.jpg"`.

**Schema for `images` Array**:
```json
[
  {
    "original_filename": "Image1.jpg",
    "storage_path": "s3://bucket/2002/01/Image1.jpg",
    "caption": "Optional caption found in XML",
    "width": 800,
    "height": 600
  }
]
```

**Storage Strategy**:
1.  **Extraction**: When parsing the ZIP, identify non-XML files (JPG, GIF, TIFF).
2.  **Upload**: Upload binary content to Object Storage (S3/MinIO).
3.  **Link**: Update the `documents.images` array with the storage path.
4.  **Content Patching**: Optionally replace `<img src="Image1.jpg">` in `content_html` with the public URL or a placeholder.

### 4.3 Indexing Strategy
1.  **Atlas Search Index (`default`)**:
    - Mapping: Dynamic (index all fields) OR Static mapping for `title`, `content`, `abstract`.
    - Analyzer: `lucene.brazilian` (Critical for Portuguese stemming/stopwords).
2.  **Vector Search Index (`vector_index`)**:
    - Field: `embedding`.
    - Dimensions: 768 (or model specific).
    - Similarity: Cosine.

## 5. Implementation Specification

### 5.1 Validation Rules
- **Date Parsing**: Fail batch if `pubDate` is malformed.
- **Content Check**: Ensure `Texto` is not empty.
- **Uniqueness**: Upsert based on `source_id` (filename) to prevent duplicates during re-runs.

### 5.2 Collection Strategy
- **Embedded vs. Separate**:
    - **Images**: Store metadata (filenames) embedded in the document. Store actual image blobs in S3/MinIO (or GridFS if strictly necessary, but S3 is preferred). For this phase, we might skip image storage or keep them in a separate `images` collection if metadata is complex.
    - **Decision**: **Embedded**. The image metadata is small and strictly belongs to the article.

## 6. Next Steps
1.  Refine `sync_dou.py` to implement the `download_and_extract` logic robustly.
2.  Implement the XML parser with `lxml` (faster than `xml.etree`) and Pydantic models for validation.
3.  Set up the MongoDB Atlas connection and Search Index.
