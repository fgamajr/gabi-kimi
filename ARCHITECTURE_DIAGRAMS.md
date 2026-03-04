# GABI Pipeline Automation - Architecture Diagrams

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         AUTOMATED PIPELINE                               │
│                    (Runs Daily at 2:00 AM via Systemd)                   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      PIPELINE ORCHESTRATOR                               │
│                  (ingest/orchestrator.py)                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Configuration: YAML/CLI                                          │   │
│  │ Error Handling: Retries, Circuit Breaker                         │   │
│  │ Reporting: JSON, Logs, Metrics                                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
        │   DISCOVERY     │ │   DOWNLOAD      │ │    INGEST       │
        │     PHASE       │ │     PHASE       │ │     PHASE       │
        └─────────────────┘ └─────────────────┘ └─────────────────┘
                    │               │               │
                    ▼               ▼               ▼
        ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
        │  in.gov.br      │ │  ZIP Files      │ │  PostgreSQL     │
        │  Catalog API    │ │  (Downloaded)   │ │  Registry       │
        └─────────────────┘ └─────────────────┘ └─────────────────┘
```

## Detailed Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         SYSTEMD TIMER                                    │
│                    gabi-ingest.timer                                     │
│  Schedule: Daily at 2:00 AM                                              │
│  Persistent: Yes (runs on boot if missed)                                │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      PIPELINE ORCHESTRATOR                               │
│                  ingest/orchestrator.py                                  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ PipelineConfig                                                    │  │
│  │ ├── data_dir: Path                                                │  │
│  │ ├── dsn: str                                                      │  │
│  │ ├── auto_discover: bool                                           │  │
│  │ ├── seal_commitment: bool                                         │  │
│  │ └── ...                                                           │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Phases:                                                            │  │
│  │ 1. Discovery → auto_discovery.discover_new_publications()         │  │
│  │ 2. Download → bulk_pipeline.run_pipeline()                        │  │
│  │ 3. Extract  → bulk_pipeline.run_pipeline()                        │  │
│  │ 4. Parse    → bulk_pipeline.run_pipeline()                        │  │
│  │ 5. Normalize→ bulk_pipeline.run_pipeline()                        │  │
│  │ 6. Ingest   → bulk_pipeline.run_pipeline()                        │  │
│  │ 7. Commit   → bulk_pipeline.run_pipeline()                        │  │
│  │ 8. Report   → orchestrator._generate_final_report()               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  DISCOVERY    │    │   DOWNLOAD    │    │    INGEST     │
│   MODULE      │    │   MODULE      │    │   MODULE      │
└───────────────┘    └───────────────┘    └───────────────┘
        │                    │                    │
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  REGISTRIES   │    │    STORAGE    │    │   DATABASE    │
│               │    │               │    │               │
│  ┌─────────┐  │    │  ┌─────────┐  │    │  ┌─────────┐  │
│  │Discovery│  │    │  │  ZIPs   │  │    │  │Registry │  │
│  │Registry │  │    │  │         │  │    │  │  Tables │  │
│  └─────────┘  │    │  └─────────┘  │    │  └─────────┘  │
│  ┌─────────┐  │    │  ┌─────────┐  │    │  ┌─────────┐  │
│  │ Download│  │    │  │ Extracted│  │    │  │Commit-  │  │
│  │ Registry│  │    │  │  XML    │  │    │  │ments    │  │
│  └─────────┘  │    │  └─────────┘  │    │  └─────────┘  │
└───────────────┘    └───────────────┘    └───────────────┘
```

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL SOURCES                                 │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  in.gov.br    │    │  Tags API     │    │  Catalog      │
│  Document     │    │  (Special     │    │  Registry     │
│  Library      │    │   Editions)   │    │  (JSON)       │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      DISCOVERY PHASE                                     │
│  ingest/auto_discovery.py                                                │
│                                                                          │
│  1. Query catalog for folder IDs                                         │
│  2. Probe URLs for monthly ZIPs                                          │
│  3. Query tags API for special editions                                  │
│  4. Compare against discovery registry                                   │
│  5. Return list of new publications                                      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      DOWNLOAD PHASE                                      │
│  ingest/zip_downloader.py                                                │
│                                                                          │
│  1. Build download targets                                               │
│  2. Check download registry (skip if exists)                             │
│  3. Download ZIPs with retry logic                                       │
│  4. Verify SHA-256 checksums                                             │
│  5. Update download registry                                             │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      EXTRACTION PHASE                                    │
│  ingest/zip_downloader.py (extract_xml_from_zip)                         │
│                                                                          │
│  1. Extract XML files from ZIPs                                          │
│  2. Extract images (PNG, JPG, etc.)                                      │
│  3. Validate file integrity                                              │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      PARSING PHASE                                       │
│  ingest/xml_parser.py                                                    │
│                                                                          │
│  1. Parse XML → DOUArticle objects                                       │
│  2. Sanitize malformed XML                                               │
│  3. Validate required fields                                             │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      NORMALIZATION PHASE                                 │
│  ingest/normalizer.py                                                    │
│                                                                          │
│  1. Compute identity hashes (natural_key_hash, content_hash)             │
│  2. Compute evidence hashes (edition_id, occurrence_hash)                │
│  3. Apply canonicalization (whitespace, quotes, signatures)              │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      INGESTION PHASE                                     │
│  dbsync/registry_ingest.py                                               │
│                                                                          │
│  1. Insert into registry.editions                                        │
│  2. Insert into registry.concepts                                        │
│  3. Insert into registry.versions                                        │
│  4. Insert into registry.occurrences                                     │
│  5. Log to registry.ingestion_log                                        │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      COMMITMENT PHASE                                    │
│  commitment/ + dbsync/registry_ingest.py                                 │
│                                                                          │
│  1. Compute CRSS-1 Merkle tree                                           │
│  2. Seal batch with cryptographic commitment                             │
│  3. Chain anchor to proofs/ directory                                    │
│  4. Persist to registry.commitments                                      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      REPORTING PHASE                                     │
│  ingest/orchestrator.py (_generate_final_report)                         │
│                                                                          │
│  1. Generate JSON report with metrics                                    │
│  2. Print summary to stderr                                              │
│  3. Return exit code (0=success, 1=failure)                              │
└─────────────────────────────────────────────────────────────────────────┘
```

## Database Schema Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL DATABASE                                 │
│                          (Schema: discovery)                             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
        │  publications   │ │   (indexes)     │ │   (views)       │
        │                 │ │                 │ │                 │
        │  • id (PK)      │ │  • section_date │ │  • statistics   │
        │  • section      │ │  • downloaded   │ │                 │
        │  • pub_date     │ │                 │ │                 │
        │  • filename     │ │                 │ │                 │
        │  • folder_id    │ │                 │ │                 │
        │  • discovered   │ │                 │ │                 │
        │  • downloaded   │ │                 │ │                 │
        │  • sha256       │ │                 │ │                 │
        └─────────────────┘ └─────────────────┘ └─────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL DATABASE                                 │
│                          (Schema: ingest)                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
        │ downloaded_zips │ │   (indexes)     │ │   (views)       │
        │                 │ │                 │ │                 │
        │  • id (PK)      │ │  • section_date │ │  • pending      │
        │  • section      │ │  • status       │ │  • statistics   │
        │  • pub_date     │ │  • downloaded   │ │                 │
        │  • filename     │ │                 │ │                 │
        │  • folder_id    │ │                 │ │                 │
        │  • file_size    │ │                 │ │                 │
        │  • sha256       │ │                 │ │                 │
        │  • status       │ │                 │ │                 │
        │  • error        │ │                 │ │                 │
        │  • retry_count  │ │                 │ │                 │
        └─────────────────┘ └─────────────────┘ └─────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                      POSTGRESQL DATABASE                                 │
│                          (Schema: registry)                              │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
        ┌───────────────┬───────────────┬───────────────┬───────────────┐
        │               │               │               │               │
        ▼               ▼               ▼               ▼               ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│   editions    │ │   concepts    │ │   versions    │ │ occurrences   │ │ingestion_log  │
│               │ │               │ │               │ │               │ │               │
│ • edition_id  │ │ • natural_    │ │ • id (PK)     │ │ • occurrence_ │ │ • id (PK)     │
│ • pub_date    │ │   key_hash    │ │ • natural_    │ │   hash (PK)   │ │ • occurrence_ │
│ • edition_num │ │ • strategy    │ │   key_hash    │ │ • edition_id  │ │   hash        │
│ • section     │ │               │ │ • content_    │ │ • version_id  │ │ • action      │
│ • listing_    │ │               │ │   hash        │ │ • page_num    │ │ • natural_    │
│   sha256      │ │               │ │ • body_text   │ │ • source_url  │ │   key_hash    │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘ │ • content_    │
                                                                        │   hash        │
                                                                        │ • edition_id  │
                                                                        │ • source_file │
                                                                        │ • decision_   │
                                                                        │   basis       │
                                                                        └───────────────┘
                                                                                │
                                                                                ▼
                                                                        ┌───────────────┐
                                                                        │ commitments   │
                                                                        │               │
                                                                        │ • id (PK)     │
                                                                        │ • crss_       │
                                                                        │   version     │
                                                                        │ • commitment_ │
                                                                        │   root        │
                                                                        │ • record_     │
                                                                        │   count       │
                                                                        │ • log_high_   │
                                                                        │   water       │
                                                                        │ • envelope    │
                                                                        └───────────────┘
```

## Component Interaction Diagram

```
┌─────────────┐
│   Systemd   │
│   Timer     │
└──────┬──────┘
       │ triggers
       │
       ▼
┌─────────────────────────────────────────────────────┐
│              Pipeline Orchestrator                   │
│              (orchestrator.py)                       │
└──────┬──────────────────────┬───────────────────────┘
       │                      │
       │ uses                 │ coordinates
       │                      │
       ▼                      ▼
┌──────────────┐      ┌─────────────────────────────┐
│  Discovery   │      │      Bulk Pipeline          │
│  Registry    │      │      (bulk_pipeline.py)     │
│  (PostgreSQL)│      └──────┬──────────────────────┘
└──────────────┘             │
                             │ uses
                             │
                    ┌────────┼────────┬────────┬────────┐
                    │        │        │        │        │
                    ▼        ▼        ▼        ▼        ▼
              ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
              │  ZIP   │ │ Extract│ │ Parse  │ │Normalize│ │ Ingest │
              │Download│ │  XML   │ │  XML   │ │        │ │   +    │
              │        │ │        │ │        │ │        │ │ Commit │
              └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
                    │        │        │        │        │
                    │        │        │        │        │
                    ▼        ▼        ▼        ▼        ▼
              ┌─────────────────────────────────────────────────┐
              │              PostgreSQL                          │
              │  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
              │  │   ingest    │  │  discovery  │  │ registry │ │
              │  │   schema    │  │   schema    │  │  schema  │ │
              │  └─────────────┘  └─────────────┘  └──────────┘ │
              └─────────────────────────────────────────────────┘
```

## State Transition Diagram (Download)

```
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │
                           │ start download
                           │
                           ▼
                    ┌─────────────┐
                    │  DOWNLOADING│
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           │ success       │ failure       │ timeout
           │               │               │
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │   SUCCESS   │ │   FAILED    │ │   FAILED    │
    │             │ │  (retryable)│ │ (retryable) │
    └─────────────┘ └──────┬──────┘ └──────┬──────┘
                           │               │
                           │ retry count < 3
                           │               │
                           └───────┬───────┘
                                   │
                                   ▼
                           ┌─────────────┐
                           │   FAILED    │
                           │  (terminal) │
                           └─────────────┘
```

## File System Layout

```
/opt/gabi/
├── .venv/                      # Python virtual environment
│   └── bin/
│       └── python
├── data/
│   ├── inlabs/                 # Downloaded ZIP files
│   │   ├── 2026-03_DO1.zip
│   │   ├── 2026-03_DO2.zip
│   │   └── ...
│   ├── extracted/               # Extracted XML files
│   │   ├── 2026-03_DO1/
│   │   │   ├── article1.xml
│   │   │   └── ...
│   │   └── ...
│   └── dou_catalog_registry.json  # Catalog registry
├── logs/
│   ├── pipeline_2026-03-03_02-00-01.json  # Pipeline reports
│   └── ...
├── config/
│   ├── production.yaml          # Pipeline configuration
│   └── systemd/
│       ├── gabi-ingest.service
│       └── gabi-ingest.timer
├── ingest/                     # Ingestion modules
│   ├── orchestrator.py
│   ├── auto_discovery.py
│   ├── discovery_registry.py
│   ├── bulk_pipeline.py
│   ├── zip_downloader.py
│   ├── xml_parser.py
│   ├── normalizer.py
│   └── ...
├── dbsync/                     # Database sync modules
│   ├── registry_ingest.py
│   ├── download_registry_schema.sql
│   └── ...
├── commitment/                 # CRSS-1 commitment modules
│   ├── crss1.py
│   └── ...
├── sources_v3.yaml             # Sources schema
├── sources_v3.identity-test.yaml  # Identity config
└── .env                        # Environment variables
```
