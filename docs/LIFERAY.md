# Liferay & The Imprensa Nacional (IN)

This document details how the Imprensa Nacional (IN) uses Liferay for the Diário Oficial da União (DOU) "Base de Dados" and how our project interacts with it.

## 1. The Platform: Liferay Portal

The Imprensa Nacional's data portal (`in.gov.br`) is built on **Liferay**, an enterprise Java-based content management system (CMS).

### Structure
Liferay organizes content hierarchically:
- **Group ID (`groupId`)**: A unique identifier for a "site" or organization within the portal.
    - For the DOU Base de Dados, the `groupId` is **`49035712`**.
- **Folder ID (`folderId`)**: Each monthly collection of files is stored in a specific folder.
    - Example: `50300481` corresponds to April 2002.
    - These IDs are **non-sequential** and must be scraped/discovered.
- **Documents**: The actual files (ZIPs, PDFs, XMLs) reside inside these folders.

### URL Patterns
The system exposes documents via predictable URL patterns:

```
https://www.in.gov.br/documents/{groupId}/{folderId}/{filename}
```

- **Example**: `https://www.in.gov.br/documents/49035712/50300481/S01042002.zip`

## 2. Our "Compass": The Registry

Since `folderId`s change arbitrarily every month, we cannot guess them. We maintain a "compass" file:

- **File**: `ops/data/dou_catalog_registry.json`
- **Purpose**: Maps every `YYYY-MM` to its corresponding Liferay `folderId`.
- **Generation**: Created by `ops/update_registry.py`.

### How Discovery Works
The script `ops/update_registry.py` reverse-engineers the Liferay structure by:
1.  Accessing the public "Base de Dados" page:
    `https://www.in.gov.br/acesso-a-informacao/dados-abertos/base-de-dados?ano=YYYY&mes=MonthName`
2.  Parsing the HTML to find download links.
3.  Extracting the `folderId` from the `href` attributes of those links using Regex:
    `/documents/49035712/(\d+)/...`

## 3. Data Ingestion Strategy

Instead of crawling the entire site blindly, we use the **Liferay Registry Strategy**:

1.  **Read Registry**: Load `dou_catalog_registry.json`.
2.  **Construct URLs**: For a given date (e.g., 2002-04-01), look up the `folderId` for "2002-04".
3.  **Direct Download**: Construct the URL `https://www.in.gov.br/documents/49035712/{folderId}/filename.zip` and download directly.

This bypasses the slow HTML navigation and allows for high-speed, direct asset retrieval.

## 4. Historical Context & Quirks

- **Platform Migrations**: The registry reveals "jumps" in `folderId` sequences, indicating underlying Liferay upgrades or data migrations at the Imprensa Nacional.
- **Filename Consistency**: While Liferay IDs change, the filenames inside the folders (e.g., `S01042002.zip`) generally follow a consistent `DDPPYYYY` or `S...` pattern, though variations exist (underscores, "Parte1", etc.).

## 5. Maintenance

If the download pipeline starts failing with 404s, it likely means:
1.  A new month has started and needs to be added to the registry.
2.  The Imprensa Nacional has migrated data, changing `folderId`s for existing months.

**Fix**: Run `python ops/update_registry.py` to refresh the compass.
