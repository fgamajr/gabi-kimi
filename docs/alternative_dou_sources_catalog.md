# Alternative Sources for DOU Data - Research Catalog

**Research Date:** March 2, 2026  
**Context:** GABI (Gerador Automatico de Boletins por Inteligencia Artificial) - Brazilian legal publications crawler

---

## Executive Summary

This catalog documents alternative sources for Diario Oficial da Uniao (DOU) data beyond the primary sources currently in use (INLabs authenticated API and leiturajornal public HTML). Sources are categorized by type, coverage, access method, and suitability for bulk data acquisition.

---

## Table of Contents

1. [Official Government Sources](#1-official-government-sources)
2. [Academic & Research Repositories](#2-academic--research-repositories)
3. [Commercial Legal Databases](#3-commercial-legal-databases)
4. [Internet Archive & Historical Sources](#4-internet-archive--historical-sources)
5. [Summary Comparison Matrix](#5-summary-comparison-matrix)

---

## 1. Official Government Sources

### 1.1 INLabs (Imprensa Nacional Labs) - PRIMARY

| Attribute | Details |
|-----------|---------|
| **URL** | https://www.gov.br/imprensanacional/pt-br |
| **API/Access** | Requires registration/authentication |
| **Coverage** | February 2018 - present (structured XML); 1998-2018 (PDF) |
| **Format** | XML (structured), PDF (scanned), HTML |
| **Update Frequency** | Daily |
| **Bulk Download** | Yes - Monthly ZIP archives containing XML files |
| **Cost** | Free (registration required) |
| **Licensing** | Public domain (Brazilian law) |

**Access Method:**
- Register at INLabs portal to obtain credentials
- Download monthly ZIP files containing XML documents
- Each ZIP contains hundreds/thousands of XML files organized by publication date
- XML Schema available upon request via LAI (Lei de Acesso a Informacao)

**Limitations:**
- Section 3 data (contracts, bids) only available as full PDF or HTML before 2018
- Section 1 and 2 available in structured XML since 2018
- Monthly bundles only available after month ends
- Rate limiting applies; IP blocking for excessive requests

**Data Volume:** Approximately 926,000 XML files per month (as of September 2023)

---

### 1.2 LexML Brasil

| Attribute | Details |
|-----------|---------|
| **URL** | https://www.lexml.gov.br |
| **API/Access** | SRU (Search/Retrieve via URL) API via Senado Federal |
| **Coverage** | 1.5+ million documents (as of 2010), multi-source legislation and jurisprudence |
| **Format** | XML, JSON (via API) |
| **Update Frequency** | Daily (harvested via OAI-PMH) |
| **Bulk Download** | No - API query only, no full database download |
| **Cost** | Free |
| **Licensing** | Open data (Creative Commons where applicable) |

**API Details:**
- Endpoint: `https://www12.senado.leg.br/dados-abertos/legislativo/legislacao/acervo-do-portal-lexml`
- Protocol: SRU (Search/Retrieve via URL) - Library of Congress standard
- Query Language: CQL (Contextual Query Language)
- Response formats: XML

**Features:**
- Unified search across Congress, Judiciary (STF, STJ, TST, TSE, TCU), and some state/municipal bodies
- Persistent identifiers (URN-LEX)
- Filters by locality, authority, document type, date
- OAI-PMH harvesting protocol for metadata

**Limitations:**
- No bulk download of complete database
- API documentation is complex (CQL queries)
- Focused on legislation/norms, not full DOU content
- No Section 3 (contracts/bids) data

---

### 1.3 Câmara dos Deputados - Dados Abertos

| Attribute | Details |
|-----------|---------|
| **URL** | https://dadosabertos.camara.leg.br |
| **API/Access** | REST API + Bulk file downloads |
| **Coverage** | Propositions from 1934-1945, complete from 2001; Deputies data from 1827 |
| **Format** | JSON, XML, CSV, XLSX, ODS |
| **Update Frequency** | Daily |
| **Bulk Download** | Yes - Complete datasets by year |
| **Cost** | Free |
| **Licensing** | Open data |

**Available Datasets:**
- Proposicoes (bills/propositions)
- Votacoes (voting records)
- Deputados (representatives)
- Eventos (committee meetings, sessions)
- Despesas (expenses by Cota Parlamentar)
- Orgaos (commissions, boards)

**API Endpoint:** `https://dadosabertos.camara.leg.br/swagger/api.html`

**Limitations:**
- Legislative focus only, not full DOU
- No executive branch content

---

### 1.4 Senado Federal - Dados Abertos

| Attribute | Details |
|-----------|---------|
| **URL** | https://www12.senado.leg.br/dados-abertos |
| **API/Access** | REST API + Bulk downloads |
| **Coverage** | Senate legislative data, includes LexML integration |
| **Format** | JSON, XML, CSV |
| **Update Frequency** | Daily |
| **Bulk Download** | Yes (some datasets) |
| **Cost** | Free |

**Features:**
- Senator information and expenses
- Legislative process data
- LexML integration for legal documents
- SIGA integration for budget data

---

### 1.5 Acervo Histórico do DOU (1808-2001)

| Attribute | Details |
|-----------|---------|
| **URL** | https://imprensa2.in.gov.br/ca/web/dou/dou/-/document_library/kcmautn6AnNs |
| **API/Access** | Web interface, manual download |
| **Coverage** | 1808 - 2001 (organized by section and year) |
| **Format** | PDF (digitized) |
| **Update Frequency** | Static archive |
| **Bulk Download** | No - Section/year navigation only |
| **Cost** | Free |

**Limitations:**
- No API access
- Manual navigation required
- PDF format only (requires OCR for text extraction)
- Not suitable for automated bulk acquisition

---

## 2. Academic & Research Repositories

### 2.1 Lume - Repositório Digital UFRGS

| Attribute | Details |
|-----------|---------|
| **URL** | https://lume.ufrgs.br |
| **API/Access** | DSpace repository interface |
| **Coverage** | Academic research, some DOU-related studies |
| **Format** | PDF, various |
| **Bulk Download** | Limited - item by item |
| **Cost** | Free |

**Status:**
- Could not access specific DOU collection (handle 10183/131388 returned 504 error)
- Likely contains research papers analyzing DOU data, not raw DOU archives
- May have historical collections of specific document types

**Recommendation:**
- Contact repository directly for specific DOU collections
- Useful for academic research on DOU content, not for bulk data acquisition

---

### 2.2 Arca Dados (Fiocruz)

| Attribute | Details |
|-----------|---------|
| **URL** | https://arcadados.fiocruz.br |
| **API/Access** | Dataverse platform |
| **Coverage** | Research data from Fiocruz (health, public policy) |
| **Format** | Various |
| **Bulk Download** | Dataset-dependent |
| **Cost** | Free (open science) |

**Status:**
- Health and public policy research focus
- May contain processed DOU data for specific research projects
- Not a primary source for raw DOU content

---

### 2.3 Repositório Alice (Embrapa)

| Attribute | Details |
|-----------|---------|
| **URL** | https://www.alice.cnptia.embrapa.br |
| **API/Access** | Institutional repository |
| **Coverage** | Agricultural research |
| **Format** | PDF, various |

**Status:**
- Agricultural research focus
- May contain normative acts related to agriculture from DOU
- Not a primary DOU source

---

## 3. Commercial Legal Databases

### 3.1 Escavador API

| Attribute | Details |
|-----------|---------|
| **URL** | https://api.escavador.com/v1/docs/ |
| **API/Access** | REST API with Bearer Token authentication |
| **Coverage** | DOU, tribunal diaries, process data |
| **Format** | JSON |
| **Update Frequency** | Real-time monitoring available |
| **Bulk Download** | API-based retrieval (rate limited: 500 req/min) |
| **Cost** | Pay-per-use (credit-based system) |
| **Licensing** | Commercial API access |

**Features:**
- V1: Search and monitoring of processes, people, companies, official diaries
- V2: Enhanced process search with more structured data
- Callback/webhook support for real-time updates
- Monitoramento (monitoring) of terms in Diarios Oficiais
- 500 requests per minute limit

**API Endpoints:**
- Search: `GET /api/v1/busca`
- Async results: `GET /api/v1/async/resultados`
- Monitoring: `POST /api/v2/monitoramentos/processos`
- Callbacks: Configurable webhook URLs

**Cost Structure:**
- Credit-based system (cost per request shown in `Creditos-Utilizados` header)
- Different credit costs for different operations
- Requires account and token generation

**Limitations:**
- Commercial service - costs scale with usage
- Not a primary source (aggregates from official sources)
- Rate limiting applies

---

### 3.2 JusBrasil

| Attribute | Details |
|-----------|---------|
| **URL** | https://www.jusbrasil.com.br/diarios/ |
| **API/Access** | Web interface (scraping not permitted by ToS) |
| **Coverage** | DOU, state and municipal diaries, judicial diaries |
| **Format** | HTML (web), PDF |
| **Bulk Download** | No official API for bulk download |
| **Cost** | Free (web), Premium subscription for advanced features |

**Features:**
- Comprehensive diary collection (federal, state, municipal, judicial)
- Search interface
- Historical access (dates vary by source)
- Legal case tracking

**Limitations:**
- No official API for bulk data access
- Terms of Service likely prohibit automated scraping
- Premium features require subscription
- Not suitable for automated bulk acquisition

---

### 3.3 Thomson Reuters - Legal One Firms Brazil

| Attribute | Details |
|-----------|---------|
| **URL** | https://developerportal.thomsonreuters.com/legal-one-firms-brazil |
| **API/Access** | REST API (commercial) |
| **Coverage** | Legal data for Brazil |
| **Format** | JSON |
| **Bulk Download** | API-based |
| **Cost** | Commercial (license required) |

**Status:**
- Enterprise legal management platform
- API for manipulating Legal One Firms Brazil product data
- Likely includes DOU content as part of legal research suite
- Contact Thomson Reuters for access and pricing

---

## 4. Internet Archive & Historical Sources

### 4.1 Internet Archive (archive.org) - Wayback Machine

| Attribute | Details |
|-----------|---------|
| **URL** | https://web.archive.org |
| **API/Access** | Wayback Machine CDX API, Memento protocol |
| **Coverage** | Snapshots of DOU website (inconsistent, based on crawls) |
| **Format** | HTML (archived web pages) |
| **Update Frequency** | Based on archive crawls (irregular) |
| **Bulk Download** | Possible with tools (wayback-machine-downloader) |
| **Cost** | Free |

**Access Methods:**
- CDX API: `http://web.archive.org/cdx/search/cdx?url=...`
- Memento protocol for temporal queries
- Tools: `wayback_machine_downloader` (Ruby gem)

**URL Patterns:**
- List all snapshots: `http://web.archive.org/web/*/http://domain/*`
- Specific snapshot: `http://web.archive.org/web/YYYYMMDDhhmmssid_/http://domain/page`

**Limitations:**
- Incomplete coverage (only crawled pages)
- Snapshot quality varies
- JavaScript-rendered content may not archive well
- INLabs portal may not be fully archived due to authentication requirements
- Suitable for recovery, not for systematic data collection

---

### 4.2 Repositório Legislativo - Câmara dos Deputados

| Attribute | Details |
|-----------|---------|
| **URL** | http://www2.camara.leg.br/legin |
| **API/Access** | Web interface |
| **Coverage** | Historical legislation (19th century - present) |
| **Format** | PDF, HTML |

**Features:**
- Legislative history research
- Historical DOU references
- Links to LexML

---

## 5. Summary Comparison Matrix

| Source | Coverage | Format | Bulk API | Cost | Best For |
|--------|----------|--------|----------|------|----------|
| **INLabs** | 1998-present (XML from 2018) | XML, PDF | Yes (ZIP) | Free | Primary source, bulk acquisition |
| **LexML Brasil** | 1.5M+ docs (multi-source) | XML, JSON | API only | Free | Legislative research, cross-reference |
| **Escavador API** | DOU + tribunals | JSON | API (credit) | Pay-per-use | Real-time monitoring, alerts |
| **JusBrasil** | DOU + state/municipal | HTML, PDF | No | Freemium | Manual research, case tracking |
| **Internet Archive** | Snapshots (incomplete) | HTML | Tools available | Free | Historical recovery |
| **Câmara Dados Abertos** | Legislative data | JSON, XML, CSV | Yes | Free | Legislative analysis |
| **Senado Dados Abertos** | Senate + LexML | JSON, XML | Partial | Free | Senate data, LexML access |
| **Acervo Histórico** | 1808-2001 | PDF | No | Free | Historical research |
| **Lume UFRGS** | Academic | Various | No | Free | Research papers |
| **Thomson Reuters** | Legal data | JSON | API | Commercial | Enterprise legal research |

---

## Recommendations for GABI Project

### Immediate Actions

1. **Register for INLabs access** if not already done - this is the most comprehensive official source with structured XML data
2. **Evaluate Escavador API** for real-time monitoring requirements (cost-benefit analysis needed)
3. **Implement LexML SRU API** for cross-referencing legislation and norms

### For Historical Data (pre-1998)

1. **Acervo Histórico (1808-2001)** - Manual access for specific date ranges
2. **Internet Archive** - Check for specific DOU website snapshots as fallback

### For Academic/Research Context

1. **Lume Repository** - Contact for any specific DOU-related research collections
2. **LexML** - Use for legislative context and norm cross-referencing

### Technical Considerations

| Consideration | Recommendation |
|--------------|----------------|
| **Authentication** | INLabs requires registration; Escavador requires API token |
| **Rate Limiting** | INLabs: IP-based limits; Escavador: 500 req/min; LexML: reasonable use |
| **Data Volume** | INLabs: ~1M XML files/month; plan storage accordingly |
| **Format Conversion** | INLabs XML to JSON (schema available); LexML XML parsing |
| **Update Strategy** | INLabs: monthly bundles; Escavador: real-time callbacks available |

---

## Data Completeness Assessment

| Source | Section 1 (Laws) | Section 2 (Personnel) | Section 3 (Contracts) | Historical |
|--------|-----------------|----------------------|----------------------|------------|
| INLabs (2018+) | XML | XML | PDF/HTML | No |
| INLabs (1998-2018) | PDF | PDF | PDF | No |
| LexML | Partial | No | No | Limited |
| Escavador | Yes | Yes | Yes | Limited |
| Acervo Histórico | PDF | PDF | PDF | 1808-2001 |

---

## API Technical Specifications

### INLabs XML Schema

Available upon request via LAI (Lei de Acesso a Informacao). Schema includes:
- `article` element with metadata attributes
- `body` element with HTML content
- `Texto` element with publication text
- `Midias` element for image captions
- `category` for hierarchical classification
- `signature` for signatory information

### LexML SRU Example

```
https://www12.senado.leg.br/dados-abertos/legislativo/legislacao/acervo-do-portal-lexml
?operation=searchRetrieve
&query=legislacao
&startRecord=1
&maximumRecords=10
```

### Escavador API Example

```bash
curl -X GET "https://api.escavador.com/api/v1/busca?q=DOU&qo=d&qs=d" \
    -H "Authorization: Bearer {token}" \
    -H "X-Requested-With: XMLHttpRequest"
```

---

## Conclusion

For the GABI project's purposes:

1. **INLabs remains the primary source** for bulk DOU data acquisition, especially for 2018+ structured XML data
2. **Escavador API** is the best commercial alternative for real-time monitoring and alerts
3. **LexML Brasil** provides valuable cross-referencing capabilities for legislative context
4. **Historical data (pre-1998)** requires manual access through Acervo Histórico or digitization from physical archives
5. **No single source** provides complete coverage from 1808-present in structured format

The recommended architecture combines:
- INLabs for bulk historical and ongoing data acquisition
- LexML for legislative metadata enrichment
- Escavador (if budget allows) for real-time monitoring of specific terms/entities

---

*Document generated by GABI research agent - March 2026*
