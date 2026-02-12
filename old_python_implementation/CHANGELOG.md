# Changelog

All notable changes to GABI (Gerador Automático de Boletins por IA) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.1] - 2026-02-07

### Security
- Fixed SSRF vulnerability in fetcher (added URL validation and blocklist)
- Added input sanitization for Elasticsearch queries (prevent script injection)
- Fixed token revocation fail-open behavior (now fails closed)
- Added rate limiting race condition fix (Redis Lua scripts for atomicity)
- Implemented password masking using `SecretStr` for sensitive configuration

### Fixed
- Consolidated duplicate SearchService implementations (unified API/core services)
- Fixed schema type mismatches (date fields normalized to ISO 8601 strings)
- Fixed ES field path error (corrected `content.fields.vector` mapping)
- Added cascading soft delete for chunks (bulk update instead of N+1)
- Fixed async test decorators (proper `@pytest.mark.asyncio` usage)

### Improved
- Added true streaming for large files (chunked upload/download)
- Optimized LRU cache to O(1) (collections.OrderedDict)
- Added request coalescing for embeddings (deduplicate concurrent requests)
- Enhanced PDF parser with limits and OCR (memory protection, tesseract)
- Added comprehensive type aliases (`JsonDict`, `MetadataDict`, `EmbeddingVector`)
- Improved module docstrings with usage examples

### Added
- Added `__all__` exports to all package `__init__.py` files
- Created type aliases module in `types.py` for better readability
- Added CHANGELOG.md for version tracking

### Changed
- Moved `Environment` enum to `types.py` (single source of truth)
- Updated README.md with correct Docker Compose commands
- Added `SecretStr` type for password fields in settings

## [2.1.0] - 2026-01-15

### Added
- Hybrid search with Reciprocal Rank Fusion (RRF)
- pgvector support for semantic search
- TEI (Text Embeddings Inference) integration
- MCP (Model Context Protocol) server for ChatTCU
- Dead Letter Queue (DLQ) for failed operations
- Circuit breaker pattern for external services
- Comprehensive audit logging

### Changed
- Migrated from sync to async SQLAlchemy
- Upgraded to Pydantic v2
- Refactored pipeline to be fully async

## [2.0.0] - 2025-11-01

### Added
- Complete rewrite with FastAPI
- Elasticsearch 8.x integration
- JWT authentication with Keycloak
- Redis caching layer
- Celery background tasks
- Kubernetes deployment manifests

### Removed
- Legacy Flask implementation
- Direct PostgreSQL full-text search (replaced by ES)

## [1.0.0] - 2025-06-01

### Added
- Initial release
- Basic document ingestion
- Simple keyword search
- Web crawler for TCU sources
